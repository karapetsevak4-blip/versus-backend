from decimal import Decimal
from io import StringIO
from django.test import TransactionTestCase, override_settings
from django.core.management import call_command
from django.core.management.base import CommandError
from .models import Traders, Ofice, UserBalance, UserTraders, Season
from .test_auth import signed_init_data


@override_settings(CLOSED_TEST_MODE=True, TELEGRAM_TESTER_IDS=(900000001,), FUNDED_TESTER_ID=900000001)
class CatalogTests(TransactionTestCase):
    def seed(self):
        call_command('seed_closed_test', stdout=StringIO())

    def login(self):
        result = self.client.post('/api/create_session/', HTTP_AUTHORIZATION=signed_init_data())
        self.assertEqual(result.status_code, 200)
        self.csrf = result.json()['csrf_token']

    def post(self, url, **data):
        return self.client.post(url, data, content_type='application/json', HTTP_X_CSRFTOKEN=self.csrf)

    def test_catalog_idempotence_and_exact_l2_purchase(self):
        self.seed(); self.seed()
        self.assertEqual((Traders.objects.count(), Ofice.objects.count(), Season.objects.count()), (5,5,1))
        l2 = Traders.objects.get(lvl=2)
        self.assertEqual(l2.price, Decimal('7.50'))
        self.login()
        result = self.post('/api/buy_something/', model='trader', id_products=l2.id, count=3)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(UserBalance.objects.get().token_money, Decimal('977.50'))
        self.assertEqual(self.client.get('/api/main_page/').status_code, 200)
        shop = self.client.get('/api/get_shop/').json()
        self.assertEqual(next(t['price'] for t in shop['traders'] if t['lvl']==2), 7.5)
        self.seed()
        self.assertEqual(UserBalance.objects.get().token_money, Decimal('977.50'))

    def test_tower_has_unlimited_placement_and_dynamic_safe(self):
        self.seed(); self.login()
        l1 = Traders.objects.get(lvl=1)
        self.assertEqual(self.post('/api/buy_something/', model='trader', id_products=l1.id, count=4).status_code, 200)
        tower = Ofice.objects.get(lvl=5)
        self.assertEqual(self.post('/api/buy_something/', model='ofice', id_products=tower.id).status_code, 200)
        balance = UserBalance.objects.get()
        for trader in balance.list_of_my_traders.exclude(pk__in=balance.my_ofice.traders.values('pk')):
            self.assertEqual(self.post('/api/apply_traders_in_ofice/', first_user_id_trader=trader.id).status_code, 200)
        main = self.client.get('/api/main_page/').json()
        office = main['user_balance']['my_ofice']['ofice']
        self.assertEqual(office['count_of_traders'], -1)
        self.assertEqual(office['safe_capacity'], 3650)
        details = self.client.get('/api/my_ofice/').json()
        self.assertEqual((details['all'], details['empty'], details['occupied']), (-1,-1,5))

    def test_seed_refuses_to_overwrite_changed_catalog(self):
        self.seed()
        Traders.objects.filter(lvl=2).update(price=9)
        with self.assertRaises(CommandError): self.seed()
        self.assertEqual(Traders.objects.get(lvl=2).price, 9)

    @override_settings(CLOSED_TEST_MODE=False)
    def test_seed_cannot_run_outside_closed_mode(self):
        with self.assertRaises(CommandError): self.seed()
        self.assertFalse(Traders.objects.exists())
