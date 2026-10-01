from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.db import connection, IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from . import gameplay
from .models import (Ofice, Season, Team, TeamStats, Transaction, User,
                     UserBalance, UserOfice, UserTraders)
from .season_state import relevant_season
from .tasks import create_team_stats
from .team_stats import refresh_team_snapshot, snapshot_current_teams, team_snapshot
from .test_accrual import AccrualFixture
from .test_auth import signed_init_data


class TeamStateTests(AccrualFixture):
    def test_future_season_does_not_hide_current_in_any_path(self):
        future_a = Team.objects.create(name='Future A')
        future_b = Team.objects.create(name='Future B')
        future = Season.objects.create(first_team=future_a, second_team=future_b,
            active=True, start_time=self.at + timedelta(days=10),
            finish_time=self.at + timedelta(days=20))
        at = self.at + timedelta(days=1)
        self.assertEqual(relevant_season(at).pk, self.season.pk)
        main = gameplay.main_snapshot(self.user.pk, at)
        self.assertEqual((main['season']['id'], main['user_balance']['my_bank']), (self.season.pk, 20))
        self.assertEqual(team_snapshot(self.user.pk, at)['stats_first_team']['id'], self.team.pk)
        self.balance.team = None
        self.balance.save(update_fields=['team'])
        with self.assertRaises(gameplay.GameplayError):
            gameplay.choose_team(self.user.pk, future_a.pk, at)
        gameplay.choose_team(self.user.pk, self.other_team.pk, at)
        with patch('main.tasks.timezone.now', return_value=at):
            self.assertEqual(create_team_stats(), 2)
        self.assertFalse(TeamStats.objects.filter(season=future).exists())

    def test_future_only_does_not_create_stats_allow_choice_or_accrue(self):
        self.season.start_time = self.at + timedelta(days=2)
        self.season.save(update_fields=['start_time'])
        at = self.at + timedelta(days=1)
        self.assertIsNone(relevant_season(at))
        self.assertIsNone(gameplay.main_snapshot(self.user.pk, at)['season'])
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.my_bank, 0)
        self.assertEqual(snapshot_current_teams(at), 0)
        with self.assertRaises(gameplay.GameplayError):
            team_snapshot(self.user.pk, at)
        self.balance.team = None
        self.balance.save(update_fields=['team'])
        with self.assertRaises(gameplay.GameplayError):
            gameplay.choose_team(self.user.pk, self.team.pk, at)

    def test_ended_season_remains_visible_but_cannot_be_joined(self):
        self.season.finish_time = self.at + timedelta(days=1)
        self.season.active = False
        self.season.save(update_fields=['finish_time', 'active'])
        at = self.at + timedelta(days=2)
        self.assertEqual(gameplay.main_snapshot(self.user.pk, at)['season']['id'], self.season.pk)
        self.balance.team = None
        self.balance.save(update_fields=['team'])
        with self.assertRaises(gameplay.GameplayError):
            gameplay.choose_team(self.user.pk, self.team.pk, at)

    def test_one_missing_stats_team_http_returns_live_values_and_correct_series(self):
        # Deliberately wrong old snapshot must not control the current headline.
        legacy = TeamStats.objects.create(team=self.team, season=self.season,
            total_coins=900, total_players=12, total_traders=99, date=self.at)
        self.assertEqual(self.client.post('/api/create_session/',
            HTTP_AUTHORIZATION=signed_init_data()).status_code, 200)
        at = self.at + timedelta(days=1)
        with patch('main.team_stats.timezone.now', return_value=at):
            response = self.client.get('/api/get_data_team/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        first, second = data['stats_first_team'], data['stats_second_team']
        self.assertEqual((first['total_coins'], first['total_players'], first['total_traders'],
                          first['productivity_per_day']), (20, 1, 1, 20))
        self.assertEqual((second['total_coins'], second['total_players'], second['total_traders']), (0, 0, 0))
        self.assertEqual([row['productivity_per_day'] for row in first['all_day_productivity_per_day']], [0, 20])
        self.assertNotIn('total_coins', first['all_day_productivity_per_day'][-1])
        self.assertLess(first['all_day_total_coins'][0]['date'], first['all_day_total_coins'][1]['date'])
        legacy.refresh_from_db()
        self.assertEqual((legacy.total_coins, legacy.total_players, legacy.snapshot_day), (900, 12, None))

    def test_counts_and_production_follow_placement_and_office_upgrade(self):
        initial = team_snapshot(self.user.pk, self.at)
        self.assertEqual(initial['stats_first_team']['total_traders'], 1)
        extra = UserTraders.objects.create(user=self.user, trader=self.trader)
        # Owned inactive trader and orphan office do not contribute.
        orphan = UserOfice.objects.create(user=self.user, ofice=self.basic)
        orphan.traders.add(extra)
        self.assertEqual(team_snapshot(self.user.pk, self.at)['stats_first_team']['total_traders'], 1)
        gameplay.place_trader(self.user.pk, extra.pk, at=self.at)
        stats = TeamStats.objects.get(team=self.team)
        self.assertEqual((stats.total_traders, stats.productivity_per_day), (2, 40))
        pro = Ofice.objects.create(lvl=2, comfort=.05, safe_capacity=650,
            count_of_traders=5, price=15, currency=self.currency)
        gameplay.purchase(self.user.pk, 'ofice', pro.pk, at=self.at)
        stats.refresh_from_db()
        self.assertEqual(stats.productivity_per_day, 42)
        main = gameplay.main_snapshot(self.user.pk, self.at)['season']['first_team']
        self.assertEqual(main['total_players'], 1)
        self.assertAlmostEqual(main['ear_per_minute'], 42 / 1440)

    def test_current_configured_paid_boost_matches_office_rate(self):
        self.team.boost_team = 1.5
        self.team.save(update_fields=['boost_team'])
        self.assertEqual(team_snapshot(self.user.pk, self.at)['stats_first_team']['productivity_per_day'], 20)
        Transaction.objects.create(user=self.user, price=1, completed=True)
        self.assertEqual(team_snapshot(self.user.pk, self.at)['stats_first_team']['productivity_per_day'], 30)
        main = gameplay.main_snapshot(self.user.pk, self.at)['season']['first_team']
        self.assertEqual(main['boost_team'], 50)
        self.assertAlmostEqual(main['ear_per_minute'], 30 / 1440)

    def test_daily_snapshots_are_utc_idempotent_and_previous_day_is_immutable(self):
        before = self.at + timedelta(hours=23)
        # 02:00 Moscow is still the same UTC day.
        local_before = before.astimezone(dt_timezone(timedelta(hours=3)))
        snapshot_current_teams(local_before)
        snapshot_current_teams(local_before)
        first = TeamStats.objects.get(team=self.team)
        self.assertEqual(first.snapshot_day, self.at.date())
        at = self.at + timedelta(days=1)
        gameplay.settle(self.user.pk, at)
        snapshot_current_teams(at)
        first.refresh_from_db()
        self.assertEqual(first.total_coins, 0)
        self.assertEqual(list(TeamStats.objects.filter(team=self.team).order_by('snapshot_day')
            .values_list('total_coins', flat=True)), [0, 20])
        snapshot_current_teams(before)  # Reordered/retried task cannot backfill today's state.
        first.refresh_from_db()
        self.assertEqual(first.total_coins, 0)
        self.assertEqual(TeamStats.objects.count(), 4)

    def test_old_timestamp_does_not_overwrite_newer_same_day_snapshot(self):
        later = self.at + timedelta(hours=12)
        gameplay.settle(self.user.pk, later)
        original = TeamStats.objects.get(team=self.team)
        refresh_team_snapshot(self.team.pk, self.season, self.at)
        original.refresh_from_db()
        self.assertEqual((original.date, original.total_coins), (later, 10))

    def test_delayed_settlement_refreshes_latest_observation_without_rewriting_past_day(self):
        first = refresh_team_snapshot(self.team.pk, self.season, self.at)
        later = self.at + timedelta(days=1)
        newest = refresh_team_snapshot(self.team.pk, self.season, later)
        # An earlier API/worker timestamp can obtain the team lock last.
        self.assertEqual(gameplay.settle(self.user.pk, self.at + timedelta(hours=12)), 10)
        first.refresh_from_db()
        newest.refresh_from_db()
        self.assertEqual((first.total_coins, first.date), (0, self.at))
        self.assertEqual((newest.total_coins, newest.date, newest.snapshot_day), (10, later, later.date()))

    def test_delayed_same_day_settlement_is_not_dropped_from_snapshot(self):
        later = self.at + timedelta(hours=12)
        snapshot = refresh_team_snapshot(self.team.pk, self.season, later)
        self.assertEqual(gameplay.settle(self.user.pk, self.at + timedelta(hours=6)), 5)
        snapshot.refresh_from_db()
        self.assertEqual((snapshot.total_coins, snapshot.date), (5, later))

    def test_history_preserves_legacy_rows_but_displays_one_value_per_day(self):
        first = TeamStats.objects.create(team=self.team, season=self.season,
            total_coins=1, date=self.at)
        second = TeamStats.objects.create(team=self.team, season=self.season,
            total_coins=2, date=self.at + timedelta(hours=1))
        data = team_snapshot(self.user.pk, self.at + timedelta(days=1))
        history = data['stats_first_team']['all_day_total_coins']
        self.assertEqual([row['total_coins'] for row in history], [2, 20])
        self.assertTrue(TeamStats.objects.filter(pk=first.pk).exists())
        self.assertTrue(TeamStats.objects.filter(pk=second.pk).exists())

    def test_leaderboard_descends_with_stable_ties_and_same_personal_rank(self):
        self.balance.earn_in_team_per_month = 70
        self.balance.save(update_fields=['earn_in_team_per_month'])
        self.team.money_team = 300
        self.team.save(update_fields=['money_team'])
        leaders = []
        for index, score in enumerate((100, 100, 5)):
            user = User.objects.create(tg_id=900000010 + index)
            leaders.append(UserBalance.objects.create(user=user, team=self.team,
                earn_in_team_per_month=score))
        data = team_snapshot(self.user.pk, self.at)
        ranking = data['leaderboard_first_team']
        self.assertEqual([row['earn'] for row in ranking], [100, 100, 70, 5])
        self.assertEqual([row['position'] for row in ranking], [1, 1, 3, 4])
        self.assertEqual([row['id'] for row in ranking[:2]], [leaders[0].pk, leaders[1].pk])
        self.assertEqual(data['my_position']['position'], 3)
        self.assertEqual(data['my_position']['tg_name'], '')
        self.assertEqual(data['stats_first_team']['total_players'], 4)
        self.assertEqual(data['stats_first_team']['total_traders'], 1)

    def test_canonical_snapshot_identity_has_database_constraint(self):
        refresh_team_snapshot(self.team.pk, self.season, self.at)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeamStats.objects.create(team=self.team, season=self.season, snapshot_day=self.at.date())


class SnapshotMigrationTests(TransactionTestCase):
    def test_legacy_duplicate_rows_are_preserved_without_guessing_day(self):
        old = [('main', '0027_unique_telegram_identity')]
        new = [('main', '0028_team_snapshot_day')]
        executor = MigrationExecutor(connection)
        executor.migrate(old)
        try:
            apps = executor.loader.project_state(old).apps
            team = apps.get_model('main', 'Team').objects.create(name='Legacy')
            at = datetime(2026, 9, 1, tzinfo=dt_timezone.utc)
            season = apps.get_model('main', 'Season').objects.create(start_time=at, finish_time=at)
            old_stats = apps.get_model('main', 'TeamStats')
            for value in (7, 9):
                old_stats.objects.create(team=team, season=season, date=at, total_coins=value)
            MigrationExecutor(connection).migrate(new)
            self.assertEqual(list(TeamStats.objects.order_by('pk').values_list(
                'total_coins', 'snapshot_day')), [(7, None), (9, None)])
        finally:
            MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
