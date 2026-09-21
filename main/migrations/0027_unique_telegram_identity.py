from django.db import migrations, models
from django.db.models import Count


def reject_duplicate_telegram_ids(apps, schema_editor):
    users = apps.get_model('main', 'User').objects.using(schema_editor.connection.alias)
    duplicates = users.values('tg_id').annotate(rows=Count('pk')).filter(rows__gt=1).count()
    if duplicates:
        # Report only the count, not Telegram identifiers/personal data.
        raise RuntimeError(
            f'Cannot enforce unique Telegram identity: {duplicates} duplicate tg_id group(s). '
            'No players were merged or deleted. Review their balances, property and referrals '
            'and prepare an explicit data repair before retrying migration 0027.')


class Migration(migrations.Migration):
    dependencies = [('main', '0026_exact_accrual_and_purchase_receipts')]
    operations = [
        migrations.RunPython(reject_duplicate_telegram_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='user', name='tg_id',
            field=models.BigIntegerField(unique=True, verbose_name='Телеграм Ид')),
    ]
