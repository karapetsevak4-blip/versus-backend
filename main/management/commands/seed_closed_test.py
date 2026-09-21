"""Initialize the supplied v0.4 catalog in the closed test database only."""
from datetime import timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from main.models import Currency, Ofice, Traders, Team, Season, TeamStats
from main.test_mode import closed_test_mode


class Command(BaseCommand):
    help = 'Create v0.4 catalog and a zero-prize test season; never reset balances.'

    @transaction.atomic
    def handle(self, *args, **options):
        if not closed_test_mode():
            raise CommandError('Only available in closed test mode')
        credit, _ = Currency.objects.get_or_create(name='stars')
        Currency.objects.get_or_create(name='coin')
        for lvl, price, production in [(1,'5',20),(2,'7.5',35),(3,'12',60),(4,'20',110),(5,'35',220)]:
            values = dict(name=f'L{lvl}', price=Decimal(price), earn_for_day=production, currency=credit)
            row, created = Traders.objects.get_or_create(lvl=lvl, defaults=values)
            if not created and any(getattr(row,k) != v for k,v in values.items()):
                raise CommandError(f'Trader L{lvl} differs; existing data was not overwritten')
        for lvl, price, seats, comfort, base, per_seat in [
            (1,0,3,0,220,0), (2,15,5,0.05,650,0), (3,40,8,0.10,2200,0),
            (4,100,12,0.15,3500,0), (5,250,-1,0.20,2500,230),
        ]:
            values = dict(price=price, count_of_traders=seats, comfort=comfort,
                          safe_capacity=base, safe_capacity_per_trader=per_seat, currency=credit)
            row, created = Ofice.objects.get_or_create(lvl=lvl, defaults=values)
            if not created and any(getattr(row,k) != v for k,v in values.items()):
                raise CommandError(f'Office L{lvl} differs; existing data was not overwritten')
        if not Season.objects.exists():
            if Team.objects.exists():
                raise CommandError('Existing teams require review before creating test season')
            first = Team.objects.create(name='Test Team 1')
            second = Team.objects.create(name='Test Team 2')
            now = timezone.now()
            season = Season.objects.create(first_team=first, second_team=second, start_time=now,
                finish_time=now+timedelta(days=14), active=True, prize=0)
            for team in (first, second):
                TeamStats.objects.create(team=team, season=season)
        self.stdout.write('OK: test catalog ready; player balances were not changed.')
