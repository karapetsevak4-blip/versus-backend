"""Authenticated presentation contracts. No synthetic money or external payments."""
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .models import (User, UserBalance, PlayerGuide, TaskReward, OperationReceipt,
                     PurchaseReceipt, ClaimUserHistory, Season)
from .season_state import relevant_season, utc_day


def active_season(at):
    season = relevant_season(at)
    return season if season and season.active and season.start_time <= at < season.finish_time else None


def ready_task(user_id, kind, key, at, season=None, amount=1):
    return TaskReward.objects.get_or_create(user_id=user_id, key=key, defaults={
        'kind': kind, 'amount': Decimal(str(amount)), 'season': season,
        'ready_at': at, 'expires_at': season.finish_time if season else None})[0]


def on_placement(balance, at):
    if balance.my_ofice.traders.count() >= 3:
        ready_task(balance.user_id, 'office', 'office:first-three', at)


def on_claim(balance, at):
    season = active_season(at)
    if not season:
        return
    ready_task(balance.user_id, 'daily', f'daily:{season.pk}:{utc_day(at)}', at, season, '.5')
    user = balance.user
    if user.referrer_id and season.start_time <= user.first_visit < season.finish_time and balance.team_id:
        # Unique season key gives the inviter one award even with parallel referrals.
        ready_task(user.referrer_id, 'invite', f'invite:{season.pk}', at, season)


@transaction.atomic
def operation(user_id, key, signature, callback):
    from .gameplay import _lock_balance, _purchase_key, GameplayError
    _lock_balance(user_id)
    key = _purchase_key(key)
    if key:
        previous = OperationReceipt.objects.filter(user_id=user_id, key=key).first()
        if previous:
            if previous.signature != signature:
                raise GameplayError('Operation key belongs to another action', 409)
            return previous.result
    result = callback()
    if key:
        OperationReceipt.objects.create(user_id=user_id, key=key, signature=signature, result=result)
    return result


@transaction.atomic
def tasks(user_id, at=None):
    from .gameplay import _lock_balance
    at = at or timezone.now()
    balance = _lock_balance(user_id)
    on_placement(balance, at)
    season = active_season(at)
    rows = []
    for reward in TaskReward.objects.filter(user_id=user_id).select_related('season').order_by('-ready_at', '-pk'):
        expiry = reward.season.finish_time if reward.season else None
        rows.append({'id': reward.pk, 'kind': reward.kind, 'key': reward.key, 'amount': str(reward.amount),
                     'state': 'claimed' if reward.claimed_at else 'expired' if expiry and at >= expiry else 'ready',
                     'ready_at': reward.ready_at, 'expires_at': expiry, 'claimed_at': reward.claimed_at})
    return {'rows': rows, 'active_season': season.pk if season else None,
            'seated': balance.my_ofice.traders.count(), 'has_team': bool(balance.team_id)}


@transaction.atomic
def claim_task(user_id, reward_id):
    from .gameplay import _lock_balance, GameplayError
    balance = _lock_balance(user_id)
    reward = TaskReward.objects.select_for_update(of=('self',)).filter(pk=reward_id, user_id=user_id).select_related('season').first()
    if not reward:
        raise GameplayError('Reward not found', 404)
    if reward.claimed_at:
        return {'Info': 'Reward already recorded', 'amount': str(reward.amount)}
    at = timezone.now()
    if reward.season and at >= reward.season.finish_time:
        raise GameplayError('This reward expired with its season', 409)
    balance.token_money += reward.amount
    balance.save(update_fields=['token_money'])
    reward.claimed_at = at
    reward.save(update_fields=['claimed_at'])
    return {'Info': 'Reward recorded', 'amount': str(reward.amount)}


def history(user_id):
    rows = []
    for r in PurchaseReceipt.objects.filter(user_id=user_id).order_by('-created_at')[:200]:
        parts = r.signature.split(':')
        rows.append({'id': f'P{r.pk}', 'kind': 'purchase', 'at': r.created_at,
                     'label': r.result.get('item', 'Office upgrade' if parts[0] == 'ofice' else 'Trader purchase'),
                     'amount': r.result.get('amount'), 'currency': r.result.get('currency'), 'status': 'confirmed',
                     'quantity': int(parts[2]), 'detail': 'Delivered. Original order record.'})
    for r in ClaimUserHistory.objects.filter(user_id=user_id).order_by('-datatime')[:200]:
        rows.append({'id': f'C{r.pk}', 'kind': 'collection', 'at': r.datatime, 'label': 'Safe collection',
                     'amount': str(r.money), 'currency': 'Coins', 'status': 'confirmed', 'detail': 'No extra season contribution.'})
    for r in TaskReward.objects.filter(user_id=user_id, claimed_at__isnull=False).order_by('-claimed_at')[:200]:
        rows.append({'id': f'Q{r.pk}', 'kind': 'reward', 'at': r.claimed_at, 'label': r.kind.capitalize() + ' task reward',
                     'amount': str(r.amount), 'currency': 'credits', 'status': 'confirmed', 'detail': 'Non-withdrawable store credits.'})
    return {'rows': sorted(rows, key=lambda r: (r['at'], r['id']), reverse=True),
            'refunds_available': False, 'limit_per_type': 200}


def guide(user_id, data=None):
    from .gameplay import GameplayError
    obj, _ = PlayerGuide.objects.get_or_create(user_id=user_id)
    if data is not None:
        status, step = data.get('status'), data.get('step', 0)
        if status not in ['welcome', 'step', 'skipped', 'completed'] or type(step) is not int or not 0 <= step <= 4:
            raise GameplayError('Invalid guide progress')
        obj.status, obj.step, obj.version = status, step, 1
        obj.save(update_fields=['status', 'step', 'version', 'updated_at'])
    return {'status': obj.status, 'step': obj.step, 'version': obj.version}


def community(user_id):
    # The legacy endpoint mislabelled credit balances as Stars. Paid-volume and
    # reward ledgers are unavailable; return null, never invent zero earnings.
    current = [user_id]; layers = {}; visited = {user_id}
    for level in range(1, 6):
        members = list(User.objects.filter(referrer_id__in=current).exclude(pk__in=visited).order_by('pk'))
        layers[str(level)] = [{'id': u.pk, 'nickname': u.tg_username or u.tg_first_name or 'Player',
                              'invited': u.referrals.count(), 'volume': None, 'earned': None} for u in members]
        current = [u.pk for u in members]; visited.update(current)
    return {'layers': layers, 'rates': [10, 7, 4, 3, 1], 'period': 'all_time_invited',
            'financial_status': 'unavailable', 'pool_status': 'unavailable', 'volume': None, 'earned': None}


def presentation(user_id):
    at = timezone.now(); season = relevant_season(at)
    future = Season.objects.filter(start_time__gt=at).order_by('start_time').first()
    state = 'active' if active_season(at) else 'settling' if season and season.finish_time <= at else 'scheduled' if future else 'none'
    return {'guide': guide(user_id), 'season_status': state,
            'starts_at': future.start_time if state == 'scheduled' else season.start_time if season else None,
            'ends_at': season.finish_time if season else None, 'as_of': at,
            'payments_available': False, 'refunds_available': False,
            'switch_available': False, 'prize_balance': None, 'referral_balance': None}
