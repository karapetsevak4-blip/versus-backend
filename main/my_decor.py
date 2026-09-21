from functools import wraps
from django.http import JsonResponse
from .models import User, UserBalance
import time
from asgiref.sync import sync_to_async
from rest_framework.authentication import SessionAuthentication
from .test_mode import telegram_user_allowed


def telegram_authenticated(view_func):
    @wraps(view_func)
    async def _wrapped_view(request, *args, **kwargs):
        telegram_user = await request.session.aget('telegram_user')
        verified = await request.session.aget('telegram_verified')
        expires_at = await request.session.aget('telegram_expires_at', 0)
        if (verified != 1 or not isinstance(telegram_user, dict)
                or type(telegram_user.get('id')) is not int
                or not isinstance(expires_at, (int, float)) or expires_at <= time.time()):
            return JsonResponse({"detail": "Unauthorized"}, status=401)

        # Recheck every request so removing a tester also revokes existing sessions.
        if not telegram_user_allowed(telegram_user['id']):
            await request.session.aflush()
            return JsonResponse({'detail': 'Access is limited to test participants'}, status=403)

        # DRF's default SessionAuthentication ignores our custom Telegram User.
        # Explicitly enforce Django CSRF checks for cookie-authenticated writes.
        await sync_to_async(SessionAuthentication().enforce_csrf)(request)

        # Добавляем данные Telegram в kwargs
        kwargs["telegram_user"] = telegram_user

        return await view_func(request, *args, **kwargs)

    return _wrapped_view


def check_user_exists(view_func):
    @wraps(view_func)
    async def _wrapped_view(request, *args, **kwargs):
        user = await User.objects.filter(tg_id=kwargs.get("telegram_user").get("id")).afirst()
        user_balance = await UserBalance.objects.filter(user=user).select_related('user', 'team',
                                                                                  'my_ofice__ofice').prefetch_related(
            'my_ofice__traders__trader__currency',
            'list_of_my_traders__trader__currency').afirst()
        if not user or user.is_baned == True:
            return JsonResponse({"Error": "User unexist"}, status=404)

        return await view_func(request, *args, **kwargs, user=user, user_balance=user_balance, )

    return _wrapped_view
