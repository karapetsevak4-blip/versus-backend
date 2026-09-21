"""Atomic player initialization and narrowly scoped profile mutations."""
from datetime import timedelta, timezone as datetime_timezone

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .input_validation import positive_integer
from .models import Ofice, Traders, User, UserBalance, UserOfice, UserStatistics, UserTraders
from .test_mode import initial_test_balance


class PlayerError(Exception):
    def __init__(self, message, status=400, code='invalid_player_request'):
        super().__init__(message)
        self.status = status
        self.code = code


def parse_referral_id(value):
    if value is None or value == '':
        return None
    try:
        return positive_integer(value)
    except ValueError as exc:
        raise PlayerError('Некорректный код приглашения') from exc


def _utc_date(at):
    if timezone.is_naive(at):
        at = timezone.make_aware(at, timezone.get_default_timezone())
    return at.astimezone(datetime_timezone.utc).date()


def _assert_not_banned(user):
    if user.is_baned:
        raise PlayerError('Доступ игрока ограничен', 403, 'player_banned')


def _complete_balance(user):
    balance = UserBalance.objects.select_related('my_ofice').filter(user=user).first()
    if (not balance or not balance.my_ofice or not balance.my_ofice.ofice_id
            or balance.my_ofice.user_id != user.pk
            or UserStatistics.objects.filter(user=user).count() != 1):
        # Never replay the starter grant to repair an old partial account.
        raise PlayerError('Состояние игрока неполное; требуется восстановление',
                          503, 'player_state_incomplete')
    return balance


def _grant_referral(user, balance, referrer, is_premium):
    referrer_balance = _complete_balance(referrer)
    # Preserve the existing non-financial signup rule in this integrity fix.
    # This does not approve it as the final RC06/RC08 reward policy.
    reward = 3500 if is_premium else 500
    UserStatistics.objects.filter(user=referrer).update(
        friends_are_inv=F('friends_are_inv') + 1,
        received_coins_from_ref=F('received_coins_from_ref') + reward)
    UserBalance.objects.filter(pk=balance.pk).update(
        game_coin=F('game_coin') + reward,
        earn_in_team_per_all_time=F('earn_in_team_per_all_time') + reward)
    UserBalance.objects.filter(pk=referrer_balance.pk).update(
        game_coin=F('game_coin') + reward,
        earn_in_team_per_all_time=F('earn_in_team_per_all_time') + reward,
        count_of_friends=F('count_of_friends') + 1)
    user.referrer = referrer
    user.save(update_fields=['referrer'])


@transaction.atomic
def register_player(telegram_user, referral_id=None, at=None):
    """Return one fully initialized player for a verified Telegram identity.

    unique(tg_id) arbitrates concurrent first inserts; Django get_or_create's
    savepoint retries the winning row after an integrity conflict. The outer
    transaction makes that row and the complete starter bundle visible together.
    Existing rows are locked while visit state is checked and updated.
    """
    referral_id = parse_referral_id(referral_id)  # Before any player write.
    at = at or timezone.now()
    today = _utc_date(at)
    tg_id = telegram_user['id']
    user, created = User.objects.select_for_update().get_or_create(
        tg_id=tg_id,
        defaults={
            'tg_username': telegram_user.get('username'),
            'tg_first_name': telegram_user.get('first_name'),
            'tg_last_name': telegram_user.get('last_name'),
            'photo_url': telegram_user.get('photo_url'),
            'first_visit': at, 'last_visit': today,
        })
    _assert_not_banned(user)
    if created:
        office_type = Ofice.objects.filter(lvl=1).first()
        trader_type = Traders.objects.filter(lvl=1).first()
        if office_type is None or trader_type is None:
            raise PlayerError('Starting game data is not configured', 503, 'starting_data_missing')
        trader = UserTraders.objects.create(user=user, trader=trader_type)
        office = UserOfice.objects.create(user=user, ofice=office_type)
        balance = UserBalance.objects.create(user=user, my_ofice=office,
                                             accrual_updated_at=at, **initial_test_balance(tg_id))
        office.traders.add(trader)
        balance.list_of_my_traders.add(trader)
        UserStatistics.objects.create(user=user)
        if referral_id is not None and referral_id != tg_id:
            referrer = User.objects.filter(tg_id=referral_id).first()
            if referrer is not None:
                _grant_referral(user, balance, referrer, telegram_user.get('is_premium', False))
    else:
        _complete_balance(user)
        if today > user.last_visit:
            user.can_take_daly_tasks = True
            user.count_of_visit += 1
            user.visit_without_pass = (1 if user.last_visit < today - timedelta(days=1)
                                       else user.visit_without_pass + 1)
            if user.visit_without_pass >= 8:
                user.visit_without_pass = 1
            user.last_visit = today
            user.save(update_fields=['can_take_daly_tasks', 'count_of_visit',
                                     'visit_without_pass', 'last_visit'])
    return user


@transaction.atomic
def change_nickname(user_id, nickname):
    if not isinstance(nickname, str) or not nickname.strip():
        raise PlayerError('Никнейм не передан')
    user = User.objects.select_for_update().get(pk=user_id)
    _assert_not_banned(user)
    if User.objects.filter(tg_username__iexact=nickname).exclude(pk=user_id).exists():
        raise PlayerError('Данное имя уже занято', 409)
    user.tg_username = nickname
    user.save(update_fields=['tg_username'])


@transaction.atomic
def change_wallet(user_id, wallet):
    if not isinstance(wallet, str) or not wallet:
        raise PlayerError('Not wallet')
    user = User.objects.select_for_update().get(pk=user_id)
    _assert_not_banned(user)
    user.wallet_address = None if wallet == 'None' else wallet
    user.save(update_fields=['wallet_address'])
