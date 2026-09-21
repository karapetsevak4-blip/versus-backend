"""Only the authenticated API and a minimal liveness endpoint are exposed."""
from django.http import JsonResponse
from django.urls import include, path


def health(request):
    return JsonResponse({'status': 'ok'})


urlpatterns = [
    path('api/', include('main.urls')),
    path('healthz/', health),
]
