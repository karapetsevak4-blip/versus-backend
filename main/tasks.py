from celery import shared_task
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


@shared_task(acks_late=True, reject_on_worker_lost=True)
def decide_about_stop_boost():
    from .models import Season
    season = Season.objects.filter(active=True).select_related('winner_of_weak', 'losser_of_weak').last()
    if season:
        if season.losser_of_weak and season.winner_of_weak:
            if season.losser_of_weak.money_team >= season.winner_of_weak.money_team:
                season.losser_of_weak.boost_team = 1.0
                print('Баланс сравнялся!! Буст отключен')


@shared_task(acks_late=True, reject_on_worker_lost=True)
def activate_team_boost():
    from .models import Season
    season = Season.objects.select_related('first_team', 'second_team').filter(active=True).last()
    if season:
        first_team = season.first_team
        last_team = season.second_team
        first_team.money_for_weak /= 7
        last_team.money_for_weak /= 7
        winner = None
        loser = None
        if first_team.money_team > last_team.money_team:
            winner = first_team
            loser = last_team
        else:
            winner = last_team
            loser = first_team

        g = (winner.money_team / loser.money_team) - 1 if loser.money_team != 0 and winner.money_team != 0 else 'pass'
        # относительный разрыв между командами.
        if g != 'pass':
            rA = winner.money_for_weak  # средний дневной прирост монет лидирующей команды за последнюю неделю.
            rB = loser.money_for_weak  # средний дневной прирост монет отстающей команды за последнюю неделю.
            k = 3
            m_raw = 1 + (g - 0.2) * (rA / rB) / 3
            m = min(max(m_raw, 1), 1.5)
            loser.boost_team = m
            winner.boost_team = 1.0
            loser.money_for_weak = 0
            winner.money_for_weak = 0
            loser.save(update_fields=['boost_team', 'money_for_weak'])
            winner.save(update_fields=['boost_team', 'money_for_weak'])
            season.winner_of_weak = winner
            season.losser_of_weak = loser
            season.save(update_fields=['winner_of_weak', 'losser_of_weak'])
        print('Недельный бонус проигравшей команде активировался')


@shared_task(acks_late=True, reject_on_worker_lost=True)
def calculate_personal_money():
    from .models import UserBalance
    from .gameplay import settle, GameplayError
    at = timezone.now()
    # One shared cursor with API reads and claims. Retrying the task after a
    # partial run cannot pay the already processed interval for a second time.
    credited = 0
    for user_id in UserBalance.objects.filter(team__isnull=False).values_list('user_id', flat=True).iterator():
        try:
            credited += settle(user_id, at=at)
        except GameplayError:
            # Bad catalog/player state is visible in logs and does not starve
            # other players. Database failures still abort and can be retried.
            logger.exception('Could not settle player balance %s', user_id)
    return credited


@shared_task
def finish_season(season_id):
    from .test_mode import require_financial_operations
    require_financial_operations()
    from .models import Season, UserBalance

    season = Season.objects.filter(id=season_id, active=True).first()
    if not season:
        return

    # An earlier ETA can still execute after the admin extends a season.
    # The stored end time is authoritative, not the queued job's old ETA.
    if timezone.now() < season.finish_time:
        return

    t1 = season.first_team
    t2 = season.second_team
    if not t1 or not t2:
        return

    if t1.money_team > t2.money_team:
        season.winner = t1
        season.losser = t2
    else:
        season.winner = t2
        season.losser = t1

    full_prize = season.prize
    for user_balance in UserBalance.objects.filter(team=season.winner).order_by('earn_in_team_per_month').all():
        procent = (user_balance.earn_in_team_per_month * 100) / season.winner.money_team
        prize = int(season.prize * (100 / procent))
        if prize > 5:
            user_balance.money_for_winner += prize
            user_balance.save(update_fields=['money_for_winner'])
            full_prize -= prize
        else:
            season.prize = 0
            break

    season.active = False
    season.save(update_fields=['active', 'winner', 'losser', 'prize'])


@shared_task(acks_late=True, reject_on_worker_lost=True)
def create_team_stats():
    from .models import Team, TeamStats, UserBalance, Season, UserTraders

    season = Season.objects.filter(active=True).first()
    if not season:
        return

    for team in Team.objects.all():

        old_stats = TeamStats.objects.filter(team=team).first()

        total_traders = 0
        productivity_per_day = 0

        user_balances = (
            UserBalance.objects
            .filter(team=team)
            .select_related('my_ofice__ofice')
            .prefetch_related('my_ofice__traders__trader')
        )

        for person in user_balances:
            office = person.my_ofice.ofice
            comfort_bonus = 1 + office.comfort

            person_salary = 0

            for user_trader in person.my_ofice.traders.all():
                earn = user_trader.trader.earn_for_day

                person_salary += earn
                total_traders += 1


            productivity_per_day += person_salary * comfort_bonus

        TeamStats.objects.create(
            team=team,
            total_coins=team.money_team,
            productivity_per_day=productivity_per_day,
            total_players=user_balances.count(),
            total_traders=total_traders,
        )
