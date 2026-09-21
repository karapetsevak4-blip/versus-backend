"""Separate-connection snapshot/settlement races; parent runs these on PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless

from django.db import close_old_connections, connection, transaction, OperationalError

from . import gameplay
from .models import Team, TeamStats, User, UserBalance, UserOfice, UserTraders
from .team_stats import refresh_team_snapshot, snapshot_current_teams, team_snapshot
from .test_accrual import AccrualFixture


@skipUnless(connection.vendor == 'postgresql', 'Requires actual PostgreSQL row locks')
class TeamStatsConcurrencyTests(AccrualFixture):
    def race(self, *operations):
        barrier = Barrier(len(operations))

        def run(operation):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                barrier.wait(timeout=10)
                return operation()
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            futures = [executor.submit(run, operation) for operation in operations]
            return [future.result(timeout=15) for future in futures]

    def add_player(self, team):
        user = User.objects.create(tg_id=900000002)
        office = UserOfice.objects.create(user=user, ofice=self.basic)
        office.traders.add(UserTraders.objects.create(user=user, trader=self.trader))
        UserBalance.objects.create(user=user, team=team, my_ofice=office,
                                   accrual_updated_at=self.at)
        return user

    def test_duplicate_daily_jobs_create_one_snapshot_per_team(self):
        self.assertEqual(self.race(*(lambda: snapshot_current_teams(self.at) for _ in range(3))), [2, 2, 2])
        self.assertEqual(TeamStats.objects.count(), 2)
        self.assertEqual(TeamStats.objects.get(team=self.team).total_players, 1)

    def test_snapshot_and_two_settlements_keep_final_total_and_live_counts(self):
        other = self.add_player(self.team)
        at = self.at + timedelta(days=1)
        self.race(lambda: gameplay.settle(self.user.pk, at),
                  lambda: gameplay.settle(other.pk, at), lambda: snapshot_current_teams(at))
        stats = TeamStats.objects.get(team=self.team)
        self.assertEqual((stats.total_coins, stats.total_players, stats.total_traders,
                          stats.productivity_per_day), (40, 2, 2, 40))

    def test_snapshot_and_placement_keep_new_rate(self):
        trader = UserTraders.objects.create(user=self.user, trader=self.trader)
        self.race(lambda: gameplay.place_trader(self.user.pk, trader.pk, at=self.at),
                  lambda: snapshot_current_teams(self.at))
        stats = TeamStats.objects.get(team=self.team)
        self.assertEqual((stats.total_traders, stats.productivity_per_day), (2, 40))

    def test_opposing_team_requests_and_worker_have_consistent_lock_order(self):
        other = self.add_player(self.other_team)
        at = self.at + timedelta(days=1)
        results = self.race(lambda: team_snapshot(self.user.pk, at),
                            lambda: team_snapshot(other.pk, at), lambda: snapshot_current_teams(at))
        self.assertEqual(results[0]['my_position']['earn'], 20)
        self.assertEqual(results[1]['my_position']['earn'], 20)
        self.assertEqual(list(TeamStats.objects.order_by('team_id')
            .values_list('total_coins', flat=True)), [20, 20])

    def test_snapshot_waits_for_team_but_never_waits_for_balance_lock(self):
        def attempt():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '100ms'")
                return refresh_team_snapshot(self.team.pk, self.season, self.at).pk
            finally:
                connection.close()

        with transaction.atomic():
            Team.objects.select_for_update().get(pk=self.team.pk)
            with ThreadPoolExecutor(max_workers=1) as executor:
                with self.assertRaises(OperationalError) as failure:
                    executor.submit(attempt).result(timeout=10)
                self.assertIn('lock timeout', str(failure.exception))
        with transaction.atomic():
            UserBalance.objects.select_for_update().get(pk=self.balance.pk)
            with ThreadPoolExecutor(max_workers=1) as executor:
                self.assertIsInstance(executor.submit(attempt).result(timeout=10), int)
