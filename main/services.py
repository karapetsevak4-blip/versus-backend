import urllib.parse
from django.http import JsonResponse
import os
import django
import json

from .models import *

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')


file_path_upgrade = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'DataJson', 'upgrade_car.json')


async def create_session(request):
    init_data = request.headers.get("Authorization")

    if not init_data:
        return JsonResponse({"detail": "Missing Telegram Init Data"}, status=400)

    try:
        init_data_dict = await transform_init_data(init_data)
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)

    if len(init_data_dict.get("hash")) != 64:
        return JsonResponse({"detail": "Missing Telegram Init Data"}, status=400)

    # Сохраняем хэш и данные пользователя в сессии
    request.session["telegram_hash"] = init_data_dict.get("hash")
    request.session["telegram_user"] = init_data_dict.get("user", {})


async def transform_init_data(init_data: str) -> dict:
    try:
        decoded_data = urllib.parse.unquote(init_data)
        data = {k: v for k, v in (pair.split('=') for pair in decoded_data.split('&'))}
        data['user'] = json.loads(data['user'])
        return data
    except Exception as e:
        raise ValueError(f"Invalid Telegram Init Data format: {str(e)}")


async def get_user_referral_layers(user):
    layers = {
        'Layer_1': [],
        'Layer_2': [],
        'Layer_3': [],
        'Layer_4': [],
        'Layer_5': [],
    }

    counts = {
        'Layer_1': 0,
        'Layer_2': 0,
        'Layer_3': 0,
        'Layer_4': 0,
        'Layer_5': 0,
    }
    total_volume = {
        'Layer_1': 0,
        'Layer_2': 0,
        'Layer_3': 0,
        'Layer_4': 0,
        'Layer_5': 0,
    }
    total_earned = {
        'Layer_1': 0,
        'Layer_2': 0,
        'Layer_3': 0,
        'Layer_4': 0,
        'Layer_5': 0,
    }

    current_level_users = [user]

    for level in range(1, 6):
        if not current_level_users:
            # слой будет пустой, count уже 0
            continue

        qs = User.objects.filter(
            referrer__in=current_level_users
        ).select_related('user_balance')

        next_level_users = []
        level_volume = 0
        level_earned = 0

        async for u in qs:
            ub = u.user_balance

            # Расчет для каждого пользователя
            volume = ub.token_money if ub else 0
            earned = (ub.token_money - ub.money_which_i_donate) if ub else 0

            layers[f'Layer_{level}'].append({
                'tg_username': u.tg_username,
                'Invited': ub.count_of_share_invite_link if ub else 0,
                'Active': ub.count_of_friends if ub else 0,
                'Volume_Stars': volume,
                'Earned': earned
            })

            level_volume += volume
            level_earned += earned

            next_level_users.append(u)

        counts[f'Layer_{level}'] = len(layers[f'Layer_{level}'])
        total_volume[f'Layer_{level}'] = level_volume
        total_earned[f'Layer_{level}'] = level_earned

        current_level_users = next_level_users

    return layers, counts, total_volume, total_earned