from adrf.decorators import api_view
from asgiref.sync import sync_to_async
from django.db.models import Sum, F
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
from . import gameplay, registration
from .test_mode import require_financial_operations, initial_test_balance


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
    data = await create_session(request)
    if isinstance(data, JsonResponse):
        return data
    try:
        await sync_to_async(registration.register_player)(data['user'], request.GET.get('refer_id'))
    except registration.PlayerError as exc:
        return JsonResponse({'detail': str(exc), 'code': exc.code}, status=exc.status)
    await establish_session(request, data)
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
    try:
        team_id = positive_integer(request.data.get('team_id'))
        await sync_to_async(gameplay.choose_team)(kwargs['user'].pk, team_id)
    except ValueError:
        return JsonResponse({'Error': 'Invalid team ID'}, status=400)
    except gameplay.GameplayError as exc:
        return JsonResponse({'Error': str(exc)}, status=exc.status)
    return JsonResponse({'Info': 'Success'})

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
    try:
        data = await sync_to_async(gameplay.main_snapshot)(kwargs['user'].pk)
    except gameplay.GameplayError as exc:
        return JsonResponse({'Error': str(exc)}, status=exc.status)
    response = JsonResponse(data)
    response['Cache-Control'] = 'no-store'
    return response

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
    require_financial_operations()
    try:
        await sync_to_async(registration.change_wallet)(kwargs['user'].pk, request.data.get('wallet'))
    except registration.PlayerError as exc:
        return JsonResponse({'Error': str(exc), 'code': exc.code}, status=exc.status)
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
    # D02 contribution transfer/rounding is unresolved. The legacy paid path
    # also references a nonexistent field. Do not let it bypass game locks or
    # activate an unapproved economic rule while the replacement is prepared.
    return JsonResponse({
        'Error': 'Смена команды пока недоступна: правила переноса вклада ещё не утверждены',
        'code': 'team_switch_rules_pending',
    }, status=409)


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
    try:
        data = await sync_to_async(gameplay.office_snapshot)(kwargs['user'].pk)
    except gameplay.GameplayError as exc:
        return JsonResponse({'Error': str(exc)}, status=exc.status)
    response = JsonResponse(data)
    response['Cache-Control'] = 'no-store'
    return response

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
    try:
        first = positive_integer(request.data.get('first_user_id_trader'))
        second = request.data.get('second_user_id_trader')
        if second is not None:
            second = positive_integer(second)
        await sync_to_async(gameplay.place_trader)(kwargs['user'].pk, first, second)
    except ValueError:
        return JsonResponse({'Error': 'Invalid trader ID'}, status=400)
    except gameplay.GameplayError as exc:
        return JsonResponse({'Error': str(exc)}, status=exc.status)
    return JsonResponse({'Info': 'Success'})

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
    try:
        amount = await sync_to_async(gameplay.claim)(kwargs['user'].pk)
    except gameplay.GameplayError as exc:
        return JsonResponse({'Error': str(exc)}, status=exc.status)
    return JsonResponse({'Info': 'Операция прошла успешно', 'claimed': amount})

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
    require_financial_operations()
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
    try:
        count = positive_integer(request.data.get('count', 1))
        product_id = positive_integer(request.data.get('id_products'))
        model = request.data.get('model')
        if not isinstance(model, str):
            raise ValueError('Invalid product model')
        result = await sync_to_async(gameplay.purchase)(
            kwargs['user'].pk, model.lower(), product_id, count,
            idempotency_key=request.headers.get('Idempotency-Key'))
    except ValueError:
        return JsonResponse({'Error': 'Invalid quantity or product ID'}, status=400)
    except gameplay.GameplayError as exc:
        return JsonResponse({'Error': str(exc)}, status=exc.status)
    return JsonResponse(result)

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
    from .team_stats import team_snapshot
    try:
        data = await sync_to_async(team_snapshot)(kwargs['user'].pk)
    except gameplay.GameplayError as exc:
        return JsonResponse({'Error': str(exc)}, status=exc.status)
    return JsonResponse(data, status=200)


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
    try:
        await sync_to_async(registration.change_nickname)(kwargs['user'].pk, request.data.get('nickname'))
    except registration.PlayerError as exc:
        return JsonResponse({'Error': str(exc), 'code': exc.code}, status=exc.status)
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
    await UserBalance.objects.filter(pk=user_balance.pk).aupdate(
        count_of_share_invite_link=F('count_of_share_invite_link') + 1)
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
