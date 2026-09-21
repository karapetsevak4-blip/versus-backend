from django.test import TransactionTestCase, override_settings
from .models import Currency, Ofice, Traders, User, UserBalance, UserTraders, UserOfice
from .test_auth import signed_init_data


@override_settings(CLOSED_TEST_MODE=True, TELEGRAM_TESTER_IDS=(900000001, 900000002),
                   FUNDED_TESTER_ID=900000001)
class TestStarterBalance(TransactionTestCase):
    def setUp(self):
        self.coin = Currency.objects.create(name='coin')
        # Existing internal balance routing calls this currency stars; no API payment occurs.
        self.credit = Currency.objects.create(name='stars')
        self.basic = Ofice.objects.create(lvl=1, comfort=0, safe_capacity=220, price=0,
                                         currency=self.credit, count_of_traders=3)
        self.l1 = Traders.objects.create(lvl=1, earn_for_day=20, price=5, currency=self.credit)

    def login(self, user_id=900000001):
        response = self.client.post('/api/create_session/', HTTP_AUTHORIZATION=signed_init_data(
            user={'id': user_id, 'first_name': 'Synthetic'}))
        self.assertEqual(response.status_code, 200)
        self.csrf = response.json()['csrf_token']
        return UserBalance.objects.get(user__tg_id=user_id)

    def post(self, url, payload):
        return self.client.post(url, payload, content_type='application/json',
                                HTTP_X_CSRFTOKEN=self.csrf)

    def test_grant_once_and_spending_survives_relogin(self):
        balance = self.login()
        self.assertEqual((balance.game_coin, balance.token_money), (10000, 1000))
        response = self.post('/api/buy_something/', {'model': 'trader', 'id_products': self.l1.id, 'count': 2})
        self.assertEqual(response.status_code, 200)
        balance = self.login()
        self.assertEqual((balance.game_coin, balance.token_money), (10000, 990))
        self.assertEqual(balance.list_of_my_traders.count(), 3)

    def test_other_tester_has_no_grant(self):
        balance = self.login(900000002)
        self.assertEqual((balance.game_coin, balance.token_money), (0, 0))

    @override_settings(FUNDED_TESTER_IDS=(900000001, 900000002))
    def test_second_funded_tester_grant_once(self):
        balance = self.login(900000002)
        self.assertEqual((balance.game_coin, balance.token_money), (10000, 1000))
        self.assertEqual(self.post('/api/buy_something/', {
            'model': 'trader', 'id_products': self.l1.id, 'count': 2}).status_code, 200)
        balance = self.login(900000002)
        self.assertEqual((balance.game_coin, balance.token_money), (10000, 990))
        owner = self.login()
        self.assertEqual((owner.game_coin, owner.token_money), (10000, 1000))

    @override_settings(CLOSED_TEST_MODE=False)
    def test_normal_mode_has_no_grant(self):
        balance = self.login()
        self.assertEqual((balance.game_coin, balance.token_money), (0, 0))

    def test_coin_purchase_uses_coin_balance(self):
        balance = self.login()
        # Synthetic coin-priced product exercises the existing coin route, not the PDF catalog.
        trader = Traders.objects.create(lvl=9, earn_for_day=1, price=10, currency=self.coin)
        self.assertEqual(self.post('/api/buy_something/', {
            'model': 'trader', 'id_products': trader.id, 'count': 2}).status_code, 200)
        balance.refresh_from_db()
        self.assertEqual((balance.game_coin, balance.token_money), (9980, 1000))

    def test_place_purchased_trader_and_keep_it_after_office_upgrade(self):
        balance = self.login()
        self.assertEqual(self.post('/api/buy_something/', {
            'model': 'trader', 'id_products': self.l1.id}).status_code, 200)
        purchased = UserTraders.objects.filter(user=balance.user).order_by('-id').first()
        self.assertEqual(self.post('/api/apply_traders_in_ofice/', {
            'first_user_id_trader': purchased.id}).status_code, 200)
        old_id = balance.my_ofice_id
        pro = Ofice.objects.create(lvl=2, comfort=0.05, safe_capacity=650, price=15,
                                   currency=self.credit, count_of_traders=5)
        self.assertEqual(self.post('/api/buy_something/', {
            'model': 'ofice', 'id_products': pro.id}).status_code, 200)
        balance.refresh_from_db()
        self.assertEqual(balance.token_money, 980)
        self.assertEqual(balance.my_ofice.ofice_id, pro.id)
        self.assertEqual(balance.my_ofice.traders.count(), 2)
        self.assertFalse(UserOfice.objects.filter(id=old_id).exists())
        self.assertEqual(UserOfice.objects.filter(user=balance.user).count(), 1)
