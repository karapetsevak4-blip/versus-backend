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
    pass


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
        # Saving configuration, including a future season, is not rollover.
        # Progress resets require a separately approved season transition.

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
