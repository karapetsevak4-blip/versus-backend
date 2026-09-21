"""Local fixture issuer is never included in the production/staging URLconfs."""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from django.conf import settings
from django.http import JsonResponse
from django.urls import include, path
from django.views.decorators.http import require_GET
from .urls_staging import health


@require_GET
def local_fixture(request):
    if (not getattr(settings, 'LOCAL_GAME_MODE', False)
            or not getattr(settings, 'CLOSED_TEST_MODE', False)
            or request.META.get('REMOTE_ADDR') not in {'127.0.0.1', '::1'}):
        return JsonResponse({'error': 'Local preview is unavailable'}, status=404)
    players = {'910001': 'Local Player One', '910002': 'Local Player Two'}
    selected = request.GET.get('player', '910001')
    if selected not in players:
        return JsonResponse({'error': 'Unknown synthetic player'}, status=400)
    payload = {
        'user': json.dumps({'id': int(selected), 'first_name': players[selected],
                            'username': 'versus_local_' + selected}),
        'auth_date': str(int(time.time())),
        'query_id': 'local-preview-only',
    }
    check = '\n'.join(f'{key}={value}' for key, value in sorted(payload.items()))
    secret = hmac.digest(b'WebAppData', settings.TELEGRAM_BOT_TOKEN.encode(), 'sha256')
    payload['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    response = JsonResponse({'init_data': urlencode(payload), 'player_id': int(selected),
                             'label': players[selected]})
    response['Cache-Control'] = 'no-store'
    return response


urlpatterns = [
    path('api/local_fixture/', local_fixture),
    path('api/', include('main.urls')),
    path('healthz/', health),
]
