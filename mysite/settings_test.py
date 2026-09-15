"""Offline regression tests only; not a deployment or PostgreSQL substitute."""
from .settings import *  # noqa: F403

SECRET_KEY = 'versus-offline-tests-only-not-a-deployment-secret'
TELEGRAM_BOT_TOKEN = '123456789:OFFLINE_TEST_TOKEN_NOT_REAL'
DEBUG = False
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']
DATABASES = {'default': {'ENGINE': 'mysite.testing_sqlite', 'NAME': ':memory:'}}
CELERY_BROKER_URL = 'memory://'
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
