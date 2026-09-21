import os

from asgiref.sync import sync_to_async
from rest_framework import serializers
from ..models import *
from django.utils import timezone


class CurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Currency
        fields = '__all__'


class MyTeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ['id', 'name']


class MainPAgeOficeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ofice
        fields = ['id', 'lvl']


class TradersSerializer(serializers.ModelSerializer):
    # Keep the existing JSON-number contract; calculations use database decimals.
    price = serializers.FloatField(read_only=True)
    currency = CurrencySerializer()
    picture = serializers.SerializerMethodField()

    class Meta:
        model = Traders
        fields = '__all__'

    def get_picture(self, obj):
        if not obj.picture:
            return None

        url = obj.picture.url  # /media/...
        return os.getenv('BACK_URL') + url


class UserTraderOficeSerializer(serializers.ModelSerializer):
    trader = TradersSerializer()
    class Meta:
        model = UserTraders
        fields = ['id','trader','total']

class UserTradersSerializer(serializers.ModelSerializer):
    trader = TradersSerializer()
    isActive = serializers.SerializerMethodField()

    class Meta:
        model = UserTraders
        fields = ['id','trader','total','isActive']

    def get_isActive(self, obj):
        my_traders = self.context.get('my_traders')
        if obj.id in my_traders:
            return True
        else:
            return False


class OficeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ofice
        fields = ['id', 'lvl', 'count_of_traders', 'comfort', 'safe_capacity', 'safe_capacity_per_trader', 'price']


class FullMainPAgeOficeSerializer(serializers.ModelSerializer):
    ofice = OficeSerializer()
    traders = UserTraderOficeSerializer(many=True)

    class Meta:
        model = UserOfice
        fields = ['id', 'ofice', 'traders']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['ofice']['safe_capacity'] = instance.ofice.capacity_for(len(data['traders']))
        return data


class UserBalanceSerializer(serializers.ModelSerializer):
    token_money = serializers.FloatField(read_only=True)
    team = MyTeamSerializer(allow_null=True)
    my_ofice = FullMainPAgeOficeSerializer()
    list_of_my_traders = UserTradersSerializer(many=True)
    your_share_in_team = serializers.SerializerMethodField()

    class Meta:
        model = UserBalance
        fields = ['id', 'token_money', 'game_coin', 'team', 'can_change_team_for_pay', 'my_ofice', 'my_bank',
                  'earn_in_team_per_month', 'price_per_change_team', 'earn_in_team_per_weak', 'list_of_my_traders',
                  'your_share_in_team']


    def get_your_share_in_team(self, obj):
        if not obj.team:
            return None
        elif obj.team.money_team == 0 or obj.earn_in_team_per_month == 0:
            return 0
        elif obj.team:
            return float((obj.earn_in_team_per_month * 100) / obj.team.money_team)


class TeamSerializer(serializers.ModelSerializer):
    percent = serializers.SerializerMethodField()
    ear_per_minute = serializers.SerializerMethodField()
    boost_team = serializers.SerializerMethodField()
    total_players = serializers.SerializerMethodField()
    picture = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = '__all__'

    def get_percent(self, obj):
        total_price = self.context.get('total_price')
        if total_price and total_price > 0:
            return round((obj.money_team * 100) / total_price)
        return 0

    def get_ear_per_minute(self, obj):
        return self._metrics(obj)['productivity_per_day'] / 1440

    def _metrics(self, obj):
        metrics = self.context.get('team_metrics', {}).get(obj.pk)
        if metrics is None:
            from ..team_stats import team_metrics
            metrics = team_metrics(obj)[0]
        return metrics

    def get_total_players(self, obj):
        return self._metrics(obj)['total_players']

    def get_boost_team(self, obj):
        if obj.boost_team == 1.0:
            return None
        else:
            return round((obj.boost_team - 1) * 100)

    def get_picture(self, obj):
        if not obj.picture:
            return None

        url = obj.picture.url
        return os.getenv('BACK_URL') + url


class SeasonSerializer(serializers.ModelSerializer):
    first_team = serializers.SerializerMethodField()
    second_team = serializers.SerializerMethodField()
    timer = serializers.SerializerMethodField()

    class Meta:
        model = Season
        fields = ['id', 'first_team', 'second_team', 'timer', 'prize']

    def get_timer(self, obj):
        now = self.context.get('at') or timezone.now()
        if obj.finish_time > now:  # Если таймер еще идет
            delta = obj.finish_time - now
            total_seconds = int(delta.total_seconds())
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60

            # Форматируем с ведущими нулями
            return f"{days:02d}:{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:  # Если уже завершился
            return "00:00:00:00"

        # Извлекаем компоненты

    def get_first_team(self, obj):
        if not obj.first_team:
            return None
        total_price = sum(team.money_team for team in (obj.first_team, obj.second_team) if team)
        context = {**self.context, 'total_price': total_price}
        return TeamSerializer(obj.first_team, context=context).data

    def get_second_team(self, obj):
        if not obj.second_team:
            return None
        total_price = sum(team.money_team for team in (obj.first_team, obj.second_team) if team)
        context = {**self.context, 'total_price': total_price}
        return TeamSerializer(obj.second_team, context=context).data


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = '__all__'


class UserDataForMainPageSerializer(serializers.Serializer):
    name = serializers.CharField()
    team = serializers.CharField()


class OnboardingDataSerializer(serializers.Serializer):
    season = SeasonSerializer()


class MainPageSerializer(serializers.Serializer):
    season = SeasonSerializer()
    user = UserSerializer()
    user_balance = UserBalanceSerializer()


class UserOficeSerializer(serializers.ModelSerializer):
    ofice = OficeSerializer()
    traders = UserTradersSerializer(many=True)


    class Meta:
        model = UserOfice
        fields = ['id', 'ofice', 'traders']


class ClaimUserHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ClaimUserHistory
        fields = ['id', 'datatime', 'money']


class MyOficeSerializer(serializers.Serializer):
    productivity_per_day = serializers.FloatField()
    history_claims = ClaimUserHistorySerializer(many=True, allow_null=True)
    all = serializers.IntegerField()
    occupied = serializers.IntegerField()
    empty = serializers.IntegerField()


class SpecialOficeSerializer(serializers.ModelSerializer):
    block = serializers.SerializerMethodField()
    currency = CurrencySerializer()

    class Meta:
        model = Ofice
        fields = '__all__'

    def get_block(self, obj):
        lvl = self.context.get('my_lvl')
        if lvl and lvl >= obj.lvl:
            return True
        return False


class ShopSerializer(serializers.Serializer):
    traders = TradersSerializer(many=True, allow_null=True)
    ofices = SpecialOficeSerializer(many=True, allow_null=True)
