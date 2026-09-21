"""Explicit loopback-only developer environment with synthetic identities.

Start with VERSUS_LOCAL_MODE=1 and bind the API to 127.0.0.1, never 0.0.0.0.
Production and staging do not import this module or the fixture URLconf.
"""
from .settings import *  # noqa: F403
from django.core.exceptions import ImproperlyConfigured
from .local_runtime import RUNTIME, database

if os.environ.get('VERSUS_LOCAL_MODE') != '1':
    raise ImproperlyConfigured('Local preview requires VERSUS_LOCAL_MODE=1')

LOCAL_GAME_MODE = True
CLOSED_TEST_MODE = True
DEBUG = False
SECRET_KEY = 'versus-isolated-local-preview-only-never-a-deployment-secret'
TELEGRAM_BOT_TOKEN = '999999999:LOCAL_SYNTHETIC_TOKEN_NOT_A_REAL_BOT'
TELEGRAM_TEST_BOT_ID = 999999999
TELEGRAM_TESTER_IDS = frozenset({910001, 910002})
FUNDED_TESTER_IDS = TELEGRAM_TESTER_IDS
ROOT_URLCONF = 'mysite.urls_local'
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'testserver']
CORS_ALLOWED_ORIGINS = ['http://127.0.0.1:5173', 'http://localhost:5173']
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS
SESSION_COOKIE_NAME = 'versus_local_session'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_NAME = 'versus_local_csrf'
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
TIME_ZONE = 'UTC'
USE_TZ = True
DATABASES = {'default': database()}
MEDIA_ROOT = RUNTIME / 'media'
STATIC_ROOT = RUNTIME / 'staticfiles'
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
CELERY_BROKER_URL = 'redis+socket://' + str(RUNTIME / 'run' / 'redis.sock') + '?virtual_host=0'
CELERY_TIMEZONE = 'UTC'
CELERY_BEAT_SCHEDULER = 'celery.beat:PersistentScheduler'
CELERY_TASK_DEFAULT_QUEUE = 'versus-local'
CELERY_BEAT_SCHEDULE = {
    # Shares the exact elapsed-time cursor with API operations. No payouts,
    # legacy boost changes or season-finishing tasks are scheduled here.
    'settle-local-balances': {
        'task': 'main.tasks.calculate_personal_money',
        'schedule': 60.0,
    },
}
