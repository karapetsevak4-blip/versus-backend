# Versus backend

Django backend, Telegram bot, and background workers for the Versus Telegram
Mini App.

## Status

The current developer handoff is on `feat/current-game` (1 October 2026).
`main` preserves the original supplied code; `develop` retains the earlier
September integration checkpoint. See [DEVELOPER_HANDOFF.md](DEVELOPER_HANDOFF.md)
for the current source map, archive tags, verification and remaining work.
The application and payment paths are not production-ready.

## Stack

- Python 3.12 and Django 5.2.17
- Django REST Framework / ADRF
- PostgreSQL 15
- Redis and Celery
- aiogram Telegram bot

## Local verification

Create an isolated Python 3.12 environment and install the pinned application
requirements:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --requirement requirements.txt
.venv/bin/python manage.py test --settings=mysite.settings_test
.venv/bin/python manage.py check --settings=mysite.settings_test
.venv/bin/python manage.py makemigrations --check --dry-run --settings=mysite.settings_test
```

The test settings use an isolated in-memory database and fake Telegram values.
They do not verify PostgreSQL locking, Redis, Celery, Telegram, payments, or
production configuration.

## Configuration

Copy `.env.example` to `.env` and replace every placeholder locally. Never
commit `.env`. Important variables include database credentials, Django
`SECRET_KEY`, `TELEGRAM_TOKEN`, bot/frontend/backend URLs, allowed hosts, and
CORS origins.

The current Django production settings still contain legacy hardcoded origins,
and the supplied Compose file assumes an external network and sibling storage
directories. Do not treat either as a ready production configuration. The test
deployment must use a reviewed Compose override/configuration before startup.

## Initial data

An empty database requires at least the following product data before the user
journey can work:

1. office levels;
2. traders;
3. tasks;
4. currencies;
5. a season.

Values must come from the approved catalog and product decisions, not ad-hoc
developer defaults.

## Git workflow

See [CONTRIBUTING.md](CONTRIBUTING.md). Changes go through a short-lived branch
and a pull request into `develop`. A tested release is promoted from `develop`
to `main` and tagged. Database migrations must be included, reviewed, and tested
with every model change.

## Deployment

Staging deployment is not connected yet. It requires the reviewed container
stack, non-root deploy user, protected GitHub environment/secrets, health check,
database backup, and rollback command. Production deployment remains manual and
out of scope until the release candidate is accepted.
