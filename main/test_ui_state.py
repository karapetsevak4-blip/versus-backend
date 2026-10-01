from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from . import gameplay, ui_state
from .models import TaskReward, User, UserTraders, OperationReceipt
from .test_accrual import AccrualFixture
from .test_auth import signed_init_data


class PresentationContractTests(AccrualFixture):
    def test_purchase_receipt_contains_owned_ids_and_replays_after_price_change(self):
        result = gameplay.purchase(self.user.pk, 'trader', self.trader.pk, 2, 'order-ui-1', self.at, expected_price=10)
        self.assertEqual(len(result['trader_ids']), 2)
        self.assertEqual(UserTraders.objects.filter(pk__in=result['trader_ids'], user=self.user).count(), 2)
        self.trader.price = 9; self.trader.save()
        self.assertEqual(result, gameplay.purchase(self.user.pk, 'trader', self.trader.pk, 2, 'order-ui-1', self.at, expected_price=10))
        with self.assertRaises(gameplay.GameplayError):
            gameplay.purchase(self.user.pk, 'trader', self.trader.pk, 1, 'order-ui-2', self.at, expected_price=5)
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.token_money, 990)

    def test_claim_retry_cannot_collect_new_accrual_and_creates_one_daily_reward(self):
        at = self.at + timedelta(days=1)
        callback = lambda: {'claimed': gameplay.claim(self.user.pk, at)}
        first = ui_state.operation(self.user.pk, 'claim-ui-1', 'claim', callback)
        gameplay.settle(self.user.pk, at + timedelta(days=1))
        self.assertEqual(first, ui_state.operation(self.user.pk, 'claim-ui-1', 'claim', callback))
        self.balance.refresh_from_db()
        self.assertEqual((self.balance.game_coin, self.balance.my_bank), (20, 20))
        reward = TaskReward.objects.get(user=self.user, kind='daily')
        self.assertEqual(reward.amount, Decimal('.50'))
        with patch('main.ui_state.timezone.now', return_value=at):
            ui_state.claim_task(self.user.pk, reward.pk)
            ui_state.claim_task(self.user.pk, reward.pk)
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.token_money, Decimal('1000.50'))
        self.assertEqual(OperationReceipt.objects.count(), 1)

    def test_office_reward_is_once_and_not_granted_for_inventory(self):
        bought = gameplay.purchase(self.user.pk, 'trader', self.trader.pk, 2, 'office-ui-1', self.at)
        self.assertEqual(ui_state.tasks(self.user.pk, self.at)['rows'], [])
        for trader_id in bought['trader_ids']:
            gameplay.place_trader(self.user.pk, trader_id, at=self.at)
        reward = TaskReward.objects.get(user=self.user, kind='office')
        self.assertEqual(reward.amount, 1)
        ui_state.tasks(self.user.pk, self.at + timedelta(days=80))
        self.assertEqual(TaskReward.objects.filter(kind='office').count(), 1)
        self.assertIsNone(reward.expires_at)

    def test_expired_rewards_and_foreign_rewards_cannot_be_claimed(self):
        reward = ui_state.ready_task(self.user.pk, 'daily', 'daily-test', self.at, self.season, '.5')
        with patch('main.ui_state.timezone.now', return_value=self.season.finish_time):
            with self.assertRaises(gameplay.GameplayError):
                ui_state.claim_task(self.user.pk, reward.pk)
        other = User.objects.create(tg_id=900000002)
        foreign = ui_state.ready_task(other.pk, 'office', 'foreign', self.at)
        with self.assertRaises(gameplay.GameplayError):
            ui_state.claim_task(self.user.pk, foreign.pk)
        self.balance.refresh_from_db(); self.assertEqual(self.balance.token_money, 1000)

    def test_invite_requires_season_registration_team_and_nonzero_collection(self):
        inviter = User.objects.create(tg_id=900000002)
        self.user.referrer = inviter; self.user.first_visit = self.at; self.user.save()
        ui_state.tasks(self.user.pk, self.at)
        self.assertFalse(TaskReward.objects.exists())
        for day in [1, 2]:
            gameplay.claim(self.user.pk, self.at + timedelta(days=day))
        self.assertEqual(TaskReward.objects.filter(user=inviter, kind='invite').count(), 1)

    def test_guide_round_trip_does_not_reset_balance_or_traders(self):
        ui_state.guide(self.user.pk, {'status': 'step', 'step': 3})
        self.assertEqual(ui_state.guide(self.user.pk)['step'], 3)
        ui_state.guide(self.user.pk, {'status': 'completed', 'step': 4})
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.token_money, 1000)
        self.assertEqual(self.office.traders.count(), 1)
        with self.assertRaises(gameplay.GameplayError):
            ui_state.guide(self.user.pk, {'status': 'step', 'step': True})

    def test_network_is_owned_and_does_not_mislabel_credits(self):
        child = User.objects.create(tg_id=900000002, referrer=self.user)
        User.objects.create(tg_id=900000003)
        data = ui_state.community(self.user.pk)
        self.assertEqual([row['id'] for row in data['layers']['1']], [child.pk])
        self.assertIsNone(data['volume']); self.assertIsNone(data['earned'])
        self.assertEqual(data['layers']['2'], [])

    def test_authenticated_contracts_and_history_isolation(self):
        self.assertIn(self.client.get('/api/tasks_ui/').status_code, [401, 403])
        self.assertEqual(self.client.post('/api/create_session/', HTTP_AUTHORIZATION=signed_init_data()).status_code, 200)
        for path in ['tasks_ui', 'player_ui', 'history_ui', 'community_ui']:
            self.assertEqual(self.client.get(f'/api/{path}/').status_code, 200)
        gameplay.purchase(self.user.pk, 'trader', self.trader.pk, 1, 'history-ui-1', self.at)
        row = ui_state.history(self.user.pk)['rows'][0]
        self.assertEqual((row['amount'], row['currency']), ('5.00', 'credits'))
        other = User.objects.create(tg_id=900000002)
        self.assertEqual(ui_state.history(other.pk)['rows'], [])

    def test_new_cookie_mutations_enforce_csrf(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        login = client.post('/api/create_session/', HTTP_AUTHORIZATION=signed_init_data())
        self.assertEqual(login.status_code, 200)
        reward = ui_state.ready_task(self.user.pk, 'office', 'csrf-office', self.at)
        for path, payload in [('tasks_ui', {'reward_id': reward.pk}), ('player_ui', {'status': 'step', 'step': 1})]:
            self.assertEqual(client.post(f'/api/{path}/', payload, content_type='application/json').status_code, 403)
            self.assertEqual(client.post(f'/api/{path}/', payload, content_type='application/json', HTTP_X_CSRFTOKEN=login.json()['csrf_token']).status_code, 200)

    def test_quote_currency_change_never_debits_another_balance(self):
        from .models import Currency
        self.trader.currency = Currency.objects.create(name='coin'); self.trader.save()
        self.balance.game_coin = 100; self.balance.save()
        with self.assertRaises(gameplay.GameplayError):
            gameplay.purchase(self.user.pk, 'trader', self.trader.pk, expected_price=5, expected_currency='credits')
        self.balance.refresh_from_db()
        self.assertEqual((self.balance.game_coin, self.balance.token_money), (100, 1000))

    def test_daily_rewards_follow_utc_boundary_without_retroactive_days(self):
        gameplay.claim(self.user.pk, self.at + timedelta(days=1, seconds=-1))
        gameplay.claim(self.user.pk, self.at + timedelta(days=1, seconds=1))
        keys = list(TaskReward.objects.filter(kind='daily').order_by('key').values_list('key', flat=True))
        self.assertEqual(keys, [f'daily:{self.season.pk}:2026-09-01', f'daily:{self.season.pk}:2026-09-02'])
        ui_state.tasks(self.user.pk, self.at + timedelta(days=5))
        self.assertEqual(TaskReward.objects.filter(kind='daily').count(), 2)

    def test_existing_player_referral_cannot_qualify_again_in_new_season(self):
        inviter = User.objects.create(tg_id=900000002)
        self.user.referrer = inviter; self.user.first_visit = self.at - timedelta(seconds=1); self.user.save()
        gameplay.claim(self.user.pk, self.at + timedelta(days=1))
        self.assertFalse(TaskReward.objects.filter(user=inviter, kind='invite').exists())
