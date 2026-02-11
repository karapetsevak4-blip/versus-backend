from celery import shared_task
from django.utils import timezone
from datetime import timedelta


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
            loser.save()
            winner.save()
            season.winner_of_weak = winner
            season.losser_of_weak = loser
            season.save()
        print('Недельный бонус проигравшей команде активировался')


@shared_task(acks_late=True, reject_on_worker_lost=True)
def calculate_personal_money():
    from .models import UserBalance, Transaction, UserOfice, Season, TeamStats
    season = Season.objects.select_related('first_team', 'second_team').filter(active=True).last()
    if season:
        first_team = season.first_team
        last_team = season.second_team
        first_team.money_for_day = 0
        last_team.money_for_day = 0
        first_team.save()
        last_team.save()
        for user_balance in UserBalance.objects.select_related('team', 'user').all():
            if not user_balance.team:
                continue
            boost = user_balance.team.boost_team
            salary = 0
            earn = 0
            user_ofice = UserOfice.objects.prefetch_related('traders__trader').filter(user=user_balance.user).first()
            for i in user_ofice.traders.all():
                salary += i.trader.earn_for_day
            transaction = Transaction.objects.filter(user=user_balance.user, completed=True).first()
            if transaction and boost > 1.0:
                earn = (salary * (1 + user_balance.my_ofice.ofice.comfort)) * boost
            else:
                earn = salary * (1 + user_balance.my_ofice.ofice.comfort)

            max_value_for_bank = user_ofice.ofice.safe_capacity

            if user_balance.my_bank == max_value_for_bank:
                earn = 0

            elif user_balance.my_bank + earn < max_value_for_bank:
                user_balance.my_bank += earn

            else:
                earn = (user_balance.my_bank + earn) - max_value_for_bank
                user_balance.my_bank += earn

            stats_team = TeamStats.objects.filter(team=user_balance.team).first()
            stats_team.total_coins += earn
            stats_team.save()
            user_balance.earn_in_team_per_weak += earn
            user_balance.save()
            user_balance.team.money_for_day += earn
            user_balance.team.money_for_weak += earn
            user_balance.team.money_team += earn
            user_balance.team.save()

        print('Деньги удачно зачислены')


@shared_task
def finish_season(season_id):
    from .models import Season, UserBalance

    season = Season.objects.filter(id=season_id, active=True).first()
    if not season:
        return

    t1 = season.first_team
    t2 = season.second_team
    if not t1 or not t2:
        return

    if t1.money_team > t2.money_team:
        season.winner = t1
        season.loser = t2
    else:
        season.winner = t2
        season.loser = t1

    full_prize = season.prize
    for user_balance in UserBalance.objects.filter(team=season.winner).order_by('earn_in_team_per_month').all():
        procent = (user_balance.earn_in_team_per_month * 100) / season.winner.money_team
        prize = int(season.prize * (100 / procent))
        if prize > 5:
            user_balance.money_for_winner += prize
            user_balance.save()
            full_prize -= prize
        else:
            season.prize = 0
            break

    season.active = False
    season.save()


@shared_task(acks_late=True, reject_on_worker_lost=True)
def create_team_stats():
    from .models import Team, TeamStats, UserBalance, Season
    season = Season.objects.filter(active=True).afirst()
    if season:
        for i in Team.objects.all():
            old_stats = TeamStats.objects.filter(team=i).first()
            salary = 0
            len_of_traders = 0
            productivity_per_day = 0
            for person in UserBalance.objects.filter(team=i).prefetch_related('my_ofice__traders').select_related(
                    'my_ofice__ofice').all():
                for i in person.my_ofice.traders.all():
                    len_of_traders += 1
                    salary += i.trader.earn_for_day
                    i.total += i.trader.earn_for_day * (1 + person.my_ofice.ofice.comfort)
                    i.save()
                productivity_per_day += salary * (1 + person.my_ofice.ofice.comfort)
            TeamStats.objects.create(team=i, total_coins=old_stats.total_coins,
                                      productivity_per_day=old_stats.productivity_per_day / old_stats.total_players if old_stats.total_players != 0 else 0,
                                      total_players=old_stats.total_players, total_traders=len_of_traders)
    else:
        pass
