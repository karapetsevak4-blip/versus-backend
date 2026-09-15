from zoneinfo import ZoneInfo
from django.conf import settings
from django.db.backends.sqlite3.operations import DatabaseOperations as SQLiteOperations
from django.utils import timezone


class DatabaseOperations(SQLiteOperations):
    def adapt_datetimefield_value(self, value):
        # Original models return aware Moscow dates with USE_TZ=False.
        # Keep equivalent wall time for offline tests, not a timezone migration.
        if value is not None and not settings.USE_TZ and timezone.is_aware(value):
            value = timezone.make_naive(value, ZoneInfo(settings.TIME_ZONE))
        return super().adapt_datetimefield_value(value)
