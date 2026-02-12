from rest_framework import serializers

class RefererAndCreateUser(serializers.Serializer):
    Authorization = serializers.CharField()
    refer_id = serializers.IntegerField()


class ApplyWallet(serializers.Serializer):
    wallet=serializers.CharField()

class ApplyTeam(serializers.Serializer):
    team_id = serializers.IntegerField()

class ChangeTeam(serializers.Serializer):
    team_id= serializers.IntegerField()
    currency = serializers.CharField()

class CreateInvoiceLink(serializers.Serializer):
    price = serializers.IntegerField()


class ApplyTradersInOfice(serializers.Serializer):
    first_user_id_trader = serializers.IntegerField()
    second_user_id_trader = serializers.IntegerField(allow_null=True)


class BuySomething(serializers.Serializer):
    model = serializers.CharField()
    id_products = serializers.IntegerField()
    count = serializers.IntegerField()


class ChangeNickName(serializers.Serializer):
    nickname = serializers.CharField()