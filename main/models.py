from celery.worker.strategy import default
from django.db import models
from django.utils.timezone import now
from datetime import date
from django.utils import timezone
from .tasks import finish_season
import pytz


def get_moscow_time():
    moscow_tz = pytz.timezone("Europe/Moscow")
    return now().astimezone(moscow_tz)


class User(models.Model):
    tg_id = models.BigIntegerField(verbose_name='Телеграм Ид')
    tg_username = models.CharField(verbose_name='Телеграм изернейм', null=True, blank=True)
    tg_first_name = models.CharField(null=True, blank=True, verbose_name='Телеграм Имя')
    tg_last_name = models.CharField(null=True, blank=True, verbose_name='Телеграм Фамилия')
    photo_url = models.URLField(verbose_name='Фото', null=True, blank=True)
    first_visit = models.DateTimeField(default=get_moscow_time, verbose_name='Дата и время регистрации')
    last_visit = models.DateField(default=date.today, verbose_name='Дата последнего входа')
    count_of_visit = models.IntegerField(default=1, verbose_name='сумма Количество заходов')
    visit_without_pass = models.IntegerField(default=1, verbose_name='Количество заходов без пропусков')
    is_baned = models.BooleanField(default=False)
    can_take_daly_tasks = models.BooleanField(default=True, verbose_name='может выполнять дневные задания')
    wallet_address = models.CharField(verbose_name='Адрес кошелька', null=True, blank=True)
    referrer = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='referrals',
                                 verbose_name='Кто пригласил')

    class Meta:
        indexes = [
            models.Index(fields=['tg_id']),
        ]
        verbose_name = 'Юзеры'
        verbose_name_plural = 'Юзеры'

    def __str__(self):
        return f'tg_id:{self.tg_id},tg_username:{self.tg_username},tg_first_name:{self.tg_first_name},tg_last_name:{self.tg_last_name},baned:{self.is_baned}'


class UserBalance(models.Model):
    user = models.OneToOneField(User, related_name='user_balance', on_delete=models.CASCADE)
    token_money = models.FloatField(default=0, verbose_name='Общий баланс донатной валюты')
    game_coin = models.BigIntegerField(default=0, verbose_name='Игровая монета')
    team = models.ForeignKey('Team', null=True, blank=True, on_delete=models.SET_NULL, related_name='user_team',
                             verbose_name='Команда')
    can_change_team_for_pay = models.BooleanField(default=True, verbose_name='может ли менять команду')
    price_per_change_team = models.IntegerField(default=100, verbose_name='цена на смену команды')
    my_ofice = models.ForeignKey('UserOfice', null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name='user_team',
                                 verbose_name='Мой офис')
    my_bank = models.IntegerField(default=0, verbose_name='Мой Банк')
    earn_in_team_per_all_time = models.BigIntegerField(default=0, verbose_name='Всего денег')
    earn_in_team_per_month = models.BigIntegerField(default=0, verbose_name='Всего заработано в команде')
    earn_in_team_per_weak = models.IntegerField(default=0, verbose_name='Заработок за неделю')
    money_for_winner = models.IntegerField(default=0, verbose_name='Деньги для выдачи по окончанию сезона')
    list_of_my_traders = models.ManyToManyField('UserTraders', related_name='user_traders', null=True,
                                                blank=True,
                                                verbose_name='Мои трейдеры')
    count_of_share_invite_link = models.IntegerField(default=0)
    count_of_friends = models.IntegerField(default=0)
    money_which_i_donate = models.FloatField(default=0, verbose_name='Деньгии которые я задонатил')

    class Meta:
        verbose_name = 'Юзеров Баланс '
        verbose_name_plural = 'Юзеров Баланс '

    def __str__(self):
        if self.user:
            return f'user_tg_id:{self.user.tg_id},tg_username:{self.user.tg_username},tg_first_name:{self.user.tg_first_name},tg_last_name:{self.user.tg_last_name},baned:{self.user.is_baned}'
        else:
            return ''


class UserStatistics(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_stats')
    received_coins_from_ref = models.IntegerField(default=0)
    friends_are_inv = models.IntegerField(default=0)

    class Meta:
        verbose_name = 'Статистика Юзеров'
        verbose_name_plural = 'Статистика Юзеров'

    def __str__(self):
        if self.user:
            return f'user_tg_id:{self.user.tg_id},tg_username:{self.user.tg_username}'
        else:
            return ''


class Team(models.Model):
    name = models.CharField(verbose_name='Название команды')
    money_team = models.BigIntegerField(verbose_name='Деньги команды', default=0)
    money_for_weak = models.FloatField(verbose_name='Недельный прирост', default=0)
    money_for_day = models.FloatField(verbose_name='Дневной прирост', default=0)
    boost_team = models.FloatField(verbose_name='Буст команды в процентах', default=1)
    picture = models.ImageField(upload_to='', null=True, blank=True)

    class Meta:
        verbose_name = 'Команды'
        verbose_name_plural = 'Команды'

    def __str__(self):
        return f'id:{self.id},name:{self.name},boost_team:{self.boost_team}'


class Season(models.Model):
    first_team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='first_season_team')
    second_team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='second_season_team')
    start_time = models.DateTimeField()
    finish_time = models.DateTimeField()
    winner_of_weak = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='winner_weak_team',
                                       verbose_name='Команда победившая по очкам в прошлой неделе')
    losser_of_weak = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='losser_weak_team',
                                       verbose_name='Команда проигравашая по очкам в прошлой неделе')
    active = models.BooleanField(verbose_name='Активен ли сезон', default=False)
    winner = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='winner_team',
                               verbose_name='Команда победившая сезон по очкам')
    losser = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='losser_team',
                               verbose_name='Команда проигравашая сезон по очкам')
    prize = models.BigIntegerField(default=10000)

    def save_model(self, request, obj, form, change):
        """Переопределенный метод сохранения модели в Django Admin"""
        super().save_model(request, obj, form, change)  # Сначала сохраняем объект

        moscow_tz = pytz.timezone('Europe/Moscow')
        if not change:
            if timezone.now() >= obj.start_time:
                obj.active = True
                obj.save(update_fields=['active'])

                finish_season.apply_async(
                    args=[obj.id],
                    eta=obj.finish_time
                )

    class Meta:
        verbose_name = 'Сезон'
        verbose_name_plural = 'Сезон'

    def __str__(self):
        return f'id:{self.id},finish_time:{self.finish_time},prize:{self.prize}'


def get_default_season():
    """Функция, которая будет вызываться при каждом создании объекта"""
    try:
        season = Season.objects.filter(active=True).first()
        return season.pk if season else None
    except Season.DoesNotExist:
        return None


class TeamStats(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='team_stats')
    season = models.ForeignKey("Season", on_delete=models.SET_NULL, null=True, blank=True, related_name='season_team',
                               default=get_default_season)
    total_coins = models.IntegerField(default=0)
    productivity_per_day = models.FloatField(default=0)
    total_players = models.IntegerField(default=0)
    total_traders = models.IntegerField(default=0)
    date = models.DateTimeField(default=get_moscow_time)

    class Meta:
        verbose_name = 'Статистика Команд'
        verbose_name_plural = 'Статистика Команд'

    if team:
        def __str__(self):
            return f'id:{self.id},team_name:{self.team.name},date:{self.date}'
    else:
        def __str__(self):
            return f'id:{self.id}'


class Ofice(models.Model):
    lvl = models.IntegerField(default=1, verbose_name='Уровень офиса')
    count_of_traders = models.IntegerField(default=3, verbose_name='Количество трейдоров для данного уровня офиса',
                                           null=True, blank=True)
    comfort = models.FloatField(verbose_name='Бонус к результату трейдеров')
    safe_capacity = models.IntegerField(verbose_name='Максимум очков, которые копятся до клейма')
    price = models.IntegerField(verbose_name='Стоимость уровня', null=True, blank=True)
    currency = models.ForeignKey('Currency', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                 verbose_name='Тип валюты')

    class Meta:
        verbose_name = 'Офис'
        verbose_name_plural = 'Офис'

    def __str__(self):
        return f'lvl:{self.lvl},count_of_traders:{self.count_of_traders},price:{self.price}'


class UserOfice(models.Model):
    user = models.ForeignKey(User, related_name='userofice_user', on_delete=models.CASCADE)
    ofice = models.ForeignKey(Ofice, related_name='userofice_ofice', on_delete=models.SET_NULL, null=True,
                              blank=True, )
    traders = models.ManyToManyField('UserTraders', related_name='userofice_traders', null=True,
                                     blank=True,
                                     verbose_name='трейдеры')

    class Meta:
        verbose_name = 'Офисы Юзеров'
        verbose_name_plural = 'Офисы Юзеров'

    def __str__(self):
        if self.user and self.ofice:
            return f'user_tg_id:{self.user.tg_id}, ofice_lvl:{self.ofice.lvl}'
        return f''


class Traders(models.Model):
    name = models.CharField(default='Trader')
    earn_for_day = models.FloatField(verbose_name='Заработок за день')
    price = models.IntegerField(verbose_name='Цена')
    lvl = models.IntegerField(verbose_name='Уровень', default=1)
    currency = models.ForeignKey('Currency', on_delete=models.SET_NULL, related_name='+', null=True, blank=True,
                                 verbose_name='Тип валюты')
    picture = models.ImageField(upload_to='', null=True, blank=True)

    class Meta:
        verbose_name = 'Трэйдерс'
        verbose_name_plural = 'Трэйдерс'

    def __str__(self):
        return f'name:{self.name},earn_for_day:{self.earn_for_day},price:{self.price}'


class UserTraders(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_traders')
    trader = models.ForeignKey(Traders, on_delete=models.SET_NULL, null=True, blank=True, related_name='trader_user')
    total = models.IntegerField(default=0)

    class Meta:
        verbose_name = 'Трейдеры Юзеров'
        verbose_name_plural = 'Трейдеры Юзеров'

    def __str__(self):
        if self.user and self.trader:
            return f'id:{self.id},user_tg_id:{self.user.tg_id}, trader_lvl:{self.trader.lvl}'
        return f''


class Currency(models.Model):
    name = models.CharField(verbose_name='Название валюты')

    class Meta:
        verbose_name = 'Валюта'
        verbose_name_plural = 'Валюта'

    def __str__(self):
        return f'id:{self.id},name:{self.name}'


# class Task(models.Model):
#     ...
#     daily = models.BooleanField(default=True, verbose_name='Дневная')
#     weekly = models.BooleanField(default=False, verbose_name='Недельная')
#     season = models.BooleanField(default=False, verbose_name='Сезонная')
#
#
# class UserTask(models.Model):
#     task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='user_task')
#     pass


# class SocialTask(models.Model):
#     name = models.CharField()
#     count_of_money = models.BigIntegerField(default=0, verbose_name='Количество денег')
#     currency = models.ForeignKey(Currency, related_name='social_task', on_delete=models.SET_NULL, null=True,
#                                  blank=True)
#     url_link = models.CharField(null=True, blank=True, verbose_name='Ссылка на таску')
#
#     class Meta:
#         verbose_name = 'Таски "Социальные"'
#         verbose_name_plural = 'Таски "Социальные"'
#
#     def __str__(self):
#         return f'id:{self.name}, name:{self.name}'
#
#
# class UserSocialTask(models.Model):
#     user = models.ForeignKey(User, related_name='user_subscribe_task', on_delete=models.CASCADE)
#     social_task = models.ForeignKey(SocialTask, related_name='+', on_delete=models.SET_NULL, null=True,
#                                     blank=True)
#     can_check = models.BooleanField(default=False)
#     complete = models.BooleanField(default=False)
#
#     class Meta:
#         indexes = [
#             models.Index(fields=['user']),
#         ]
#
#         verbose_name = 'Таски "Социальные" Юзеров'
#         verbose_name_plural = 'Таски "Социальные" Юзеров'
#
#     def __str__(self):
#         if self.user and self.social_task:
#             return f"user_tg_id:{self.user.tg_id}, task_name:{self.social_task.name},complete:{self.complete}"
#         else:
#             return ''


class ClaimUserHistory(models.Model):
    user = models.ForeignKey(User, related_name='claim_user_history', on_delete=models.CASCADE)
    datatime = models.DateTimeField(default=get_moscow_time)
    money = models.IntegerField()

    class Meta:
        verbose_name = 'История Claim Users'
        verbose_name_plural = 'История Claim Users'

    def __str__(self):
        if self.user:
            return f'id:{self.id},tg_id:{self.user.tg_id},money:{self.money},datatime:{self.datatime}'
        else:
            return ''


class Transaction(models.Model):
    user = models.ForeignKey(User, related_name='transaction', on_delete=models.SET_NULL, null=True, blank=True)
    price = models.IntegerField(default=0)
    completed = models.BooleanField(verbose_name='Прошли ли операция успешна', default=False)

    class Meta:
        verbose_name = 'Транзакции'
        verbose_name_plural = 'Транзакции'

    def __str__(self):
        if self.user:
            return f'id:{self.id},tg_id:{self.user.tg_id},model:{self.model},completed:{self.completed},price:{self.price}'
        else:
            return ''
