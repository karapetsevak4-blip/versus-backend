"""Observed team state, not a payout ledger or reconstructed daily earnings.

Gameplay locks balance -> team. Snapshot writers lock team only and read
balances with ordinary MVCC queries: never acquire a balance lock after a team.
"""
from django.db import transaction
from django.utils import timezone

from .models import Team, TeamStats, UserBalance
from .season_state import relevant_season, utc_day


def team_metrics(team):
    from .gameplay import daily_production

    balances = list(UserBalance.objects.filter(team_id=team.pk)
                    .select_related('user', 'my_ofice__ofice')
                    .prefetch_related('my_ofice__traders__trader')
                    .order_by('-earn_in_team_per_month', 'pk'))
    productivity, traders = 0, 0
    for balance in balances:
        office = balance.my_ofice
        if not office or not office.ofice or office.user_id != balance.user_id:
            continue
        traders += len(list(office.traders.all()))
        productivity += daily_production(balance, office)
    return {
        'total_coins': team.money_team,
        'productivity_per_day': float(productivity),
        'total_players': len(balances),
        'total_traders': traders,
    }, balances


def _snapshot_locked(team, season, at, metrics):
    day = utc_day(at)
    rows = TeamStats.objects.filter(team=team, season=season)
    current = rows.filter(snapshot_day__gte=day).order_by('-snapshot_day').first()
    # A delayed settlement may commit AFTER a newer observation. Reflect its
    # now-committed totals in the latest observed day, never in a closed day.
    # No historical backfill or attribution of earnings to missed days occurs.
    if current:
        for field, value in metrics.items():
            setattr(current, field, value)
        current.date = max(current.date, at)
        current.save(update_fields=[*metrics, 'date'])
        return current
    return TeamStats.objects.create(team=team, season=season, snapshot_day=day,
                                    date=at, **metrics)


@transaction.atomic
def refresh_team_snapshot(team_id, season, at):
    if not team_id or not season or team_id not in (season.first_team_id, season.second_team_id):
        return None
    team = Team.objects.select_for_update().get(pk=team_id)
    metrics, _ = team_metrics(team)
    return _snapshot_locked(team, season, at, metrics)


def snapshot_current_teams(at=None):
    at = at or timezone.now()
    season = relevant_season(at)
    if not season or not season.active:
        return 0
    ids = sorted({pk for pk in (season.first_team_id, season.second_team_id) if pk})
    for team_id in ids:
        refresh_team_snapshot(team_id, season, at)
    return len(ids)


def _history(team, season):
    # Preserve all legacy rows in storage. For presentation choose one observed
    # value per UTC day, preferring the canonical snapshot over legacy entries.
    by_day = {}
    rows = TeamStats.objects.filter(team=team, season=season).order_by('date', 'pk')
    for row in rows:
        day = row.snapshot_day or utc_day(row.date)
        previous = by_day.get(day)
        if previous is None or row.snapshot_day or not previous.snapshot_day:
            by_day[day] = row
    return [by_day[day] for day in sorted(by_day)]


def _team_payload(team, season, metrics):
    data = {'id': team.pk, 'name': team.name, **metrics}
    history = _history(team, season)
    for field in ('total_coins', 'productivity_per_day', 'total_players', 'total_traders'):
        data['all_day_' + field] = [
            {'id': row.pk, 'date': row.date, field: getattr(row, field)} for row in history]
    return data


def _ranking(team, balances):
    ranking, previous, rank = [], None, 0
    for index, balance in enumerate(balances, start=1):
        score = balance.earn_in_team_per_month
        if score != previous:
            rank = index  # Competition ranks (1, 1, 3); stable PK order for ties.
        previous = score
        ranking.append({
            'id': balance.pk,
            'tg_name': balance.user.tg_username or '',
            'tg_first_name': balance.user.tg_first_name or '',
            'tg_last_name': balance.user.tg_last_name or '',
            'earn': score,
            'precent': score * 100 / team.money_team if team.money_team > 0 else 0,
            'position': rank,
        })
    return ranking


def team_snapshot(user_id, at=None):
    from .gameplay import GameplayError, settle

    at = at or timezone.now()
    # End the player's balance/team transaction before locking both teams.
    # Otherwise opposing-team requests can lock the pair in opposite order.
    settle(user_id, at)
    with transaction.atomic():
        season = relevant_season(at)
        if not season or not season.first_team_id or not season.second_team_id:
            raise GameplayError('Сезон не создан или команды не настроены', 404)
        teams = {team.pk: team for team in Team.objects.select_for_update()
                 .filter(pk__in=(season.first_team_id, season.second_team_id)).order_by('pk')}
        player = UserBalance.objects.get(user_id=user_id)
        if player.team_id not in teams:
            raise GameplayError('У тебя нет команды в текущем сезоне', 404)
        result = {}
        for label, team_id in (('first', season.first_team_id), ('second', season.second_team_id)):
            team = teams[team_id]
            metrics, balances = team_metrics(team)
            _snapshot_locked(team, season, at, metrics)
            result[f'stats_{label}_team'] = _team_payload(team, season, metrics)
            ranking = _ranking(team, balances)
            result[f'leaderboard_{label}_team'] = ranking[:10]
            if player.team_id == team_id:
                result['my_position'] = {
                    **next(row for row in ranking if row['id'] == player.pk), 'team_id': team_id}
        return result
