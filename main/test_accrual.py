from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from fractions import Fraction
from unittest.mock import patch

from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from . import gameplay
from .models import (ClaimUserHistory, Currency, Ofice, PurchaseReceipt, Season,
                     Team, TeamStats, Traders, Transaction, User, UserBalance,
                     UserOfice, UserStatistics, UserTraders)
from .tasks import calculate_personal_money
from .test_auth import signed_init_data


class ExactAccrualMathTests(SimpleTestCase):
    def test_split_intervals_preserve_exact_fraction(self):
        rate = Fraction('36.75')
        for slices in (1, 24, 1440):
            bank, remainder = 0, Fraction(0)
            for _ in range(slices):
                bank, remainder, _ = gameplay.calculate_accrual(
                    bank, remainder, rate, gameplay.MICROSECONDS_PER_DAY // slices, 1000)
            self.assertEqual((bank, remainder), (36, Fraction(3, 4)))

    def test_exact_and_overflow_capacity(self):
        for bank in (200, 215, 220):
            result = gameplay.calculate_accrual(bank, Fraction(0), Fraction(20),
                                                gameplay.MICROSECONDS_PER_DAY, 220)
            self.assertEqual(result, (220, Fraction(0), 220 - bank))

    def test_invalid_remainder_is_rejected(self):
        for remainder in (Fraction(-1, 2), Fraction(1)):
            with self.assertRaises(gameplay.GameplayError):
                gameplay.calculate_accrual(0, remainder, Fraction(20), 1, 220)

    def test_microsecond_boundary_never_rounds_a_coin_up(self):
        bank, remainder, _ = gameplay.calculate_accrual(0, Fraction(0), Fraction(20),
                                                       4_319_999_999, 220)
        self.assertEqual(bank, 0)
        self.assertEqual(gameplay.calculate_accrual(bank, remainder, Fraction(20), 1, 220),
                         (1, Fraction(0), 1))


@override_settings(USE_TZ=True, TIME_ZONE='UTC')
class AccrualFixture(TransactionTestCase):
    def setUp(self):
        self.at = datetime(2026, 9, 1, tzinfo=dt_timezone.utc)
        self.currency = Currency.objects.create(name='stars')
        self.basic = Ofice.objects.create(lvl=1, comfort=0, safe_capacity=220,
                                         price=0, currency=self.currency, count_of_traders=3)
        self.trader = Traders.objects.create(lvl=1, earn_for_day=20, price=5,
                                             currency=self.currency)
        self.team = Team.objects.create(name='Bulls')
        self.other_team = Team.objects.create(name='Bears')
        self.season = Season.objects.create(first_team=self.team, second_team=self.other_team,
                                           start_time=self.at, finish_time=self.at + timedelta(days=60), active=True)
        self.user = User.objects.create(tg_id=900000001)
        self.office = UserOfice.objects.create(user=self.user, ofice=self.basic)
        self.seated = UserTraders.objects.create(user=self.user, trader=self.trader)
        self.office.traders.add(self.seated)
        self.balance = UserBalance.objects.create(user=self.user, team=self.team, my_ofice=self.office,
                                                  token_money=1000, accrual_updated_at=self.at)
        self.balance.list_of_my_traders.add(self.seated)
        UserStatistics.objects.create(user=self.user)

    def remainder(self):
        self.balance.refresh_from_db()
        return Fraction(int(self.balance.accrual_remainder_numerator),
                        int(self.balance.accrual_remainder_denominator))


class AccrualIntegrationTests(AccrualFixture):
    def test_http_reads_claim_and_purchase_retry(self):
        self.assertEqual(self.client.post('/api/create_session/',
                                         HTTP_AUTHORIZATION=signed_init_data()).status_code, 200)
        at = self.at + timedelta(days=1)
        with patch('main.gameplay.timezone.now', return_value=at):
            main = self.client.get('/api/main_page/')
            self.assertEqual(main.status_code, 200)
            self.assertEqual(main.json()['user_balance']['my_bank'], 20)
            self.assertEqual(self.client.get('/api/my_ofice/').json()['productivity_per_day'], 20)
            claim = self.client.post('/api/claim_bank/')
            self.assertEqual((claim.status_code, claim.json()['claimed']), (200, 20))
            self.assertEqual(self.client.post('/api/claim_bank/').status_code, 404)
            payload = {'model': 'trader', 'id_products': self.trader.pk, 'count': 2}
            for _ in range(2):
                self.assertEqual(self.client.post('/api/buy_something/', payload,
                                                  content_type='application/json',
                                                  HTTP_IDEMPOTENCY_KEY='http-retry-1').status_code, 200)
            refreshed = self.client.get('/api/main_page/').json()['user_balance']
            self.assertEqual((refreshed['game_coin'], refreshed['my_bank'], refreshed['token_money']),
                             (20, 0, 990))

    def test_repeated_team_selection_does_not_increment_counts(self):
        self.balance.team = None; self.balance.save()
        gameplay.choose_team(self.user.pk, self.team.pk, self.at)
        with self.assertRaises(gameplay.GameplayError):
            gameplay.choose_team(self.user.pk, self.team.pk, self.at)
        self.assertEqual((TeamStats.objects.get().total_players, TeamStats.objects.get().total_traders), (1, 1))

    def test_passive_elapsed_and_duplicate_or_backwards_timestamp(self):
        self.assertEqual(gameplay.settle(self.user.pk, self.at + timedelta(hours=12)), 10)
        self.assertEqual(gameplay.settle(self.user.pk, self.at + timedelta(hours=12)), 0)
        self.assertEqual(gameplay.settle(self.user.pk, self.at), 0)
        self.assertEqual(gameplay.settle(self.user.pk, self.at + timedelta(days=1)), 10)
        self.balance.refresh_from_db(); self.team.refresh_from_db()
        self.assertEqual((self.balance.my_bank, self.balance.earn_in_team_per_month,
                          self.balance.earn_in_team_per_weak, self.team.money_team), (20, 20, 20, 20))
        self.assertEqual(list(TeamStats.objects.order_by('snapshot_day')
                              .values_list('total_coins', flat=True)), [10, 20])

    def test_office_comfort_fraction_survives_repeated_settlement(self):
        self.trader.earn_for_day = 35; self.trader.save()
        self.basic.comfort = 0.05; self.basic.safe_capacity = 650; self.basic.save()
        for hour in range(1, 97):
            gameplay.settle(self.user.pk, self.at + timedelta(hours=hour))
        self.assertEqual(self.remainder(), 0)
        self.assertEqual(self.balance.my_bank, 147)

    def test_full_safe_pause_claim_and_resume(self):
        self.balance.my_bank = 215; self.balance.save()
        gameplay.settle(self.user.pk, self.at + timedelta(days=1))
        self.balance.refresh_from_db(); self.team.refresh_from_db()
        self.assertEqual((self.balance.my_bank, self.team.money_team), (220, 5))
        amount = gameplay.claim(self.user.pk, self.at + timedelta(days=8))
        self.assertEqual(amount, 220)
        gameplay.settle(self.user.pk, self.at + timedelta(days=8, hours=12))
        self.balance.refresh_from_db()
        self.assertEqual((self.balance.my_bank, self.balance.game_coin), (10, 220))
        self.assertEqual(ClaimUserHistory.objects.count(), 1)

    def test_claim_transaction_rolls_back_if_history_fails(self):
        with patch('main.gameplay.ClaimUserHistory.objects.create', side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):
                gameplay.claim(self.user.pk, self.at + timedelta(days=1))
        self.balance.refresh_from_db(); self.team.refresh_from_db()
        self.assertEqual((self.balance.my_bank, self.balance.game_coin, self.team.money_team), (0, 0, 0))
        self.assertEqual(self.balance.accrual_updated_at, self.at)
        self.assertEqual(gameplay.claim(self.user.pk, self.at + timedelta(days=1)), 20)
        with self.assertRaises(gameplay.GameplayError):
            gameplay.claim(self.user.pk, self.at + timedelta(days=1))
        self.assertEqual(ClaimUserHistory.objects.count(), 1)

    def test_replacement_settles_old_rate(self):
        l5 = Traders.objects.create(lvl=5, earn_for_day=220, price=35, currency=self.currency)
        replacement = UserTraders.objects.create(user=self.user, trader=l5)
        gameplay.place_trader(self.user.pk, self.seated.pk, replacement.pk, self.at + timedelta(hours=12))
        gameplay.settle(self.user.pk, self.at + timedelta(days=1))
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.my_bank, 120)

    def test_upgrade_settles_old_comfort_and_preserves_exact_office(self):
        pro = Ofice.objects.create(lvl=2, comfort=.05, safe_capacity=650, price=15,
                                   currency=self.currency, count_of_traders=5)
        orphan = UserOfice.objects.create(user=self.user, ofice=self.basic)
        gameplay.purchase(self.user.pk, 'ofice', pro.pk, at=self.at + timedelta(hours=12))
        gameplay.settle(self.user.pk, self.at + timedelta(days=1))
        self.assertEqual(self.remainder(), Fraction(1, 2))
        self.assertEqual(self.balance.my_bank, 20)
        self.assertTrue(UserOfice.objects.filter(pk=orphan.pk).exists())
        self.assertFalse(UserOfice.objects.filter(pk=self.office.pk).exists())
        self.assertEqual(self.balance.my_ofice.traders.get().pk, self.seated.pk)

    def test_smaller_tower_safe_requires_claim_without_losing_money(self):
        self.basic.lvl = 4; self.basic.safe_capacity = 3500; self.basic.save()
        self.balance.my_bank = 3000; self.balance.save()
        tower = Ofice.objects.create(lvl=5, comfort=.2, safe_capacity=2500,
                                     safe_capacity_per_trader=230, price=250,
                                     currency=self.currency, count_of_traders=-1)
        with self.assertRaises(gameplay.GameplayError):
            gameplay.purchase(self.user.pk, 'ofice', tower.pk, at=self.at)
        self.balance.refresh_from_db()
        self.assertEqual((self.balance.my_bank, self.balance.token_money, self.balance.my_ofice_id),
                         (3000, 1000, self.office.pk))
        gameplay.claim(self.user.pk, self.at)
        gameplay.purchase(self.user.pk, 'ofice', tower.pk, at=self.at)
        self.balance.refresh_from_db()
        self.assertEqual((self.balance.game_coin, self.balance.token_money), (3000, 750))

    def test_empty_old_cursor_does_not_invent_backpay(self):
        self.balance.accrual_updated_at = None; self.balance.my_bank = 7; self.balance.save()
        self.assertEqual(gameplay.settle(self.user.pk, self.at + timedelta(days=3)), 0)
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.my_bank, 7)

    def test_corrupt_fraction_is_rejected_without_changing_balances(self):
        self.balance.accrual_remainder_denominator = '0'; self.balance.save()
        with self.assertRaises(gameplay.GameplayError):
            gameplay.settle(self.user.pk, self.at + timedelta(days=1))
        self.balance.refresh_from_db(); self.team.refresh_from_db()
        self.assertEqual((self.balance.my_bank, self.team.money_team), (0, 0))

    def test_no_production_before_team_choice_or_outside_season(self):
        self.balance.team = None; self.balance.save()
        gameplay.settle(self.user.pk, self.at + timedelta(days=1))
        gameplay.choose_team(self.user.pk, self.team.pk, self.at + timedelta(days=2))
        gameplay.settle(self.user.pk, self.at + timedelta(days=2, hours=12))
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.my_bank, 10)
        self.season.finish_time = self.at + timedelta(days=3); self.season.save()
        gameplay.settle(self.user.pk, self.at + timedelta(days=9))
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.my_bank, 20)

    def test_future_season_does_not_produce(self):
        self.season.start_time = self.at + timedelta(days=2); self.season.save()
        self.assertEqual(gameplay.settle(self.user.pk, self.at + timedelta(days=1)), 0)

    def test_worker_and_api_share_exact_cursor(self):
        at = self.at + timedelta(days=1)
        with patch('main.tasks.timezone.now', return_value=at):
            self.assertEqual(calculate_personal_money(), 20)
            self.assertEqual(calculate_personal_money(), 0)
        self.assertEqual(gameplay.main_snapshot(self.user.pk, at)['user_balance']['my_bank'], 20)
        self.team.refresh_from_db()
        self.assertEqual(self.team.money_team, 20)

    def test_configured_boost_applies_only_to_completed_purchase(self):
        self.team.boost_team = 1.5; self.team.save()
        self.assertEqual(gameplay.office_snapshot(self.user.pk, self.at)['productivity_per_day'], 20)
        Transaction.objects.create(user=self.user, price=1, completed=True)
        self.assertEqual(gameplay.office_snapshot(self.user.pk, self.at)['productivity_per_day'], 30)
        self.assertEqual(gameplay.settle(self.user.pk, self.at + timedelta(days=1)), 30)

    def test_purchase_key_replays_result_but_rejects_changed_request(self):
        for _ in range(2):
            gameplay.purchase(self.user.pk, 'trader', self.trader.pk, 2, 'synthetic-order-1', self.at)
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.token_money, Decimal('990'))
        self.assertEqual(UserTraders.objects.filter(user=self.user).count(), 3)
        self.assertEqual(PurchaseReceipt.objects.count(), 1)
        with self.assertRaises(gameplay.GameplayError):
            gameplay.purchase(self.user.pk, 'trader', self.trader.pk, 3, 'synthetic-order-1', self.at)
        gameplay.purchase(self.user.pk, 'trader', self.trader.pk, at=self.at)
        gameplay.purchase(self.user.pk, 'trader', self.trader.pk, at=self.at)
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.token_money, Decimal('980'))

    def test_excessive_batch_and_fractional_coin_price_cannot_debit(self):
        with self.assertRaises(gameplay.GameplayError):
            gameplay.purchase(self.user.pk, 'trader', self.trader.pk, 2**63 - 1)
        coin = Currency.objects.create(name='coin')
        self.trader.currency = coin; self.trader.price = Decimal('7.5'); self.trader.save()
        self.balance.game_coin = 10; self.balance.save()
        with self.assertRaises(gameplay.GameplayError):
            gameplay.purchase(self.user.pk, 'trader', self.trader.pk, at=self.at)
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.game_coin, 10)


class AccrualMigrationTests(TransactionTestCase):
    def test_existing_bank_is_preserved_without_retroactive_cursor(self):
        old = [('main', '0025_test_catalog_precision')]
        new = [('main', '0026_exact_accrual_and_purchase_receipts')]
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        executor = MigrationExecutor(connection)
        executor.migrate(old)
        try:
            apps = executor.loader.project_state(old).apps
            user = apps.get_model('main', 'User').objects.create(tg_id=900000099)
            balance = apps.get_model('main', 'UserBalance').objects.create(
                user=user, my_bank=17, token_money=Decimal('7.50'), game_coin=123)
            executor = MigrationExecutor(connection)
            executor.migrate(new)
            migrated = UserBalance.objects.get(pk=balance.pk)
            self.assertEqual((migrated.my_bank, migrated.token_money, migrated.game_coin),
                             (17, Decimal('7.50'), 123))
            self.assertIsNone(migrated.accrual_updated_at)
            self.assertEqual((migrated.accrual_remainder_numerator,
                              migrated.accrual_remainder_denominator), ('0', '1'))
        finally:
            MigrationExecutor(connection).migrate(latest)
