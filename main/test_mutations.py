from django.test import TransactionTestCase
from .models import Currency, Ofice, Traders, User, UserBalance, UserTraders
from .test_auth import signed_init_data


class MutationBoundaryTests(TransactionTestCase):
    def setUp(self):
        self.coin = Currency.objects.create(name='coin')
        self.office = Ofice.objects.create(lvl=1, comfort=0, safe_capacity=100,
                                           price=0, currency=self.coin, count_of_traders=3)
        self.trader = Traders.objects.create(lvl=1, earn_for_day=10, price=10, currency=self.coin)
        login = self.client.post('/api/create_session/', HTTP_AUTHORIZATION=signed_init_data())
        self.assertEqual(login.status_code, 200)
        self.user = User.objects.get(tg_id=900000001)
        self.balance = UserBalance.objects.get(user=self.user)
        self.balance.game_coin = 100
        self.balance.save()
        self.other = User.objects.create(tg_id=900000002)
        self.foreign_trader = UserTraders.objects.create(user=self.other, trader=self.trader)

    def test_negative_and_malformed_quantity_never_change_balance(self):
        for count in (-2, 0, True, 1.5, '1.5', 'abc', None, [], {}):
            with self.subTest(count=count):
                response = self.client.post('/api/buy_something/', {
                    'model': 'trader', 'id_products': self.trader.id, 'count': count,
                }, content_type='application/json')
                self.assertEqual(response.status_code, 400)
                self.balance.refresh_from_db()
                self.assertEqual(self.balance.game_coin, 100)
                self.assertEqual(UserTraders.objects.filter(user=self.user).count(), 1)

    def test_valid_purchase_is_unchanged(self):
        response = self.client.post('/api/buy_something/', {
            'model': 'trader', 'id_products': self.trader.id, 'count': 2,
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.game_coin, 80)
        self.assertEqual(self.balance.list_of_my_traders.count(), 3)

    def test_cannot_install_someone_elses_trader(self):
        response = self.client.post('/api/apply_traders_in_ofice/', {
            'first_user_id_trader': self.foreign_trader.id,
        }, content_type='application/json')
        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.balance.my_ofice.traders.filter(pk=self.foreign_trader.pk).exists())

    def test_cannot_replace_with_someone_elses_trader(self):
        original = self.balance.my_ofice.traders.get()
        response = self.client.post('/api/apply_traders_in_ofice/', {
            'first_user_id_trader': original.id,
            'second_user_id_trader': self.foreign_trader.id,
        }, content_type='application/json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(list(self.balance.my_ofice.traders.all()), [original])

    def test_cannot_replace_non_seated_trader_to_bypass_capacity(self):
        spare = UserTraders.objects.create(user=self.user, trader=self.trader)
        replacement = UserTraders.objects.create(user=self.user, trader=self.trader)
        self.office.count_of_traders = 1
        self.office.save()
        response = self.client.post('/api/apply_traders_in_ofice/', {
            'first_user_id_trader': spare.id, 'second_user_id_trader': replacement.id,
        }, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.balance.my_ofice.traders.count(), 1)
