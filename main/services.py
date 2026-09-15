import urllib.parse
from django.http import JsonResponse
import os
import django
import json
import time
from django.conf import settings
from .telegram_auth import validate_init_data

from .models import *

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')


file_path_upgrade = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'DataJson', 'upgrade_car.json')


async def create_session(request):
    init_data = request.headers.get("Authorization")
    # Fail closed and remove any older identity before trying a new login.
    for key in ('telegram_hash', 'telegram_user', 'telegram_verified', 'telegram_expires_at'):
        await request.session.apop(key, None)
    if not settings.TELEGRAM_BOT_TOKEN:
        return JsonResponse({'detail': 'Telegram login is not configured'}, status=503)
    try:
        data = validate_init_data(init_data, settings.TELEGRAM_BOT_TOKEN,
                                  settings.TELEGRAM_INIT_DATA_MAX_AGE)
    except (ValueError, UnicodeError):
        return JsonResponse({'detail': 'Invalid or expired Telegram data'}, status=401)
    await request.session.acycle_key()
    await request.session.aset('telegram_hash', data['hash'])
    await request.session.aset('telegram_user', data['user'])
    await request.session.aset('telegram_verified', 1)
    expires_at = min(int(time.time()) + settings.SESSION_COOKIE_AGE,
                     data['auth_date'] + settings.TELEGRAM_INIT_DATA_MAX_AGE)
    await request.session.aset('telegram_expires_at', expires_at)
    await request.session.aset_expiry(max(1, expires_at - int(time.time())))


async def transform_init_data(init_data: str) -> dict:
    # Kept for existing callers; parsing must never be mistaken for verification.
    return validate_init_data(init_data, settings.TELEGRAM_BOT_TOKEN,
                              settings.TELEGRAM_INIT_DATA_MAX_AGE)


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
