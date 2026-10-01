from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TransactionTestCase, override_settings

from . import registration
from .models import Currency, Ofice, Traders, User, UserBalance, UserOfice, UserStatistics, UserTraders
from .test_auth import signed_init_data


@override_settings(USE_TZ=True, TIME_ZONE='UTC')
class RegistrationFixture(TransactionTestCase):
    def setUp(self):
        self.at = datetime(2026, 9, 20, 12, tzinfo=datetime_timezone.utc)
        self.metadata = {'id': 900000001, 'first_name': 'Synthetic', 'username': 'original_name'}
        self.currency = Currency.objects.create(name='stars')
        self.office = Ofice.objects.create(lvl=1, comfort=0, safe_capacity=220, price=0,
                                           currency=self.currency, count_of_traders=3)
        self.trader = Traders.objects.create(lvl=1, earn_for_day=20, price=5, currency=self.currency)

    def login(self, referral=None, user=None):
        url = '/api/create_session/'
        if referral is not None:
            url += '?refer_id=' + str(referral)
        return self.client.post(url, HTTP_AUTHORIZATION=signed_init_data(user=user or self.metadata))


class RegistrationTests(RegistrationFixture):
    def test_invalid_referral_has_no_player_writes_or_authenticated_session(self):
        for referral in ('wrong', '1.5', '-1', '0', '9' * 30):
            with self.subTest(referral=referral):
                self.assertEqual(self.login(referral).status_code, 400)
                self.assertFalse(User.objects.exists())
                self.assertFalse(UserBalance.objects.exists())
                self.assertFalse(UserTraders.objects.exists())
                self.assertNotIn('telegram_verified', self.client.session)

    def test_failure_mid_registration_rolls_back_bundle_then_retry_succeeds(self):
        self.client = Client(raise_request_exception=False)
        with patch('main.registration.UserBalance.objects.create', side_effect=RuntimeError('injected failure')):
            with self.assertLogs('django.request', level='ERROR'):
                self.assertEqual(self.login().status_code, 500)
        for model in (User, UserBalance, UserOfice, UserTraders, UserStatistics):
            self.assertEqual(model.objects.count(), 0)
        self.assertNotIn('telegram_verified', self.client.session)
        self.assertEqual(self.login().status_code, 200)
        for model in (User, UserBalance, UserOfice, UserTraders, UserStatistics):
            self.assertEqual(model.objects.count(), 1)

    def test_referral_updates_are_atomic_and_original_inviter_is_preserved(self):
        inviter = registration.register_player({'id': 900000002}, at=self.at)
        original = registration._grant_referral

        def fail_after_rewards(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('injected after referral writes')

        with patch('main.registration._grant_referral', side_effect=fail_after_rewards):
            with self.assertRaises(RuntimeError):
                registration.register_player(self.metadata, inviter.tg_id, self.at)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(UserBalance.objects.get(user=inviter).game_coin, 0)
        self.assertEqual(UserStatistics.objects.get(user=inviter).friends_are_inv, 0)
        player = registration.register_player(self.metadata, inviter.tg_id, self.at)
        another = registration.register_player({'id': 900000003}, at=self.at)
        registration.register_player(self.metadata, another.tg_id, self.at)
        player.refresh_from_db()
        self.assertEqual(player.referrer_id, inviter.pk)
        self.assertEqual(UserBalance.objects.get(user=inviter).game_coin, 0)
        self.assertEqual(UserBalance.objects.get(user=player).game_coin, 0)
        self.assertEqual(UserBalance.objects.get(user=another).game_coin, 0)
        self.assertEqual(UserStatistics.objects.get(user=inviter).friends_are_inv, 1)

    def test_self_and_unknown_referrals_create_no_link_or_bonus(self):
        player = registration.register_player(self.metadata, self.metadata['id'], self.at)
        other = registration.register_player({'id': 900000002}, 999999999, self.at)
        for user in (player, other):
            self.assertIsNone(user.referrer_id)
            self.assertEqual(UserBalance.objects.get(user=user).game_coin, 0)

    def test_existing_incomplete_player_is_not_regranted_or_authenticated(self):
        player = registration.register_player(self.metadata, at=self.at)
        UserBalance.objects.filter(user=player).delete()
        response = self.login()
        self.assertEqual((response.status_code, response.json()['code']), (503, 'player_state_incomplete'))
        self.assertFalse(UserBalance.objects.exists())
        self.assertEqual((User.objects.count(), UserOfice.objects.count(), UserTraders.objects.count()), (1, 1, 1))
        self.assertNotIn('telegram_verified', self.client.session)

    def test_failed_player_login_revokes_previous_session(self):
        self.assertEqual(self.login().status_code, 200)
        UserBalance.objects.all().delete()
        self.assertEqual(self.login().status_code, 503)
        self.assertEqual(self.client.get('/api/info_person/').status_code, 401)

    def test_banned_player_cannot_relogin_or_modify_profile(self):
        player = registration.register_player(self.metadata, at=self.at)
        User.objects.filter(pk=player.pk).update(is_baned=True)
        self.assertEqual(self.login().status_code, 403)
        for operation in (lambda: registration.change_nickname(player.pk, 'new-name'),
                          lambda: registration.change_wallet(player.pk, 'new-wallet')):
            with self.assertRaises(registration.PlayerError):
                operation()
        player.refresh_from_db()
        self.assertTrue(player.is_baned)
        self.assertEqual(player.tg_username, 'original_name')
        self.assertIsNone(player.wallet_address)

    def test_profile_write_preserves_fields_changed_after_user_read(self):
        player = registration.register_player(self.metadata, at=self.at)
        original = registration._assert_not_banned

        def change_independent_fields(user):
            original(user)
            User.objects.filter(pk=user.pk).update(wallet_address='independent-wallet', is_baned=True)

        with patch('main.registration._assert_not_banned', side_effect=change_independent_fields):
            registration.change_nickname(player.pk, 'new-name')
        player.refresh_from_db()
        self.assertEqual(player.tg_username, 'new-name')
        self.assertEqual(player.wallet_address, 'independent-wallet')
        self.assertTrue(player.is_baned)

    def test_visit_day_is_utc_and_only_visit_fields_change(self):
        at = datetime(2026, 9, 21, 0, 30, tzinfo=datetime_timezone(timedelta(hours=3)))
        player = registration.register_player(self.metadata, at=at)
        self.assertEqual(player.last_visit.isoformat(), '2026-09-20')
        registration.change_nickname(player.pk, 'new-name')
        registration.change_wallet(player.pk, 'wallet')
        registration.register_player(self.metadata, at=at + timedelta(days=1))
        registration.register_player(self.metadata, at=at + timedelta(days=1))
        player.refresh_from_db()
        self.assertEqual((player.last_visit.isoformat(), player.count_of_visit, player.visit_without_pass),
                         ('2026-09-21', 2, 2))
        self.assertEqual((player.tg_username, player.wallet_address), ('new-name', 'wallet'))

    def test_database_rejects_duplicate_telegram_id(self):
        registration.register_player(self.metadata, at=self.at)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create(tg_id=self.metadata['id'])


class IdentityMigrationTests(TransactionTestCase):
    def test_duplicate_preflight_refuses_without_deleting_historical_records(self):
        old = [('main', '0026_exact_accrual_and_purchase_receipts')]
        new = [('main', '0027_unique_telegram_identity')]
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        executor = MigrationExecutor(connection)
        executor.migrate(old)
        duplicate = None
        try:
            apps = executor.loader.project_state(old).apps
            UserBefore = apps.get_model('main', 'User')
            BalanceBefore = apps.get_model('main', 'UserBalance')
            one = UserBefore.objects.create(tg_id=900000099)
            duplicate = UserBefore.objects.create(tg_id=900000099)
            BalanceBefore.objects.create(user=one, game_coin=10)
            BalanceBefore.objects.create(user=duplicate, game_coin=20)
            with self.assertRaisesRegex(RuntimeError, '1 duplicate tg_id group') as failure:
                MigrationExecutor(connection).migrate(new)
            self.assertNotIn('900000099', str(failure.exception))
            self.assertEqual(UserBefore.objects.filter(tg_id=900000099).count(), 2)
            self.assertEqual(list(BalanceBefore.objects.order_by('game_coin').values_list('game_coin', flat=True)), [10, 20])
            # Only repair this synthetic fixture so the test schema can advance.
            UserBefore.objects.filter(pk=duplicate.pk).update(tg_id=900000100)
            duplicate = None
            MigrationExecutor(connection).migrate(new)
        finally:
            if duplicate is not None:
                duplicate.tg_id = 900000100
                duplicate.save(update_fields=['tg_id'])
            MigrationExecutor(connection).migrate(latest)
