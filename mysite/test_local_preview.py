"""The browser fixture is a local-only route, never a production auth bypass."""
from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.urls import Resolver404, resolve

from main.telegram_auth import validate_init_data


@override_settings(ROOT_URLCONF='mysite.urls_local', LOCAL_GAME_MODE=True,
                   CLOSED_TEST_MODE=True)
class LocalPreviewBoundaryTests(SimpleTestCase):
    def test_fixture_signs_only_allowlisted_synthetic_players(self):
        for user_id in (910001, 910002):
            response = self.client.get('/api/local_fixture/', {'player': user_id})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            verified = validate_init_data(data['init_data'], settings.TELEGRAM_BOT_TOKEN,
                                           settings.TELEGRAM_INIT_DATA_MAX_AGE)
            self.assertEqual(verified['user']['id'], user_id)
            self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(self.client.get('/api/local_fixture/', {'player': 250427245}).status_code, 400)

    def test_fixture_requires_local_closed_profile_and_loopback(self):
        self.assertEqual(self.client.get('/api/local_fixture/', REMOTE_ADDR='198.51.100.8').status_code, 404)
        with override_settings(LOCAL_GAME_MODE=False):
            self.assertEqual(self.client.get('/api/local_fixture/').status_code, 404)
        with override_settings(CLOSED_TEST_MODE=False):
            self.assertEqual(self.client.get('/api/local_fixture/').status_code, 404)
        self.assertEqual(self.client.post('/api/local_fixture/').status_code, 405)

    def test_fixture_route_is_absent_from_deployed_urlconfs(self):
        for urlconf in ('mysite.urls', 'mysite.urls_staging'):
            with self.subTest(urlconf=urlconf), self.assertRaises(Resolver404):
                resolve('/api/local_fixture/', urlconf=urlconf)
