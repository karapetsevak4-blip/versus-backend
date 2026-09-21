"""Disposable PostgreSQL regression tests. No real Telegram or payment access."""
from .settings_test import *  # noqa: F403
from .local_runtime import database

DATABASES = {'default': database()}
TIME_ZONE = 'UTC'
USE_TZ = True
CELERY_TIMEZONE = 'UTC'
