"""Real separate-connection races. SQLite cannot prove row-lock behavior."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless

from django.db import close_old_connections, connection, transaction, OperationalError

from . import gameplay
from .models import (ClaimUserHistory, Currency, PurchaseReceipt, Traders, User,
                     UserBalance, UserOfice, UserTraders)
from .test_accrual import AccrualFixture


@skipUnless(connection.vendor == 'postgresql', 'Requires actual PostgreSQL row locks')
class GameplayConcurrencyTests(AccrualFixture):
    def race(self, *operations):
        barrier = Barrier(len(operations))

        def run(operation):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                barrier.wait(timeout=10)
                try:
                    operation()
                    return 'ok'
                except gameplay.GameplayError:
                    return 'rejected'
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            futures = [executor.submit(run, operation) for operation in operations]
            return [future.result(timeout=15) for future in futures]

    def test_two_claims_transfer_once(self):
        at = self.at + timedelta(days=1)
        outcomes = self.race(*(lambda: gameplay.claim(self.user.pk, at) for _ in range(2)))
        self.assertCountEqual(outcomes, ['ok', 'rejected'])
        self.balance.refresh_from_db()
        self.assertEqual((self.balance.my_bank, self.balance.game_coin), (0, 20))
        self.assertEqual(list(ClaimUserHistory.objects.values_list('money', flat=True)), [20])

    def test_claim_settlement_and_purchase_preserve_wallet(self):
        coin = Currency.objects.create(name='coin')
        product = Traders.objects.create(lvl=2, earn_for_day=35, price=10, currency=coin)
        self.balance.game_coin = 10; self.balance.save()
        at = self.at + timedelta(days=1)
        outcomes = self.race(lambda: gameplay.claim(self.user.pk, at),
                             lambda: gameplay.settle(self.user.pk, at),
                             lambda: gameplay.purchase(self.user.pk, 'trader', product.pk, at=at))
        self.assertEqual(outcomes, ['ok', 'ok', 'ok'])
        self.balance.refresh_from_db(); self.team.refresh_from_db()
        self.assertEqual((self.balance.my_bank, self.balance.game_coin, self.team.money_team), (0, 20, 20))
        self.assertEqual(UserTraders.objects.filter(user=self.user).count(), 2)

    def test_two_players_do_not_lose_shared_team_contribution(self):
        other = User.objects.create(tg_id=900000002)
        office = UserOfice.objects.create(user=other, ofice=self.basic)
        office.traders.add(UserTraders.objects.create(user=other, trader=self.trader))
        UserBalance.objects.create(user=other, team=self.team, my_ofice=office,
                                   accrual_updated_at=self.at)
        at = self.at + timedelta(days=1)
        self.assertEqual(self.race(lambda: gameplay.settle(self.user.pk, at),
                                   lambda: gameplay.settle(other.pk, at)), ['ok', 'ok'])
        self.team.refresh_from_db()
        self.assertEqual(self.team.money_team, 40)
        self.assertEqual(sum(UserBalance.objects.values_list('earn_in_team_per_month', flat=True)), 40)

    def test_only_one_trader_can_take_last_seat(self):
        self.basic.count_of_traders = 2; self.basic.save()
        a, b = [UserTraders.objects.create(user=self.user, trader=self.trader) for _ in range(2)]
        outcomes = self.race(lambda: gameplay.place_trader(self.user.pk, a.pk, at=self.at),
                             lambda: gameplay.place_trader(self.user.pk, b.pk, at=self.at))
        self.assertCountEqual(outcomes, ['ok', 'rejected'])
        self.assertEqual(self.office.traders.count(), 2)

    def test_two_replacements_cannot_duplicate_one_seat(self):
        self.basic.count_of_traders = 1; self.basic.save()
        a, b = [UserTraders.objects.create(user=self.user, trader=self.trader) for _ in range(2)]
        outcomes = self.race(lambda: gameplay.place_trader(self.user.pk, self.seated.pk, a.pk, self.at),
                             lambda: gameplay.place_trader(self.user.pk, self.seated.pk, b.pk, self.at))
        self.assertCountEqual(outcomes, ['ok', 'rejected'])
        self.assertEqual(self.office.traders.count(), 1)

    def test_only_one_purchase_uses_last_funds(self):
        self.balance.token_money = 5; self.balance.save()
        outcomes = self.race(*(lambda: gameplay.purchase(self.user.pk, 'trader', self.trader.pk,
                                                          at=self.at) for _ in range(2)))
        self.assertCountEqual(outcomes, ['ok', 'rejected'])
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.token_money, 0)
        self.assertEqual(UserTraders.objects.filter(user=self.user).count(), 2)

    def test_parallel_retry_uses_one_purchase_receipt(self):
        outcomes = self.race(*(lambda: gameplay.purchase(self.user.pk, 'trader', self.trader.pk,
                                                          idempotency_key='parallel-order-1', at=self.at)
                               for _ in range(2)))
        self.assertEqual(outcomes, ['ok', 'ok'])
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.token_money, 995)
        self.assertEqual(UserTraders.objects.filter(user=self.user).count(), 2)
        self.assertEqual(PurchaseReceipt.objects.count(), 1)

    def test_purchase_actually_waits_for_existing_balance_lock(self):
        def attempt():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '100ms'")
                gameplay.purchase(self.user.pk, 'trader', self.trader.pk, at=self.at)
            finally:
                connection.close()

        with transaction.atomic():
            UserBalance.objects.select_for_update().get(pk=self.balance.pk)
            with ThreadPoolExecutor(max_workers=1) as executor:
                result = executor.submit(attempt)
                with self.assertRaises(OperationalError) as failure:
                    result.result(timeout=10)
                self.assertIn('lock timeout', str(failure.exception))
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.token_money, 1000)
        self.assertEqual(UserTraders.objects.filter(user=self.user).count(), 1)
