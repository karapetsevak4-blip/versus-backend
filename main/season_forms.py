from datetime import timedelta

from django import forms

from .models import Season


class SeasonAdminForm(forms.ModelForm):
    # Store the exact interval in the existing start/finish columns, avoiding
    # a second, potentially conflicting source for the season end time.
    duration_days = forms.FloatField(
        label='Длительность сезона, дней', initial=14, min_value=1,
        help_text='По умолчанию 14 дней. Окончание = начало + длительность.',
    )

    class Meta:
        model = Season
        fields = '__all__'
        exclude = ('finish_time',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.start_time and self.instance.finish_time:
            self.initial['duration_days'] = (
                self.instance.finish_time - self.instance.start_time
            ).total_seconds() / 86400

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_time')
        days = cleaned.get('duration_days')
        if start is not None and days is not None:
            try:
                self.instance.finish_time = start + timedelta(days=days)
            except (OverflowError, ValueError):
                self.add_error('duration_days', 'Недопустимая длительность сезона.')
        return cleaned
