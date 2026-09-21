"""Server-authoritative office operations.

All mutations take the player's balance lock before inspecting money or seats.
The fractional coin is stored as an exact rational, not a rounded per-tick rate.
This module does not define season payouts, referral rewards or boost policy.
"""
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import re

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from .models import (ClaimUserHistory, Ofice, PurchaseReceipt, Season, Team,
                     TeamStats, Traders, Transaction, UserBalance, UserOfice,
                     UserTraders)

MICROSECONDS_PER_DAY = 86_400_000_000
MAX_PURCHASE_BATCH = 1000  # Resource bound per request, not an ownership limit.


class GameplayError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _fraction(value):
    try:
        return Fraction(Decimal(str(value)))
    except (ValueError, OverflowError, InvalidOperation) as exc:
        raise GameplayError('Некорректное значение каталога', 409) from exc


def _remainder(balance):
    numerator, denominator = (balance.accrual_remainder_numerator,
                              balance.accrual_remainder_denominator)
    if not all(isinstance(value, str) and re.fullmatch(r'[0-9]{1,120}', value)
               for value in (numerator, denominator)) or int(denominator) == 0:
        raise GameplayError('Некорректный остаток накопления', 409)
    value = Fraction(int(numerator), int(denominator))
    if not 0 <= value < 1:
        raise GameplayError('Некорректный остаток накопления', 409)
    return value


def _elapsed_us(start, end):
    elapsed = end - start
    return ((elapsed.days * 86400 + elapsed.seconds) * 1_000_000
            + elapsed.microseconds)


def calculate_accrual(bank, remainder, daily_rate, elapsed_us, capacity):
    """Return (new bank, exact remainder, accepted whole coins).

    Previously invalid overflow is preserved for collection, never silently
    deleted. No new overflow is created and full-safe time earns no backpay.
    """
    if bank < 0 or capacity < 0 or daily_rate < 0 or not 0 <= remainder < 1:
        raise GameplayError('Некорректное состояние накопления', 409)
    if bank >= capacity:
        return bank, Fraction(0), 0
    if elapsed_us <= 0:
        return bank, remainder, 0
    produced = remainder + daily_rate * elapsed_us / MICROSECONDS_PER_DAY
    whole = produced.numerator // produced.denominator
    credited = min(whole, capacity - bank)
    new_bank = bank + credited
    return (new_bank, Fraction(0) if new_bank >= capacity else produced - whole,
            credited)


def _lock_balance(user_id):
    # Do not combine this lock with nullable select_related outer joins (PG).
    try:
        return UserBalance.objects.select_for_update().get(user_id=user_id)
    except UserBalance.DoesNotExist as exc:
        raise GameplayError('Баланс игрока не найден', 404) from exc


def _office(balance):
    office = (UserOfice.objects.select_related('ofice')
              .prefetch_related('traders__trader').filter(
                  pk=balance.my_ofice_id, user_id=balance.user_id).first())
    if not office or not office.ofice:
        raise GameplayError('У вас нет действующего офиса', 409)
    return office


def daily_production(balance, office):
    traders = list(office.traders.all())
    rate = sum((_fraction(t.trader.earn_for_day) for t in traders if t.trader),
               Fraction(0)) * (1 + _fraction(office.ofice.comfort))
    if balance.team_id and Transaction.objects.filter(
            user_id=balance.user_id, completed=True).exists():
        boost = Team.objects.get(pk=balance.team_id).boost_team
        if boost > 1:
            rate *= _fraction(boost)
    if rate < 0:
        raise GameplayError('Некорректная производительность каталога', 409)
    return rate


def _settle_locked(balance, at):
    if balance.accrual_updated_at and at <= balance.accrual_updated_at:
        return 0
    office = _office(balance)
    start = balance.accrual_updated_at
    balance.accrual_updated_at = at
    credited = 0
    # Existing balances have no reliable last calculation time. Initialize the
    # cursor without inventing retroactive production, retaining their bank.
    season = (Season.objects.filter(active=True, start_time__lte=at)
              .filter(Q(first_team_id=balance.team_id) | Q(second_team_id=balance.team_id))
              .order_by('-start_time', '-pk').first()) if balance.team_id else None
    if start and season:
        end = min(at, season.finish_time)
        start = max(start, season.start_time)
        remainder = _remainder(balance)
        capacity = office.ofice.capacity_for(len(list(office.traders.all())))
        bank, remainder, credited = calculate_accrual(
            balance.my_bank, remainder, daily_production(balance, office),
            max(0, _elapsed_us(start, end)), capacity)
        if max(len(str(remainder.numerator)), len(str(remainder.denominator))) > 120:
            raise GameplayError('Точность каталога превышает поддерживаемую', 409)
        balance.my_bank = bank
        balance.accrual_remainder_numerator = str(remainder.numerator)
        balance.accrual_remainder_denominator = str(remainder.denominator)
        if credited:
            balance.earn_in_team_per_month += credited
            balance.earn_in_team_per_weak += credited
            # UPDATE locks the team until commit; no stale full-model saves.
            Team.objects.filter(pk=balance.team_id).update(
                money_team=F('money_team') + credited,
                money_for_day=F('money_for_day') + credited,
                money_for_weak=F('money_for_weak') + credited)
            stats = (TeamStats.objects.filter(team_id=balance.team_id, season=season)
                     .order_by('-date', '-pk').first())
            if stats:
                TeamStats.objects.filter(pk=stats.pk).update(
                    total_coins=F('total_coins') + credited)
            else:
                TeamStats.objects.create(
                    team_id=balance.team_id, season=season,
                    total_coins=Team.objects.get(pk=balance.team_id).money_team,
                    date=at)
    balance.save(update_fields=['my_bank', 'accrual_updated_at',
                                'accrual_remainder_numerator',
                                'accrual_remainder_denominator',
                                'earn_in_team_per_month', 'earn_in_team_per_weak'])
    return credited


@transaction.atomic
def settle(user_id, at=None):
    return _settle_locked(_lock_balance(user_id), at or timezone.now())


@transaction.atomic
def claim(user_id, at=None):
    balance = _lock_balance(user_id)
    if not balance.team_id:
        raise GameplayError('У вас нет команды', 404)
    at = at or timezone.now()
    _settle_locked(balance, at)
    amount = balance.my_bank
    if amount <= 0:
        raise GameplayError('У вас нет монет для сбора', 404)
    balance.game_coin += amount
    balance.earn_in_team_per_all_time += amount
    balance.my_bank = 0
    balance.save(update_fields=['game_coin', 'earn_in_team_per_all_time', 'my_bank'])
    ClaimUserHistory.objects.create(user_id=user_id, money=amount, datatime=at)
    return amount


@transaction.atomic
def place_trader(user_id, first_id, second_id=None, at=None):
    balance = _lock_balance(user_id)
    office = _office(balance)
    first = UserTraders.objects.filter(pk=first_id, user_id=user_id).first()
    if not first:
        raise GameplayError('Трейдер не найден у игрока', 404)
    seated = {t.pk for t in office.traders.all()}
    if second_id is not None:
        second = UserTraders.objects.filter(pk=second_id, user_id=user_id).first()
        if not second:
            raise GameplayError('Трейдер для замены не найден у игрока', 404)
        if first_id not in seated or second_id in seated:
            raise GameplayError('Invalid replacement position')
    elif first_id in seated or not office.ofice.has_space(len(seated)):
        raise GameplayError('Нет свободного места или трейдер уже в офисе', 404)
    _settle_locked(balance, at or timezone.now())
    if second_id is not None:
        office.traders.remove(first)
        office.traders.add(second)
    else:
        office.traders.add(first)


def _purchase_key(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{8,128}', value):
        raise GameplayError('Invalid Idempotency-Key')
    return value


@transaction.atomic
def purchase(user_id, model, product_id, count=1, idempotency_key=None, at=None):
    if model not in ('trader', 'ofice') or type(count) is not int or not 1 <= count <= MAX_PURCHASE_BATCH:
        raise GameplayError('Invalid product or quantity (maximum 1000 per request)')
    if model == 'ofice' and count != 1:
        raise GameplayError('Можно улучшить только один действующий офис')
    key = _purchase_key(idempotency_key)
    balance = _lock_balance(user_id)
    signature = f'{model}:{product_id}:{count}'
    if key:
        previous = PurchaseReceipt.objects.filter(user_id=user_id, key=key).first()
        if previous:
            if previous.signature != signature:
                raise GameplayError('Idempotency-Key уже использован для другой покупки', 409)
            return previous.result
    product = (Traders if model == 'trader' else Ofice).objects.select_related(
        'currency').filter(pk=product_id).first()
    if not product or not product.currency or product.price is None:
        raise GameplayError('Данный продукт не найден', 404)
    price = Decimal(str(product.price)) * count
    currency = product.currency.name.lower()
    field = {'stars': 'token_money', 'coin': 'game_coin'}.get(currency)
    if price < 0 or not field or (field == 'game_coin' and price != int(price)):
        raise GameplayError('Некорректная цена каталога', 409)
    if getattr(balance, field) < price:
        raise GameplayError('У вас недостаточно денег', 404)
    office = _office(balance)
    if model == 'ofice' and office.ofice.lvl >= product.lvl:
        raise GameplayError('Уровень вашего офиса больше или такой же', 404)
    _settle_locked(balance, at or timezone.now())
    if model == 'ofice':
        seated = list(office.traders.all())
        capacity = product.capacity_for(len(seated))
        if product.count_of_traders != -1 and (product.count_of_traders is None or len(seated) > product.count_of_traders):
            raise GameplayError('В новом офисе недостаточно мест', 409)
        if balance.my_bank > capacity or (balance.my_bank == capacity and
                                          int(balance.accrual_remainder_numerator)):
            raise GameplayError('Сначала соберите монеты: сейф нового офиса меньше накопления', 409)
        new_office = UserOfice.objects.create(user_id=user_id, ofice=product)
        new_office.traders.add(*seated)
        balance.my_ofice = new_office
    else:
        bought = UserTraders.objects.bulk_create([
            UserTraders(user_id=user_id, trader=product) for _ in range(count)])
        balance.list_of_my_traders.add(*bought)
    debit = price if field == 'token_money' else int(price)
    setattr(balance, field, getattr(balance, field) - debit)
    balance.save(update_fields=[field, 'my_ofice'])
    if model == 'ofice':
        office.delete()  # Exact replaced instance, inside the same transaction.
    result = {'Info': 'Офис удачно куплен' if model == 'ofice' else 'Трейдер удачно куплен'}
    if key:
        PurchaseReceipt.objects.create(user_id=user_id, key=key, signature=signature, result=result)
    return result


@transaction.atomic
def choose_team(user_id, team_id, at=None):
    balance = _lock_balance(user_id)
    if balance.team_id:
        raise GameplayError('Вы уже прошли онбординг', 404)
    at = at or timezone.now()
    season = (Season.objects.filter(active=True, start_time__lte=at, finish_time__gt=at)
              .filter(Q(first_team_id=team_id) | Q(second_team_id=team_id))
              .order_by('-start_time', '-pk').first())
    if not season:
        raise GameplayError('Команда не участвует в действующем сезоне', 409)
    Team.objects.select_for_update().get(pk=team_id)
    balance.team_id = team_id
    balance.accrual_updated_at = at  # No production before choosing a team.
    balance.save(update_fields=['team', 'accrual_updated_at'])
    stats = TeamStats.objects.filter(team_id=team_id, season=season).order_by('-date', '-pk').first()
    if stats is None:
        stats = TeamStats.objects.create(team_id=team_id, season=season, date=at)
    TeamStats.objects.filter(pk=stats.pk).update(
        total_players=F('total_players') + 1,
        total_traders=F('total_traders') + _office(balance).traders.count())


@transaction.atomic
def main_snapshot(user_id, at=None):
    from .Serializers.response_serializer import MainPageSerializer
    balance = _lock_balance(user_id)
    _settle_locked(balance, at or timezone.now())
    balance = (UserBalance.objects.select_related('user', 'team', 'my_ofice__ofice')
               .prefetch_related('my_ofice__traders__trader__currency',
                                 'list_of_my_traders__trader__currency').get(pk=balance.pk))
    season = Season.objects.select_related('first_team', 'second_team').order_by('-start_time', '-pk').first()
    return MainPageSerializer({'season': season, 'user': balance.user, 'user_balance': balance},
                              context={'my_traders': [t.pk for t in balance.my_ofice.traders.all()]}).data


@transaction.atomic
def office_snapshot(user_id, at=None):
    from .Serializers.response_serializer import MyOficeSerializer
    balance = _lock_balance(user_id)
    _settle_locked(balance, at or timezone.now())
    office = _office(balance)
    occupied = len(list(office.traders.all()))
    slots = office.ofice.count_of_traders
    return MyOficeSerializer({
        'productivity_per_day': float(daily_production(balance, office)),
        'history_claims': list(ClaimUserHistory.objects.filter(user_id=user_id).order_by('-id')),
        'all': slots, 'occupied': occupied, 'empty': -1 if slots == -1 else slots - occupied,
    }).data
