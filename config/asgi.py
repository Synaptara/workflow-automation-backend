import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import OriginValidator
from django.conf import settings

from workflows.channels_auth import JWTAuthMiddleware
from workflows.routing import websocket_urlpatterns

allowed_origins = list(getattr(settings, "CORS_ALLOWED_ORIGINS", []))
if settings.DEBUG:
    allowed_origins += ["http://localhost:5173", "http://127.0.0.1:5173"]

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": OriginValidator(
            JWTAuthMiddleware(URLRouter(websocket_urlpatterns)),
            allowed_origins,
        ),
    }
)
