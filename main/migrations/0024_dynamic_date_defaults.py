import datetime
import main.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('main', '0023_userbalance_count_of_friends_and_more')]
    operations = [
        migrations.AlterField(
            model_name='user', name='last_visit',
            field=models.DateField(default=datetime.date.today, verbose_name='Дата последнего входа'),
        ),
        migrations.AlterField(
            model_name='teamstats', name='date',
            field=models.DateTimeField(default=main.models.get_moscow_time),
        ),
    ]
