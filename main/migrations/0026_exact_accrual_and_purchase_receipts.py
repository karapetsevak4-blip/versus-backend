import django.db.models.deletion
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [('main', '0025_test_catalog_precision')]
    operations = [
        migrations.AddField(
            model_name='userbalance', name='accrual_updated_at',
            field=models.DateTimeField(blank=True, null=True)),
        migrations.AlterField(
            model_name='userbalance', name='accrual_updated_at',
            field=models.DateTimeField(blank=True, null=True, default=django.utils.timezone.now)),
        migrations.AddField(
            model_name='userbalance', name='accrual_remainder_numerator',
            field=models.CharField(default='0', max_length=120)),
        migrations.AddField(
            model_name='userbalance', name='accrual_remainder_denominator',
            field=models.CharField(default='1', max_length=120)),
        migrations.CreateModel(
            name='PurchaseReceipt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=128)),
                ('signature', models.CharField(max_length=100)),
                ('result', models.JSONField()),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name='purchase_receipts', to='main.user')),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('user', 'key'), name='unique_player_purchase_key')]},
        ),
    ]
