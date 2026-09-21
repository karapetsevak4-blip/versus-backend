"""One season selection rule for reads and gameplay, without performing rollover."""
from datetime import timezone as datetime_timezone

from django.utils import timezone

from .models import Season


def relevant_season(at):
    # Prefer an enabled, started season. Keep the latest started season visible
    # after it is disabled; future configuration must never replace today's UI.
    return (Season.objects.filter(start_time__lte=at)
            .select_related('first_team', 'second_team')
            .order_by('-active', '-start_time', '-pk').first())


def utc_day(at):
    if timezone.is_naive(at):
        at = timezone.make_aware(at, timezone.get_default_timezone())
    return at.astimezone(datetime_timezone.utc).date()
