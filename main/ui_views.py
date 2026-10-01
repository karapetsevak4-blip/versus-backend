from adrf.decorators import api_view
from asgiref.sync import sync_to_async
from django.http import JsonResponse
from .my_decor import telegram_authenticated, check_user_exists
from . import ui_state, gameplay
from .input_validation import positive_integer


@api_view(['GET', 'POST'])
@telegram_authenticated
@check_user_exists
async def player_ui(request, *args, **kwargs):
    try:
        if request.method == 'POST':
            result = await sync_to_async(ui_state.guide)(kwargs['user'].pk, request.data)
        else:
            result = await sync_to_async(ui_state.presentation)(kwargs['user'].pk)
        return JsonResponse(result)
    except gameplay.GameplayError as exc:
        return JsonResponse({'Error': str(exc)}, status=exc.status)


@api_view(['GET', 'POST'])
@telegram_authenticated
@check_user_exists
async def tasks_ui(request, *args, **kwargs):
    try:
        if request.method == 'POST':
            result = await sync_to_async(ui_state.claim_task)(kwargs['user'].pk, positive_integer(request.data.get('reward_id')))
        else:
            result = await sync_to_async(ui_state.tasks)(kwargs['user'].pk)
        return JsonResponse(result)
    except ValueError:
        return JsonResponse({'Error': 'Invalid reward ID'}, status=400)
    except gameplay.GameplayError as exc:
        return JsonResponse({'Error': str(exc)}, status=exc.status)


@api_view(['GET'])
@telegram_authenticated
@check_user_exists
async def history_ui(request, *args, **kwargs):
    return JsonResponse(await sync_to_async(ui_state.history)(kwargs['user'].pk))


@api_view(['GET'])
@telegram_authenticated
@check_user_exists
async def community_ui(request, *args, **kwargs):
    return JsonResponse(await sync_to_async(ui_state.community)(kwargs['user'].pk))
