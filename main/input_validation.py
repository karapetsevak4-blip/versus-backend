import re


def positive_integer(value):
    """Reject booleans, fractions and coercions; keep decimal form IDs compatible."""
    if type(value) is int and 0 < value <= 2**63 - 1:
        return value
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,19}', value):
        parsed = int(value)
        if 0 < parsed <= 2**63 - 1:
            return parsed
    raise ValueError('Expected a positive integer')
