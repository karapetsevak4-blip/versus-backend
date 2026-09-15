from datetime import timedelta
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.test import TestCase, RequestFactory
from django.utils import timezone

from .admin import SeasonAdmin
from .models import Season, Team, User, UserBalance
from .season_forms import SeasonAdminForm
from .tasks import finish_season


class SeasonConfigurationTests(TestCase):
    def setUp(self):
        self.start = timezone.now().replace(microsecond=0)
        self.a = Team.objects.create(name='Bulls', money_team=100)
        self.b = Team.objects.create(name='Bears', money_team=50)

    def form_data(self, days=14):
        return {'start_time': self.start, 'duration_days': days,
                'first_team': self.a.pk, 'second_team': self.b.pk,
                'prize': 0, 'active': True}

    def test_default_is_fourteen_days(self):
        self.assertEqual(SeasonAdminForm.base_fields['duration_days'].initial, 14)
        form = SeasonAdminForm(data=self.form_data())
        self.assertTrue(form.is_valid(), form.errors)
        season = form.save()
        self.assertEqual(season.finish_time, self.start + timedelta(days=14))

    def test_custom_duration_and_reload(self):
        form = SeasonAdminForm(data=self.form_data(days=21))
        self.assertTrue(form.is_valid(), form.errors)
        season = form.save()
        season.refresh_from_db()
        self.assertEqual(SeasonAdminForm(instance=season).initial['duration_days'], 21)
        changed = SeasonAdminForm(data=self.form_data(days=10), instance=season)
        self.assertTrue(changed.is_valid(), changed.errors)
        changed.save()
        season.refresh_from_db()
        self.assertEqual(season.finish_time, self.start + timedelta(days=10))

    def test_bad_durations_rejected(self):
        for days in (0, -1, 'wrong', 'inf', 'nan', 1e100):
            with self.subTest(days=days):
                self.assertFalse(SeasonAdminForm(data=self.form_data(days)).is_valid())

    def test_admin_edit_preserves_progress_and_reschedules_after_commit(self):
        season = Season.objects.create(start_time=self.start,
                    finish_time=self.start + timedelta(days=14),
                    first_team=self.a, second_team=self.b, active=True)
        player = User.objects.create(tg_id=900000020)
        balance = UserBalance.objects.create(user=player, team=self.a,
                        earn_in_team_per_month=100, earn_in_team_per_weak=20, game_coin=70)
        form = SeasonAdminForm(data=self.form_data(days=21), instance=season)
        self.assertTrue(form.is_valid(), form.errors)
        obj = form.save(commit=False)
        model_admin = SeasonAdmin(Season, AdminSite())
        with patch('main.admin.finish_season.apply_async') as queued:
            with self.captureOnCommitCallbacks(execute=True):
                model_admin.save_model(RequestFactory().post('/admin/'), obj, form, change=True)
                queued.assert_not_called()
            queued.assert_called_once()
            self.assertEqual(queued.call_args.kwargs['args'], [season.pk])
        balance.refresh_from_db()
        self.a.refresh_from_db()
        self.assertEqual((balance.team_id, balance.earn_in_team_per_month,
                          balance.earn_in_team_per_weak, balance.game_coin),
                         (self.a.pk, 100, 20, 70))
        self.assertEqual(self.a.money_team, 100)

    def test_old_job_does_not_finish_extended_season(self):
        season = Season.objects.create(start_time=self.start,
                    finish_time=self.start + timedelta(days=14),
                    first_team=self.a, second_team=self.b, active=True)
        finish_season(season.pk)
        season.refresh_from_db()
        self.assertTrue(season.active)
        self.assertIsNone(season.winner_id)
