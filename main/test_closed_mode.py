"""Regression checks using synthetic identities and mocked Telegram transport."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from .models import Currency, Ofice, Traders, User, Transaction
from .test_auth import signed_init_data


@override_settings(CLOSED_TEST_MODE=True, TELEGRAM_TESTER_IDS=frozenset({900000001}))
class ClosedLoginTests(TransactionTestCase):
    def setUp(self):
        coin = Currency.objects.create(name='coin')
        Ofice.objects.create(lvl=1, comfort=0, safe_capacity=100, price=0, currency=coin)
        Traders.objects.create(lvl=1, earn_for_day=10, price=10, currency=coin)

    def login(self, user_id=900000001):
        return self.client.post('/api/create_session/', HTTP_AUTHORIZATION=signed_init_data(
            user={'id': user_id, 'first_name': 'Synthetic'}))

    def test_allowed_tester_can_login_and_read(self):
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.client.get('/api/info_person/').status_code, 200)

    def test_valid_signature_from_other_user_creates_nothing(self):
        self.assertEqual(self.login(900000002).status_code, 403)
        self.assertFalse(User.objects.exists())
        self.assertNotIn('telegram_verified', self.client.session)

    @override_settings(TELEGRAM_TESTER_IDS=())
    def test_empty_allowlist_denies_everyone(self):
        self.assertEqual(self.login().status_code, 403)
        self.assertFalse(User.objects.exists())

    def test_removing_tester_revokes_existing_session(self):
        self.assertEqual(self.login().status_code, 200)
        with override_settings(TELEGRAM_TESTER_IDS=()):
            self.assertEqual(self.client.get('/api/info_person/').status_code, 403)
        self.assertEqual(self.client.get('/api/info_person/').status_code, 401)

    def test_denied_login_clears_previous_session(self):
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.login(900000002).status_code, 403)
        self.assertEqual(self.client.get('/api/info_person/').status_code, 401)

    def test_wallet_cannot_be_changed_with_valid_session_and_csrf(self):
        login = self.login()
        before = User.objects.get().wallet_address
        response = self.client.post('/api/apply_wallet/', {'wallet': 'synthetic-wallet'},
                                    HTTP_X_CSRFTOKEN=login.json()['csrf_token'])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(User.objects.get().wallet_address, before)
        self.assertFalse(Transaction.objects.exists())

    def test_missing_starting_data_does_not_create_partial_player(self):
        Traders.objects.all().delete()
        self.assertEqual(self.login().status_code, 503)
        self.assertFalse(User.objects.exists())
        coin = Currency.objects.get()
        Traders.objects.create(lvl=1, earn_for_day=10, price=10, currency=coin)
        Ofice.objects.all().delete()
        self.assertEqual(self.login().status_code, 503)
        self.assertFalse(User.objects.exists())


@override_settings(CLOSED_TEST_MODE=True, TELEGRAM_TESTER_IDS=frozenset({900000001}),
                   TELEGRAM_TEST_BOT_ID=123456789)
class ClosedBotTests(SimpleTestCase):
    async def test_invoice_is_blocked_before_telegram_session(self):
        import telegram
        with patch.object(telegram, 'AiohttpSession') as transport:
            with self.assertRaises(PermissionDenied):
                await telegram.create_invoice_link(1, 1)
            transport.assert_not_called()

    async def test_precheckout_is_rejected(self):
        import telegram
        query = SimpleNamespace(answer=AsyncMock())
        await telegram.pre_checkout_handler(query)
        self.assertFalse(query.answer.call_args.kwargs['ok'])

    async def test_successful_payment_does_not_touch_database(self):
        import telegram
        # SimpleTestCase fails any DB query; no message content should be read.
        with self.assertLogs(level='ERROR'):
            await telegram.successful_payment(SimpleNamespace())

    async def test_refunds_and_referral_rewards_are_blocked(self):
        import telegram
        bot = SimpleNamespace(refund_star_payment=AsyncMock())
        await telegram.commandrefund_handler(SimpleNamespace(), bot, SimpleNamespace())
        bot.refund_star_payment.assert_not_called()
        with self.assertRaises(PermissionDenied):
            await telegram.distribute_rewards(1, 1)

    def test_season_prizes_are_blocked_before_database_access(self):
        from .tasks import finish_season
        with self.assertRaises(PermissionDenied):
            finish_season.run(1)

    async def test_start_from_other_user_has_no_reply(self):
        import telegram
        message = SimpleNamespace(from_user=SimpleNamespace(id=900000002), answer=AsyncMock())
        await telegram.handle_start(message)
        message.answer.assert_not_called()

    async def test_existing_webhook_is_not_deleted(self):
        import telegram
        with patch.object(telegram.bot, 'get_me', AsyncMock(return_value=SimpleNamespace(id=123456789))), \
             patch.object(telegram.bot, 'get_webhook_info', AsyncMock(return_value=SimpleNamespace(url='https://example.invalid'))), \
             patch.object(telegram.bot, 'delete_webhook', AsyncMock()) as delete, \
             patch.object(telegram.dp, 'start_polling', AsyncMock()) as poll:
            with self.assertRaises(RuntimeError):
                await telegram.main()
            delete.assert_not_called()
            poll.assert_not_called()

    async def test_wrong_bot_cannot_start_polling(self):
        import telegram
        with patch.object(telegram.bot, 'get_me', AsyncMock(return_value=SimpleNamespace(id=987654321))), \
             patch.object(telegram.bot, 'get_webhook_info', AsyncMock()) as webhook, \
             patch.object(telegram.dp, 'start_polling', AsyncMock()) as poll:
            with self.assertRaises(RuntimeError):
                await telegram.main()
            webhook.assert_not_called()
            poll.assert_not_called()

    @override_settings(ROOT_URLCONF='mysite.urls_staging')
    def test_staging_exposes_no_admin_or_swagger(self):
        self.assertEqual(self.client.get('/admin/').status_code, 404)
        self.assertEqual(self.client.get('/dev/swagger/').status_code, 404)
        self.assertEqual(self.client.get('/healthz/').status_code, 200)
