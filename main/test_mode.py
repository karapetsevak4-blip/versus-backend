"""Server-side restrictions for the isolated, non-financial test deployment."""
from django.conf import settings
from django.core.exceptions import PermissionDenied


def closed_test_mode():
    return getattr(settings, 'CLOSED_TEST_MODE', False)


def telegram_user_allowed(user_id):
    if not closed_test_mode():
        return True
    return (type(user_id) is int and user_id > 0
            and user_id in getattr(settings, 'TELEGRAM_TESTER_IDS', ()))


def require_financial_operations():
    if closed_test_mode():
        raise PermissionDenied('Financial operations are disabled in this test environment')


def initial_test_balance(user_id):
    """Owner-approved grant at account creation only; never refill on login."""
    if (closed_test_mode() and telegram_user_allowed(user_id)
            and user_id in getattr(settings, 'FUNDED_TESTER_IDS',
                                   (getattr(settings, 'FUNDED_TESTER_ID', None),))):
        return {'game_coin': 10000, 'token_money': 1000}
    return {}
