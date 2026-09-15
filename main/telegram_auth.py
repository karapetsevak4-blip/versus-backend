"""Telegram's bot-token HMAC protocol, with strict parsing and bounded freshness."""
import hashlib
import hmac
import json
import re
import time
from urllib.parse import parse_qsl


def validate_init_data(raw, token, max_age, *, now=None):
    # Decode each value exactly once. Unquoting the whole query first corrupts
    # names containing &, = or +. Duplicate keys make identity ambiguous.
    if not isinstance(raw, str) or not raw or len(raw) > 16384:
        raise ValueError('Invalid Telegram data')
    if re.search(r'%(?![0-9a-fA-F]{2})', raw):
        raise ValueError('Invalid Telegram data')
    pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True,
                      encoding='utf-8', errors='strict', max_num_fields=32)
    data = dict(pairs)
    if len(data) != len(pairs) or not all(data):
        raise ValueError('Ambiguous Telegram data')
    digest = data.pop('hash', '')
    if not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('Invalid Telegram signature')
    check = '\n'.join(f'{key}={value}' for key, value in sorted(data.items()))
    secret = hmac.digest(b'WebAppData', token.encode(), 'sha256')
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, digest):
        raise ValueError('Invalid Telegram signature')

    auth_date = data.get('auth_date', '')
    if not re.fullmatch('[0-9]{1,12}', auth_date):
        raise ValueError('Invalid Telegram timestamp')
    timestamp = int(auth_date)
    current = int(time.time()) if now is None else now
    if timestamp > current + 30 or current - timestamp > max_age:
        raise ValueError('Expired Telegram data')
    user = json.loads(data.get('user', 'null'))
    if (not isinstance(user, dict) or type(user.get('id')) is not int
            or not 0 < user['id'] < 2**52
            or not isinstance(user.get('first_name'), str)):
        raise ValueError('Invalid Telegram user')
    for field in ('last_name', 'username', 'photo_url'):
        if field in user and not isinstance(user[field], str):
            raise ValueError('Invalid Telegram user')
    if 'is_premium' in user and type(user['is_premium']) is not bool:
        raise ValueError('Invalid Telegram user')
    return {'user': user, 'auth_date': timestamp, 'hash': digest}
