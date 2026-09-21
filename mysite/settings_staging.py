"""Closed test deployment; never use settings_test on a deployed server."""
from .settings import *  # noqa: F403
from django.core.exceptions import ImproperlyConfigured


def required_secret(name):
    path = os.getenv(name + '_FILE')
    try:
        value = Path(path).read_text().strip() if path else os.getenv(name, '').strip()
    except OSError:
        raise ImproperlyConfigured(f'Cannot read {name} secret file') from None
    if not value:
        raise ImproperlyConfigured(f'{name} is required for staging')
    return value


# These restrictions cannot be switched off via environment variables.
CLOSED_TEST_MODE = True
DEBUG = False
try:
    TELEGRAM_TESTER_IDS = frozenset(int(v.strip()) for v in
                                  os.environ['TELEGRAM_TESTER_IDS'].split(','))
    TELEGRAM_TEST_BOT_ID = int(os.environ['TELEGRAM_TEST_BOT_ID'])
except (KeyError, ValueError):
    raise ImproperlyConfigured('Explicit numeric tester IDs and test bot ID are required') from None
if not TELEGRAM_TESTER_IDS or min(TELEGRAM_TESTER_IDS) <= 0 or TELEGRAM_TEST_BOT_ID <= 0:
    raise ImproperlyConfigured('Tester IDs and test bot ID must be positive')

# Explicitly selected testers receive funds only at account creation.
try:
    FUNDED_TESTER_IDS = frozenset(int(v.strip()) for v in
        os.getenv('FUNDED_TESTER_IDS', os.getenv('FUNDED_TESTER_ID', '')).split(',')
        if v.strip())
except ValueError:
    raise ImproperlyConfigured('FUNDED_TESTER_IDS must be numeric') from None
if not FUNDED_TESTER_IDS.issubset(TELEGRAM_TESTER_IDS):
    raise ImproperlyConfigured('Funded testers must be in the tester allowlist')

SECRET_KEY = required_secret('SECRET_KEY')
if len(SECRET_KEY) < 50:
    raise ImproperlyConfigured('Use a random staging SECRET_KEY of at least 50 characters')
TELEGRAM_BOT_TOKEN = required_secret('TELEGRAM_TOKEN')
if TELEGRAM_BOT_TOKEN.split(':', 1)[0] != str(TELEGRAM_TEST_BOT_ID):
    raise ImproperlyConfigured('Token does not belong to the configured test bot')

ALLOWED_HOSTS = ['test.versuschain.com', '127.0.0.1', 'localhost']
CORS_ALLOWED_ORIGINS = ['https://test.versuschain.com']
CSRF_TRUSTED_ORIGINS = ['https://test.versuschain.com']
SESSION_COOKIE_NAME = '__Host-versus_test_session'
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_DOMAIN = None
CSRF_COOKIE_NAME = '__Host-versus_test_csrf'
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_DOMAIN = None
SECURE_CONTENT_TYPE_NOSNIFF = True
# Set by the dedicated proxy; backend port must never be exposed publicly.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r'^healthz/$']
ROOT_URLCONF = 'mysite.urls_staging'

DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': 'versus_test', 'USER': 'versus_test', 'HOST': 'db', 'PORT': 5432,
    'PASSWORD': required_secret('POSTGRES_PASSWORD'),
}}
CELERY_BROKER_URL = 'redis://redis:6379/0'
CELERY_BEAT_SCHEDULE = {}
