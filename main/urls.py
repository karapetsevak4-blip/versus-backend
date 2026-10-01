from django.urls import path
from .views import *
from . import ui_views

urlpatterns = [
    path('player_ui/', ui_views.player_ui),
    path('tasks_ui/', ui_views.tasks_ui),
    path('history_ui/', ui_views.history_ui),
    path('community_ui/', ui_views.community_ui),
    path('create_session/',create_my_session),
    path('main_page/',main_page),
    path('onboarding_apply_team/',onboarding_apply_team),
    path('apply_wallet/',apply_wallet),
    path('change_team/',change_team),
    path('my_ofice/',my_ofice),
    path('apply_traders_in_ofice/', apply_traders_in_ofice),
    path('claim_bank/',claim_bank),
    path('get_shop/',get_shop),
    path('buy_something/',buy_something),
    path('get_data_team/',get_data_team),
    path('info_person/',info_person),
    path('change_nickname/',change_nickname),
    path('get_invite_link/',get_invite_link),
    path('get_my_community/',get_my_community),




]
