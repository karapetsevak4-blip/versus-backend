"""Paths for the isolated developer database; never imported by production."""
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


WORKSPACE = Path(__file__).resolve().parents[3]
RUNTIME = WORKSPACE / '.local'


def database():
    password_file = RUNTIME / 'run' / 'pg-password'
    if not password_file.is_file():
        raise ImproperlyConfigured('Initialize the isolated local PostgreSQL runtime first')
    return {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'versus_local',
        'USER': 'versus_local',
        'PASSWORD': password_file.read_text().strip(),
        'HOST': str(RUNTIME / 'run'),
        'PORT': '55432',
        'TEST': {'NAME': 'test_versus_local'},
    }
