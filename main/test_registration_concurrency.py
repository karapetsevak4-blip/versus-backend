"""Registration/identity races on actual PostgreSQL connections."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection, transaction
from django.db.models.query import QuerySet
from django.test import Client, override_settings

from . import registration
from .models import User, UserBalance, UserOfice, UserStatistics, UserTraders
from .test_auth import signed_init_data
from .test_registration import RegistrationFixture


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL identity/row-lock behavior')
class RegistrationConcurrencyTests(RegistrationFixture):
    def race(self, *operations):
        start = Barrier(len(operations))

        def run(operation):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                start.wait(timeout=10)
                return operation()
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            futures = [executor.submit(run, operation) for operation in operations]
            return [future.result(timeout=20) for future in futures]

    @override_settings(CLOSED_TEST_MODE=True, TELEGRAM_TESTER_IDS=(900000001, 900000002),
                       FUNDED_TESTER_ID=900000001)
    def test_two_first_http_logins_create_one_player_and_one_referral_reward(self):
        inviter = registration.register_player({'id': 900000002}, at=self.at)
        both_absent = Barrier(2)
        original_get = QuerySet.get

        def synchronized_get(queryset, *args, **kwargs):
            try:
                return original_get(queryset, *args, **kwargs)
            except User.DoesNotExist:
                if queryset.model is User and kwargs == {'tg_id': self.metadata['id']}:
                    # Force both first lookups to see no identity before either
                    # INSERT; then prove the database arbitrates the conflict.
                    both_absent.wait(timeout=10)
                raise

        init_data = signed_init_data(user=self.metadata)

        def login():
            response = Client().post('/api/create_session/?refer_id=900000002',
                                     HTTP_AUTHORIZATION=init_data)
            return response.status_code

        with patch.object(QuerySet, 'get', synchronized_get):
            self.assertEqual(self.race(login, login), [200, 200])
        player = User.objects.get(tg_id=self.metadata['id'])
        self.assertEqual(player.referrer_id, inviter.pk)
        balance = UserBalance.objects.get(user=player)
        self.assertEqual((balance.game_coin, balance.token_money), (10000, 1000))
        self.assertEqual((UserOfice.objects.filter(user=player).count(),
                          UserTraders.objects.filter(user=player).count(),
                          UserStatistics.objects.filter(user=player).count()), (1, 1, 1))
        self.assertEqual(UserBalance.objects.get(user=inviter).game_coin, 0)
        self.assertEqual(UserStatistics.objects.get(user=inviter).friends_are_inv, 1)

    def test_two_logins_increment_new_day_once(self):
        player = registration.register_player(self.metadata, at=self.at)
        at = self.at + timedelta(days=1)
        self.race(lambda: registration.register_player(self.metadata, at=at),
                  lambda: registration.register_player(self.metadata, at=at))
        player.refresh_from_db()
        self.assertEqual((player.count_of_visit, player.visit_without_pass), (2, 2))
        self.assertEqual(player.last_visit, at.date())

    def test_login_and_profile_change_preserve_both_updates(self):
        player = registration.register_player(self.metadata, at=self.at)
        self.race(lambda: registration.register_player(self.metadata, at=self.at + timedelta(days=1)),
                  lambda: registration.change_nickname(player.pk, 'updated-name'))
        player.refresh_from_db()
        self.assertEqual((player.count_of_visit, player.tg_username), (2, 'updated-name'))

    def test_profile_waits_for_ban_transaction_and_cannot_restore_old_state(self):
        player = registration.register_player(self.metadata, at=self.at)
        started = Event()

        def attempt():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                started.set()
                try:
                    registration.change_nickname(player.pk, 'blocked-name')
                except registration.PlayerError as exc:
                    return exc.code
                return 'unexpected_success'
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                locked = User.objects.select_for_update().get(pk=player.pk)
                future = executor.submit(attempt)
                self.assertTrue(started.wait(timeout=5))
                locked.is_baned = True
                locked.save(update_fields=['is_baned'])
            self.assertEqual(future.result(timeout=10), 'player_banned')
        player.refresh_from_db()
        self.assertTrue(player.is_baned)
        self.assertEqual(player.tg_username, 'original_name')
