from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('main', '0027_unique_telegram_identity')]

    operations = [
        # Legacy duplicates are retained verbatim with NULL snapshot_day.
        # Only newly observed UTC days participate in the canonical identity.
        migrations.AddField(
            model_name='teamstats', name='snapshot_day',
            field=models.DateField(blank=True, null=True)),
        migrations.AlterField(
            model_name='teamstats', name='total_coins',
            field=models.BigIntegerField(default=0)),
        migrations.AddConstraint(
            model_name='teamstats',
            constraint=models.UniqueConstraint(
                fields=('season', 'team', 'snapshot_day'), name='unique_team_season_utc_day')),
    ]
