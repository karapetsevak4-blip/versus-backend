from adrf.decorators import api_view
from asgiref.sync import sync_to_async
from django.db.models import Sum
from django.http import HttpRequest, JsonResponse
from drf_yasg.utils import swagger_auto_schema
from datetime import timedelta
from django.utils import timezone
from django.middleware.csrf import get_token, rotate_token

from .Serializers import request_body, response_serializer
from .my_decor import telegram_authenticated, check_user_exists
from .example import get_response_examples
from .services import *
from mysite.settings import price_per_change_team
from .models import *
from .input_validation import positive_integer


@swagger_auto_schema(
    methods=(['POST']),
    query_serializer=request_body.RefererAndCreateUser(),
    responses={
        '404': get_response_examples({'Error': 'Данные переданы некорректные.'}),
        '200': get_response_examples({'Info': 'Success'}),
    },
    tags=['Основа'],
    operation_summary='Cоздать пользователя',

)
@api_view(["POST"])
async def create_my_session(request: HttpRequest):
    failure = await create_session(request)
    if failure is not None:
        return failure

    tg_id = request.session["telegram_user"].get("id")

    user = await User.objects.filter(tg_id=tg_id).afirst()

    if user is None:
        referral_id = request.GET.get("refer_id")

        tg_username = request.session["telegram_user"].get("username")
        tg_first_name = request.session["telegram_user"].get("first_name")
        tg_last_name = request.session["telegram_user"].get("last_name")
        photo_url = request.session["telegram_user"].get("photo_url")
        is_premium = request.session["telegram_user"].get("is_premium")
        user = await User.objects.acreate(tg_id=tg_id, tg_username=tg_username, tg_first_name=tg_first_name,
                                          tg_last_name=tg_last_name, photo_url=photo_url,
                                          )
        ofice = await Ofice.objects.filter(lvl=1).afirst()
        trader = await Traders.objects.filter(lvl=1).afirst()
        if not trader:
            return JsonResponse({'Error': 'Create trader!'}, status=404)
        my_trader = await UserTraders.objects.acreate(user=user, trader=trader)

        my_ofice = await UserOfice.objects.acreate(user=user, ofice=ofice)
        user_balance = await UserBalance.objects.acreate(user=user, my_ofice=my_ofice)

        await my_ofice.traders.aadd(my_trader)
        await UserStatistics.objects.acreate(user=user)
        await user_balance.list_of_my_traders.aadd(my_trader)
        if referral_id:
            old_person = await User.objects.filter(tg_id=int(referral_id)).select_related('user_balance').afirst()
            user_stats = await UserStatistics.objects.filter(user=old_person).afirst()
            if (
                    old_person
                    and user != old_person
            ):
                user.referrer = old_person
                user_stats.friends_are_inv += 1
                old_person.user_balance.game_coin += 500
                old_person.user_balance.earn_in_team_per_all_time += 500
                old_person.user_balance.count_of_friends +=1
                user_balance.game_coin += 500
                user_balance.earn_in_team_per_all_time += 500
                user_stats.received_coins_from_ref += 500
                if is_premium:
                    user_stats.received_coins_from_ref += 3000
                    old_person.user_balance.game_coin += 3000
                    user_balance.game_coin += 3000
                    old_person.user_balance.earn_in_team_per_all_time += 3000
                    user_balance.earn_in_team_per_all_time += 3000
                await user_stats.asave()
                await user_balance.asave()
                await old_person.user_balance.asave()

        await user.asave()

        # TODO добавить трейдера(ов) если они есть в самом начале или выдать какие то деньги

    # [await UserSocialTask.objects.acreate(user=user, social_task=task) async for task in
    #  SocialTask.objects.all() if
    #  not await UserSocialTask.objects.filter(user=user, social_task=task).select_related('user',
    #                                                                                      'social_task').afirst()]
    #
    # [await UserTask.objects.acreate(user=user) async for task in
    #  Task.objects.all() if
    #  not await UserTask.objects.filter(user=user, task=task).select_related('user').afirst()]

    today = date.today()
    if today > user.last_visit:
        user.can_take_daly_tasks = True
        if user.last_visit < today - timedelta(days=1):
            user.count_of_visit += 1
            user.visit_without_pass = 1
        else:
            user.count_of_visit += 1
            user.visit_without_pass += 1
        user.last_visit = today
        # TODO сделать обновление задач
        if user.visit_without_pass >= 8:
            user.visit_without_pass = 1
            # async for user_weekly_task in UserTask.objects.filter(user=user, task__weekly=True).select_related(
            #         'task').all():
            #     ...
            #     await user_weekly_task.asave()

        # async for user_daly_task in UserTask.objects.filter(user=user, task__daily=True).select_related('task').all():
        # user_daly_task.count_of_rase = 0
        # user_daly_task.take_pts = 0
        # user_daly_task.invite_friend = False
        # user_daly_task.complete = False
        # await user_daly_task.asave()

    await user.asave()

    rotate_token(request)
    response = JsonResponse({'Info': 'Success', 'csrf_token': get_token(request)}, status=200)
    response['Cache-Control'] = 'no-store'
    return response


@swagger_auto_schema(
    methods=(['POST']),
    request_body=request_body.ApplyTeam,
    responses={
        '404': get_response_examples({'Error': 'Данные переданы некорректные.'}),
        '200': get_response_examples({'Info': 'Success'}),
    },
    tags=['Основа'],
    operation_summary='Первый выбор команды(анбординг)',

)
@api_view(["POST"])
@telegram_authenticated
@check_user_exists
async def onboarding_apply_team(request: HttpRequest, *args, **kwargs):
    user_balance = kwargs.get('user_balance')
    team_id = request.data.get('team_id')
    team = await Team.objects.filter(id=team_id).afirst()
    statick_team = await TeamStats.objects.filter(team=team).afirst()
    statick_team.total_players += 1
    statick_team.total_traders += len([i async for i in user_balance.my_ofice.traders.all()])
    await statick_team.asave()
    if not user_balance.team:
        user_balance.team = team
        await user_balance.asave()
        return JsonResponse({'Info': 'Success'}, status=200)
    else:
        return JsonResponse({'Error': 'Вы уже прошли онбординг'}, status=404)


@swagger_auto_schema(
    methods=(['GET']),
    responses={
        '404': get_response_examples({'Error': 'Данные переданы некорректные.'}),
        '200': get_response_examples(schema=response_serializer.MainPageSerializer),
    },
    tags=['Основа'],
    operation_summary='Главная странциа',

)
@api_view(["GET"])
@telegram_authenticated
@check_user_exists
async def main_page(request: HttpRequest, *args, **kwargs):
    user = kwargs.get('user')
    user_balance = kwargs.get('user_balance')

    season = await Season.objects.select_related('first_team', 'second_team').alast()
    my_traders = [i.id async for i in user_balance.my_ofice.traders.all()]
    data = response_serializer.MainPageSerializer({
        'season': season,
        'user': user,
        'user_balance': user_balance,
    }, context={'my_traders': my_traders}).data

    return JsonResponse(data, status=200)


@swagger_auto_schema(
    methods=(["POST"]),
    request_body=request_body.ApplyWallet,
    responses={
        '404': get_response_examples({'Error': 'Not wallet'}),
        '200': get_response_examples({'Info': 'success'})
    },
    tags=['Основа'],
    operation_summary='Прикрепить кошелек'
)
@api_view(["POST"])
@telegram_authenticated
@check_user_exists
async def apply_wallet(request: HttpRequest, *args, **kwargs):
    user = kwargs.get('user')
    wallet = request.data.get('wallet')

    if not wallet:
        return JsonResponse({'Error': 'Not wallet'}, status=404)

    if wallet == 'None':
        wallet = None

    user.wallet_address = wallet
    await user.asave()

    return JsonResponse({'Info': 'success'}, status=200)


@swagger_auto_schema(
    methods=(["POST"]),
    request_body=request_body.ChangeTeam,
    responses={
        '404': get_response_examples(
            {'Error': 'Переход в другую команду меньше чем за 3 дня до окончания не возможен '}),
        ' 404': get_response_examples(
            {'Error': 'У вас недостаточно денег для смена команды , баланс не должен быть 0'}),
        '  404': get_response_examples({'Error': 'У вас нет команды'}),
        '   404': get_response_examples(
            {'Error': 'Недотсаточно token_money или в этом сезоне вы уже меняли команду без потери прогресса'}),
        '200': get_response_examples({'Info': 'Команда успешно поменена'})
    },
    tags=['Основа'],
    operation_summary='Поменять команду'
)
@api_view(["POST"])
@telegram_authenticated
@check_user_exists
async def change_team(request: HttpRequest, *args, **kwargs):
    saeson = await Season.objects.alast()
    user_balance = kwargs.get('user_balance')
    today = timezone.now()
    if not user_balance.team:
        return JsonResponse({'Error': 'У вас нет команды'}, status=404)
    if saeson.finish_time - today < timedelta(days=3):
        return JsonResponse({'Error': 'Переход в другую команду меньше чем за 3 дня до окончания не возможен '},
                            status=404)

    currency = request.data.get('currency')
    team_id = request.data.get('team_id')
    new_team = await Team.objects.filter(id=team_id).afirst()
    if currency.lower() == 'game_coin':
        if user_balance.earn_in_team_per_month < 1:
            return JsonResponse({'Error': 'У вас недостаточно денег для смена команды '},
                                status=404)

        user_balance.team.money_team -= user_balance.earn_in_team_per_month
        user_balance.earn_in_team_per_month = int(user_balance.earn_in_team_per_month / 2)
        new_team.money_team += user_balance.earn_in_team_per_month

    if currency.lower() == 'token_money':
        if user_balance.token_money > user_balance.price_per_change_team and user_balance.can_change_team_for_pay:
            user_balance.token_money -= user_balance.price_per_change_team
            user_balance.can_change_team_for_pay = False
            user_balance.team.money_team -= user_balance.earn_in_team
            new_team.money_team += user_balance.earn_in_team
            user_balance.price_per_change_team *= 2
        else:
            return JsonResponse(
                {'Error': 'Недотсаточно token_money или в этом сезоне вы уже меняли команду без потери прогресса'},
                status=404)

    await user_balance.team.asave()
    user_balance.team = new_team
    await user_balance.asave()
    return JsonResponse({'Info': 'Команда успешно поменена'}, status=200)


@swagger_auto_schema(
    methods=(['GET']),
    responses={
        '404': get_response_examples({'Error': 'У вас нет офиса'}),
        '200': get_response_examples(schema=response_serializer.MyOficeSerializer),
    },
    tags=['Офис'],
    operation_summary='Основная информация',

)
@api_view(["GET"])
@telegram_authenticated
@check_user_exists
async def my_ofice(request: HttpRequest, *args, **kwargs):
    user_balance = kwargs.get('user_balance')
    user = kwargs.get('user')
    user_ofice = await UserOfice.objects.prefetch_related('traders__trader', 'ofice').filter(user=user).afirst()
    if not user_balance.my_ofice:
        return JsonResponse({'Error': 'У вас нет офиса'})
    salary = 0
    len_of_traders = 0
    for i in user_ofice.traders.all():
        len_of_traders += 1
        salary += i.trader.earn_for_day
    print(salary)
    claims = [item async for item in ClaimUserHistory.objects.filter(user=user).order_by('id')]
    data = response_serializer.MyOficeSerializer({
        'productivity_per_day': salary * (1 + user_balance.my_ofice.ofice.comfort),  # монеты в день
        # 'total_coins_farmed': user_balance.earn_in_team_per_month,
        'history_claims': claims,
        'all': user_ofice.ofice.count_of_traders,
        'occupied': len_of_traders,
        'empty': user_ofice.ofice.count_of_traders - len_of_traders,
    }).data

    return JsonResponse(data, status=200)


@swagger_auto_schema(
    methods=(["POST"]),
    request_body=request_body.ApplyTradersInOfice,
    responses={
        '404': get_response_examples({'Error': 'У вас нет офиса'}),
        ' 404': get_response_examples(
            {'Error': 'id first_user_id_trader передан не верно , такого трейдера у юзера нет'}),
        '  404': get_response_examples(
            {'Error': 'id second_user_id_trader передан не верно , такого трейдера у юзера нет'}),
        '   404': get_response_examples(
            {'Error': 'Не хватает места в данном офисе или этот трейдер уже используется у вас в офисе'}),
        '200': get_response_examples({'Info': 'Success'})
    },
    tags=['Офис'],
    operation_summary='Посадить(заменить) трейдера в офис(е)'
)
@api_view(["POST"])
@telegram_authenticated
@check_user_exists
async def apply_traders_in_ofice(request: HttpRequest, *args, **kwargs):
    user_balance = kwargs.get('user_balance')
    user = kwargs.get('user')
    user_ofice = await UserOfice.objects.prefetch_related('traders__trader', 'ofice').filter(user=user).afirst()
    if not user_balance.my_ofice:
        return JsonResponse({'Error': 'У вас нет офиса'})

    try:
        first_user_id_trader = positive_integer(request.data.get('first_user_id_trader'))
        second_user_id_trader = request.data.get('second_user_id_trader')
        if second_user_id_trader is not None:
            second_user_id_trader = positive_integer(second_user_id_trader)
    except ValueError:
        return JsonResponse({'Error': 'Invalid trader ID'}, status=400)
    # Identity comes from the verified session, never the submitted object ID.
    first_traders = await UserTraders.objects.filter(id=first_user_id_trader, user=user).afirst()
    if not first_traders:
        return JsonResponse({'Error': 'id first_user_id_trader передан не верно , такого трейдера у юзера нет'},
                            status=404)

    if first_user_id_trader and second_user_id_trader:
        second_trader = await UserTraders.objects.filter(id=second_user_id_trader, user=user).afirst()
        if not second_trader:
            return JsonResponse({'Error': 'id second_user_id_trader передан не верно , такого трейдера у юзера нет'},
                                status=404)

        if (not await user_ofice.traders.filter(pk=first_traders.pk).aexists()
                or await user_ofice.traders.filter(pk=second_trader.pk).aexists()):
            return JsonResponse({'Error': 'Invalid replacement position'}, status=400)
        await user_ofice.traders.aremove(first_traders)
        await user_ofice.traders.aadd(second_trader)
        return JsonResponse({'Info': 'Success'}, status=200)
    else:
        traders = [trader async for trader in user_ofice.traders.all()]
        print(user_ofice.ofice.count_of_traders)
        print(len(traders))
        if user_ofice.ofice.count_of_traders > len(traders) and first_traders not in traders:
            await user_ofice.traders.aadd(first_traders)
            return JsonResponse({'Info': 'Success'}, status=200)
        else:
            return JsonResponse(
                {'Error': 'Не хватает места в данном офисе или этот трейдер уже используется у вас в офисе'},
                status=404)


@swagger_auto_schema(
    methods=(['POST']),
    responses={
        '404': get_response_examples({'Error': 'У вас нет команды'}),
        ' 404': get_response_examples({'Error': 'У вас нет монет для сбора'}),
        '200': get_response_examples({'Info': 'Операция прошла успешно'}),
    },
    tags=['Офис'],
    operation_summary='Забрать банк',

)
@api_view(["POST"])
@telegram_authenticated
@check_user_exists
async def claim_bank(request: HttpRequest, *args, **kwargs):
    user_balance = kwargs.get('user_balance')
    user = kwargs.get('user')
    if not user_balance.team:
        return JsonResponse({'Error': 'У вас нет команды'}, status=404)
    if user_balance.my_bank == 0:
        return JsonResponse({'Error': 'У вас нет монет для сбора'}, status=404)
    user_balance.game_coin += user_balance.my_bank
    user_balance.earn_in_team_per_all_time += user_balance.my_bank
    await ClaimUserHistory.objects.acreate(user=user, money=user_balance.my_bank)
    user_balance.my_bank = 0
    await user_balance.team.asave()
    await user_balance.asave()
    return JsonResponse({'Info': 'Операция прошла успешно'}, status=200)


@swagger_auto_schema(
    methods=(['GET']),
    responses={
        '404': get_response_examples({'Error': 'У вас нет команды'}),
        ' 404': get_response_examples({'Error': 'У вас нет монет для сбора'}),
        '200': get_response_examples(schema=response_serializer.ShopSerializer),
    },
    tags=['SHOP'],
    operation_summary='Получить список покупок',

)
@api_view(["GET"])
@telegram_authenticated
@check_user_exists
async def get_shop(request: HttpRequest, *args, **kwargs):
    user_balance = kwargs.get('user_balance')
    user = kwargs.get('user')
    traders = [trader async for trader in Traders.objects.select_related('currency').order_by('lvl').all()]
    ofices = [ofice async for ofice in Ofice.objects.select_related('currency').order_by('lvl').all()]
    context = {'my_lvl': user_balance.my_ofice.ofice.lvl}
    data = response_serializer.ShopSerializer({
        'traders': traders,
        'ofices': ofices,
    }, context=context).data

    return JsonResponse(data, status=200)


@swagger_auto_schema(
    methods=(["POST"]),
    request_body=request_body.CreateInvoiceLink,
    responses={
        '404': get_response_examples({'Error': 'Ключи не переданы или user_car не существует'}),
        '404 ': get_response_examples({'Error': 'Финансов недостаточно'}),

        '200 ': get_response_examples({'url': 'url'})
    },
    tags=['Оплата'],
    operation_summary='Получение ссылки'
)
@api_view(["POST"])
@telegram_authenticated
@check_user_exists
async def get_invoice_link(request, *args, **kwargs):
    # Import the bot only in the external payment path, not during checks/login.
    from telegram import create_invoice_link
    user = kwargs.get('user')
    price = request.data.get('price')

    if not price:
        return JsonResponse({'error': 'Missing text or price'}, status=400)

    try:
        user_transaction = await Transaction.objects.acreate(user=user, price=price)

        url = await create_invoice_link(price=user_transaction.price, id=user_transaction.id)
        return JsonResponse({'url': url}, status=200)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@swagger_auto_schema(
    methods=(["POST"]),
    request_body=request_body.BuySomething,
    responses={
        '404': get_response_examples({'Error': 'Не все ключи были переданы'}),
        '404 ': get_response_examples({'Error': 'Данный продукт не найден'}),
        ' 404 ': get_response_examples({'Error': 'У вас недостаточно денег'}),
        '  404 ': get_response_examples({'Error': 'Увровень вашего офиса больше или такой же'}),

        '200 ': get_response_examples({'Info': 'Трейдер удачно куплен'}),
        ' 200 ': get_response_examples({'Info': 'Трейдер удачно куплен'}),
    },
    tags=['Оплата'],
    operation_summary='Купить что нибудь'
)
@api_view(["POST"])
@telegram_authenticated
@check_user_exists
async def buy_something(request, *args, **kwargs):
    user_balance = kwargs.get('user_balance')
    user = kwargs.get('user')

    model = request.data.get('model')
    try:
        count = positive_integer(request.data.get('count', 1))
        id_products = positive_integer(request.data.get('id_products'))
    except ValueError:
        return JsonResponse({'Error': 'Invalid quantity or product ID'}, status=400)

    if not isinstance(model, str) or model.lower() not in {'trader', 'ofice'}:
        return JsonResponse({'Error': 'Invalid product model'}, status=400)

    if not model or not id_products:
        return JsonResponse({'Error': 'Не все ключи были переданы'}, status=404)

    if model.lower() == 'trader':
        trader = await Traders.objects.select_related('currency').filter(id=id_products).afirst()
        if not trader:
            return JsonResponse({'Error': 'Данный продукт не найден'}, status=404)

        if trader.currency.name.lower() == 'stars' and user_balance.token_money >= trader.price * count:
            for i in range(count):
                user_trader = await UserTraders.objects.acreate(user=user, trader=trader)
                await user_balance.list_of_my_traders.aadd(user_trader)
            user_balance.token_money -= trader.price * count
        elif trader.currency.name.lower() == 'coin' and user_balance.game_coin >= trader.price * count:
            for i in range(count):
                user_trader = await UserTraders.objects.acreate(user=user, trader=trader)
                await user_balance.list_of_my_traders.aadd(user_trader)
            user_balance.game_coin -= trader.price * count
        else:
            return JsonResponse({'Error': 'У вас недостаточно денег'}, status=404)

        await user_balance.asave()
        return JsonResponse({'Info': 'Трейдер удачно куплен'}, status=200)

    if model.lower() == 'ofice':
        ofice = await Ofice.objects.select_related('currency').filter(id=id_products).afirst()
        if not ofice:
            return JsonResponse({'Error': 'Данный продукт не найден'}, status=404)
        if not user_balance.my_ofice:
            return JsonResponse({'Error': 'У вас нет офиса'}, status=404)
        traders = user_balance.my_ofice.traders.all()
        if user_balance.my_ofice.ofice.lvl >= ofice.lvl:
            return JsonResponse({'Error': 'Увровень вашего офиса больше или такой же'}, status=404)

        if ofice.currency.name.lower() == 'stars' and user_balance.token_money >= ofice.price:
            user_ofice = await UserOfice.objects.acreate(user=user, ofice=ofice)
            user_balance.my_ofice = user_ofice
            user_balance.token_money -= ofice.price
        elif ofice.currency.name.lower() == 'coin' and user_balance.game_coin >= ofice.price:
            user_ofice = await UserOfice.objects.acreate(user=user, ofice=ofice)
            user_balance.my_ofice = user_ofice
            user_balance.game_coin -= ofice.price
        else:
            return JsonResponse({'Error': 'У вас недостаточно денег'}, status=404)

        await user_balance.my_ofice.traders.aadd(*traders)
        await user_balance.asave()
        last_user_ofice = await UserOfice.objects.filter(user=user).afirst()
        await last_user_ofice.adelete()
        return JsonResponse({'Info': 'Офис удачно куплен'}, status=200)
    else:
        return JsonResponse({'Error': 'Данные переданы некоректно'}, status=404)


@swagger_auto_schema(
    methods=(['GET']),
    responses={
        '404': get_response_examples({'Error': 'У вас нет команды'}),
        ' 404': get_response_examples({'Error': 'У вас нет монет для сбора'}),
        '200': get_response_examples({
            'stats_first_team': {
                'id': 1,
                'name': 'test',
                'total_coins': 100,
                'productivity_per_day': 100.1,
                'total_players': 2,
                'total_traders': 4,
                'all_day_total_coins': [{
                    'id': 1,
                    'date': '2026-01-30T12:13:12',
                    'total_coins': 127,
                }],
                'all_day_productivity_per_day': [{
                    'id': 1,
                    'date': '2026-01-30T12:13:12',
                    'productivity_per_day': 127,
                }],
                'all_day_total_players': [{
                    'id': 1,
                    'date': '2026-01-30T12:13:12',
                    'total_players': 127,
                }],
                'all_day_total_traders': [{
                    'id': 1,
                    'date': '2026-01-30T12:13:12',
                    'total_traders': 127,
                }],
            },
            'stats_second_team': {
                'id': 2,
                'name': 'test',
                'total_coins': 200,
                'productivity_per_day': 100.1,
                'total_players': 2,
                'total_traders': 4,
                'all_day_total_coins': [{
                    'id': 1,
                    'date': '2026-01-30T12:13:12',
                    'total_coins': 127,
                }],
                'all_day_productivity_per_day': [{
                    'id': 1,
                    'date': '2026-01-30T12:13:12',
                    'productivity_per_day': 127,
                }],
                'all_day_total_players': [{
                    'id': 1,
                    'date': '2026-01-30T12:13:12',
                    'total_players': 127,
                }],
                'all_day_total_traders': [{
                    'id': 1,
                    'date': '2026-01-30T12:13:12',
                    'total_traders': 127,
                }],
            },
            'leaderboard_first_team': [
                {
                    'id': 1,
                    'tg_name': 'team1',
                    'tg_first_name': 'fsdf',
                    'tg_last_name': 'gfdgdfg',
                    'earn': 123,
                    'precent': 12.543,
                    'position': 1,

                }],
            'leaderboard_second_team': [
                {
                    'id': 2,
                    'tg_name': 'team2',
                    'tg_first_name': 'aaavvvv',
                    'tg_last_name': 'utyu',
                    'earn': 124,
                    'precent': 25,
                    'position': 1,

                }],
            'my_position': {
                'team_id': 1,
                'tg_name': 'admin',
                'tg_first_name': 'admin',
                'tg_last_name': 'admin',
                'earn': 124543,
                'precent': 76.76,
                'position': 1,
            }})},
    tags=['Team'],
    operation_summary='Получить иформацию о командах + лидерборд',

)
@api_view(["GET"])
@telegram_authenticated
@check_user_exists
async def get_data_team(request: HttpRequest, *args, **kwargs):
    user_balance = kwargs.get('user_balance')
    season = await Season.objects.select_related('first_team', 'second_team').afirst()
    if not season:
        return JsonResponse({'Error': 'Сезон не создан'}, safe=False, status=404)

    user_position = await UserBalance.objects.filter(
        team=user_balance.team,
        earn_in_team_per_month__gt=user_balance.earn_in_team_per_month
    ).acount() + 1
    team_1 = season.first_team
    team_2 = season.second_team
    stats_for_first_team = await TeamStats.objects.filter(team=team_1, season=season).select_related('team',
                                                                                                     'season').afirst()
    stats_for_second = await TeamStats.objects.filter(team=team_2, season=season).select_related('team',
                                                                                                 'season').afirst()

    if not stats_for_first_team and not stats_for_second:
        return JsonResponse({'Error': 'Статистика для команд не создана'}, status=404)

    if not user_balance.team:
        return JsonResponse({'Error': 'У тебя нет команды'}, status=404)
    all_day_total_coins_1 = []
    all_day_productivity_per_day_1 = []
    all_day_total_players_1 = []
    all_day_total_traders_1 = []
    all_day_total_coins_2 = []
    all_day_productivity_per_day_2 = []
    all_day_total_players_2 = []
    all_day_total_traders_2 = []
    total_players_1 = [user async for user in
                       UserBalance.objects.filter(team=season.first_team).select_related('user').order_by(
                           'earn_in_team_per_month').all()[:10]]
    total_players_2 = [user async for user in
                       UserBalance.objects.filter(team=season.second_team).select_related('user').order_by(
                           'earn_in_team_per_month').all()[:10]]

    all_team_stats_1 = [i async for i in TeamStats.objects.filter(team=team_1, season=season).order_by('-date').all()]
    for i in all_team_stats_1:
        all_day_total_coins_1.append({
            'id': i.id,
            'date': i.date,
            'total_coins': i.total_coins,
        })
        all_day_productivity_per_day_1.append({
            'id': i.id,
            'date': i.date,
            'total_coins': i.productivity_per_day,
        })
        all_day_total_players_1.append({
            'id': i.id,
            'date': i.date,
            'total_players': i.total_players,
        })
        all_day_total_traders_1.append({
            'id': i.id,
            'date': i.date,
            'total_traders': i.total_traders,
        })
    all_team_stats_2 = [i async for i in TeamStats.objects.filter(team=team_2, season=season).order_by('-date').all()]
    for i in all_team_stats_2:
        all_day_total_coins_2.append({
            'id': i.id,
            'date': i.date,
            'total_coins': i.total_coins,
        })
        all_day_productivity_per_day_2.append({
            'id': i.id,
            'date': i.date,
            'total_coins': i.productivity_per_day,
        })
        all_day_total_players_2.append({
            'id': i.id,
            'date': i.date,
            'total_players': i.total_players,
        })
        all_day_total_traders_2.append({
            'id': i.id,
            'date': i.date,
            'total_traders': i.total_traders,
        })

    data = {
        'stats_first_team': {
            'id': season.first_team.id,
            'name': season.first_team.name,
            'total_coins': stats_for_first_team.total_coins,
            'productivity_per_day': stats_for_first_team.productivity_per_day,
            'total_players': stats_for_first_team.total_players,
            'total_traders': stats_for_first_team.total_traders,
            'all_day_total_coins': all_day_total_coins_1,
            'all_day_productivity_per_day': all_day_productivity_per_day_1,
            'all_day_total_players': all_day_total_players_1,
            'all_day_total_traders': all_day_total_traders_1,
        },
        'stats_second_team': {
            'id': season.second_team.id,
            'name': season.second_team.name,
            'total_coins': stats_for_second.total_coins,
            'productivity_per_day': stats_for_second.productivity_per_day,
            'total_players': stats_for_second.total_players,
            'total_traders': stats_for_second.total_traders,
            'all_day_total_coins': all_day_total_coins_2,
            'all_day_productivity_per_day': all_day_productivity_per_day_2,
            'all_day_total_players': all_day_total_players_2,
            'all_day_total_traders': all_day_total_traders_2,
        },
        'leaderboard_first_team': [{
            'id': user_balance.id,
            'tg_name': user_balance.user.tg_username,
            'tg_first_name': user_balance.user.tg_first_name,
            'tg_last_name': user_balance.user.tg_last_name,
            'earn': user_balance.earn_in_team_per_month,
            'precent': (user_balance.earn_in_team_per_month * 100) / season.first_team.money_team
            if season.first_team.money_team > 0 else 0,
            'position': idx + 1} for idx, user_balance in enumerate(total_players_1)
        ],
        'leaderboard_second_team': [{
            'id': user_balance.id,
            'tg_name': user_balance.user.tg_username,
            'tg_first_name': user_balance.user.tg_first_name,
            'tg_last_name': user_balance.user.tg_last_name,
            'earn': user_balance.earn_in_team_per_month,
            'precent': (user_balance.earn_in_team_per_month * 100) / season.second_team.money_team
            if season.second_team.money_team > 0 else 0,
            'position': idx + 1} for idx, user_balance in enumerate(total_players_2)
        ],
        'my_position': {
            'team_id': user_balance.team.id,
            'id': user_balance.id,
            'tg_name': user_balance.user.tg_username,
            'tg_first_name': user_balance.user.tg_first_name,
            'tg_last_name': user_balance.user.tg_last_name,
            'earn': user_balance.earn_in_team_per_month,
            'precent': (user_balance.earn_in_team_per_month * 100) / user_balance.team.money_team
            if user_balance.team.money_team > 0 else 0,
            'position': user_position
        },
    }
    return JsonResponse(data, safe=False, status=200)


@swagger_auto_schema(
    methods=(['GET']),
    responses={
        '404': get_response_examples({'Error': 'У вас нет команды'}),
        ' 404': get_response_examples({'Error': 'У вас нет монет для сбора'}),
        '200': get_response_examples({
            'nickname': 'dima',
            'balance': 120,
            'total_rewards': 2345,
            'received_coins_from_referrals': 111,
            'friends_are_inv': 2,
            'total_friends_earnings': 11111,
        }),
    },
    tags=['User'],
    operation_summary='Основная информация',

)
@api_view(["GET"])
@telegram_authenticated
@check_user_exists
async def info_person(request: HttpRequest, *args, **kwargs):
    user = kwargs.get('user')
    user_balance = kwargs.get('user_balance')
    user_stats = await UserStatistics.objects.filter(user=user).afirst()
    referrals = User.objects.filter(referrer=user)
    total_earnings = await sync_to_async(
        referrals.aggregate
    )(
        total_sum=Sum('user_balance__earn_in_team_per_all_time')
    )

    total_friends_earnings = total_earnings.get('total_sum') or 0
    data = {
        'nickname': user.tg_username,
        'balance': user_balance.game_coin,
        'total_rewards': user_balance.earn_in_team_per_all_time,
        'received_coins_from_referrals': user_stats.received_coins_from_ref,
        'friends_are_inv': user_stats.friends_are_inv,
        'total_friends_earnings': total_friends_earnings,
    }
    return JsonResponse(data, status=200)


@swagger_auto_schema(
    methods=(["POST"]),
    request_body=request_body.ChangeNickName,
    responses={
        '404': get_response_examples({'Error': 'Данные не переданы'}),
        '404 ': get_response_examples({'Error': 'Данное имя уже занято'}),
        '200': get_response_examples({'Info': 'NickName успешно заменен'}),
    },
    tags=['User'],
    operation_summary='Замена NickName'
)
@api_view(["POST"])
@telegram_authenticated
@check_user_exists
async def change_nickname(request: HttpRequest, *args, **kwargs):
    nickname = request.data['nickname']
    user = kwargs.get('user')
    exist_user = await User.objects.filter(tg_username__iexact=nickname).afirst()
    if exist_user:
        return JsonResponse({'Error': 'Данное имя уже занято'}, status=404)
    if not nickname:
        return JsonResponse({'Error': 'Данные не переданы'}, status=404)

    user.tg_username = nickname
    await user.asave()

    return JsonResponse({'Info': 'NickName успешно заменен'}, status=200)


@swagger_auto_schema(
    methods=(['GET']),
    responses={
        '200': get_response_examples({'invite_link': 'https://gfdgsdfgdsaf?start=id_1241'}),
    },
    tags=['User'],
    operation_summary='Получить реферальную ссылку',

)
@api_view(["GET"])
@telegram_authenticated
@check_user_exists
async def get_invite_link(request: HttpRequest, *args, **kwargs):
    user = kwargs.get('user')
    user_balance = kwargs.get('user_balance')
    user_balance.count_of_share_invite_link += 1
    await user_balance.asave()
    return JsonResponse({'invite_link': f"{os.getenv('BOT_LINK')}?start=id_{user.tg_id}"}, status=200)


@swagger_auto_schema(
    methods=(['GET']),
    responses={
        '404': get_response_examples({'Error':'Пользователь не закончил онбординг'}),
        ' 404': get_response_examples(),
        '200': get_response_examples({
            "tg_username": "dimon_frolkov",
                "Invited": 3,
                "Active": 2,
                "Volume_Stars": 1000.0,
                "Earned": 300.0,
            "Layer_1": [
                {
                    "tg_username": "Dima_Tolshin",
                    "Invited": 1,
                    "Active": 1,
                    "Volume_Stars": 500.0,
                    "Earned": 300.0
                }
    ],
            "Layer_2": [
                {
                    "tg_username": "Traher",
                    "Invited": 0,
                    "Active": 0,
                    "Volume_Stars": 400.0,
                    "Earned": 400.0
                }
            ],
            "Layer_3": [],
            "Layer_4": [],
            "Layer_5": [],
            "Counts": {
                "Layer_1": 1,
                "Layer_2": 1,
                "Layer_3": 0,
                "Layer_4": 0,
                "Layer_5": 0
            }
                }),
            },
    tags=['User'],
    operation_summary='Сообщество',

)
@api_view(["GET"])
@telegram_authenticated
@check_user_exists
async def get_my_community(request: HttpRequest, *args, **kwargs):
    user = kwargs.get('user')
    user_balance = kwargs.get('user_balance')
    if not user or not user_balance:
        return JsonResponse({'Error':'Пользователь не закончил онбординг'},status=404)

    data = {
        'tg_username': user.tg_username,
        'Invited': user_balance.count_of_share_invite_link,
        'Active': user_balance.count_of_friends,
        'Volume_Stars': user_balance.token_money,
        'Earned': user_balance.token_money - user_balance.money_which_i_donate,
    }

    layers, counts, total_volume, total_earned = await get_user_referral_layers(user)
    data.update(layers)
    data['Counts'] = counts
    data['total_volume'] = total_volume
    data['total_earned'] = total_earned

    return JsonResponse(data,status=200)
