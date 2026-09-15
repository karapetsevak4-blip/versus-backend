"""Synthetic Telegram credentials; no Telegram requests or real user data."""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from django.conf import settings
from django.test import Client, TransactionTestCase, override_settings

from .models import Currency, Ofice, Traders, User, UserBalance


def signed_init_data(user=None, auth_date=None, token=None, **extra):
    payload = {
        'user': json.dumps(user if user is not None else {
            'id': 900000001, 'first_name': 'Offline & = + % Test',
        }, ensure_ascii=False, separators=(',', ':')),
        'auth_date': str(int(time.time()) if auth_date is None else auth_date),
        'query_id': 'offline-only',
        **extra,
    }
    data = '\n'.join(f'{key}={value}' for key, value in sorted(payload.items()))
    secret = hmac.digest(b'WebAppData', (token or settings.TELEGRAM_BOT_TOKEN).encode(), 'sha256')
    payload['hash'] = hmac.new(secret, data.encode(), hashlib.sha256).hexdigest()
    return urlencode(payload)


class TelegramLoginTests(TransactionTestCase):
    def setUp(self):
        coin = Currency.objects.create(name='coin')
        Ofice.objects.create(lvl=1, comfort=0, safe_capacity=100, price=0, currency=coin)
        Traders.objects.create(lvl=1, earn_for_day=10, price=10, currency=coin)

    def login(self, data):
        return self.client.post('/api/create_session/', HTTP_AUTHORIZATION=data)

    def test_valid_signature_and_repeated_login(self):
        data = signed_init_data(signature='optional-telegram-signature')
        self.assertEqual(self.login(data).status_code, 200)
        self.assertEqual(self.login(data).status_code, 200)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(UserBalance.objects.count(), 1)
        self.assertEqual(User.objects.get().tg_first_name, 'Offline & = + % Test')
        self.assertEqual(self.client.get('/api/info_person/').status_code, 200)

    def test_invalid_data_is_rejected_without_creating_users(self):
        invalid = [
            '', 'user=x', 'hash=' + '0' * 64,
            signed_init_data().replace('900000001', '900000002'),
            signed_init_data(token='987654321:ANOTHER_OFFLINE_TOKEN'),
            signed_init_data(auth_date=1),
            signed_init_data(auth_date=int(time.time()) + 3600),
            signed_init_data() + '&auth_date=1',
            signed_init_data(user={'id': True, 'first_name': 'Test'}),
            signed_init_data(user={'id': -1, 'first_name': 'Test'}),
            signed_init_data(user=[]),
        ]
        for data in invalid:
            with self.subTest(case=invalid.index(data)):
                self.assertIn(self.login(data).status_code, (400, 401))
        self.assertFalse(User.objects.exists())

    def test_failed_login_clears_previous_identity(self):
        self.assertEqual(self.login(signed_init_data()).status_code, 200)
        self.assertIn(self.login('hash=' + '0' * 64).status_code, (400, 401))
        self.assertEqual(self.client.get('/api/info_person/').status_code, 401)

    def test_legacy_unverified_session_is_rejected(self):
        session = self.client.session
        session['telegram_hash'] = '0' * 64
        session['telegram_user'] = {'id': 900000001}
        session.save()
        self.assertEqual(self.client.get('/api/info_person/').status_code, 401)

    def test_expired_verified_session_is_rejected(self):
        self.assertEqual(self.login(signed_init_data()).status_code, 200)
        session = self.client.session
        session['telegram_expires_at'] = int(time.time()) - 1
        session.save()
        self.assertEqual(self.client.get('/api/info_person/').status_code, 401)

    @override_settings(TELEGRAM_BOT_TOKEN='')
    def test_missing_bot_configuration_fails_closed(self):
        response = self.login(signed_init_data(token='123456789:OFFLINE_TEST_TOKEN_NOT_REAL'))
        self.assertEqual(response.status_code, 503)
        self.assertFalse(User.objects.exists())

    def test_login_does_not_accept_get(self):
        response = self.client.get('/api/create_session/', HTTP_AUTHORIZATION=signed_init_data())
        self.assertEqual(response.status_code, 405)
        self.assertFalse(User.objects.exists())

    def test_cookie_writes_require_csrf_and_trusted_origin(self):
        self.client = Client(enforce_csrf_checks=True)
        login = self.login(signed_init_data())
        self.assertEqual(login.status_code, 200)
        payload = {'nickname': 'OfflineNick'}
        url = '/api/change_nickname/'
        self.assertEqual(self.client.post(url, payload).status_code, 403)
        token = login.json()['csrf_token']
        self.assertEqual(self.client.post(url, payload, HTTP_X_CSRFTOKEN=token,
                                         HTTP_ORIGIN='https://untrusted.invalid').status_code, 403)
        self.assertEqual(self.client.post(url, payload, HTTP_X_CSRFTOKEN=token).status_code, 200)

    def test_login_rotates_session_id(self):
        self.assertEqual(self.login(signed_init_data()).status_code, 200)
        old_key = self.client.session.session_key
        self.assertEqual(self.login(signed_init_data()).status_code, 200)
        self.assertNotEqual(self.client.session.session_key, old_key)
