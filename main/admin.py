from django.contrib import admin

from .models import *
from .tasks import finish_season
from .season_forms import SeasonAdminForm
from django.db import transaction


@admin.register(User)
class CustomUserAdmin(admin.ModelAdmin):
    pass


@admin.register(UserBalance)
class UserBalanceAdmin(admin.ModelAdmin):
    pass


@admin.register(UserStatistics)
class UserStatisticsAdmin(admin.ModelAdmin):
    pass


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        TeamStats.objects.create(team=obj)


@admin.register(TeamStats)
class TeamStatsAdmin(admin.ModelAdmin):
    pass


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    form = SeasonAdminForm
    readonly_fields = ('finish_time',)
    list_display = ('id', 'start_time', 'finish_time', 'active', 'prize')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        moscow_tz = pytz.timezone('Europe/Moscow')
        # Editing duration/prize must not reset everyone's progress.
        # Preserve existing new-season initialization until lifecycle review.
        if not change:
            for user_balance in UserBalance.objects.all():
                user_balance.earn_in_team_per_month = 0
                user_balance.earn_in_team_per_weak = 0
                user_balance.team = None
                user_balance.can_change_team_for_pay = True
                user_balance.save(update_fields=['earn_in_team_per_month', 'earn_in_team_per_weak',
                                                  'team', 'can_change_team_for_pay'])

            for team in Team.objects.all():
                team.money_team = 0
                team.money_for_weak = 0
                team.money_for_day = 0
                team.boost_team = 1.0
                team.save(update_fields=['money_team', 'money_for_weak', 'money_for_day', 'boost_team'])

        finish = obj.finish_time
        if timezone.is_naive(finish):
            finish = moscow_tz.localize(finish)
        season_id = obj.pk
        transaction.on_commit(lambda: finish_season.apply_async(args=[season_id], eta=finish))


@admin.register(Ofice)
class OficeAdmin(admin.ModelAdmin):
    pass


@admin.register(UserOfice)
class UserOficeAdmin(admin.ModelAdmin):
    pass


@admin.register(Traders)
class TradersAdmin(admin.ModelAdmin):
    pass


@admin.register(UserTraders)
class UserTradersAdmin(admin.ModelAdmin):
    pass


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    pass


# @admin.register(Task)
# class TaskAdmin(admin.ModelAdmin):
#     pass
#
# @admin.register(UserTask)
# class UserTaskAdmin(admin.ModelAdmin):
#     pass
#
# @admin.register(SocialTask)
# class SocialTaskAdmin(admin.ModelAdmin):
#     pass
#
#
# @admin.register(UserSocialTask)
# class UserSocialTaskAdmin(admin.ModelAdmin):
#     pass

@admin.register(ClaimUserHistory)
class ClaimUserHistoryAdmin(admin.ModelAdmin):
    pass


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    pass
