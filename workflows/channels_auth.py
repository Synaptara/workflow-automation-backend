from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken


@database_sync_to_async
def get_user_from_ticket(ticket):
    from django.contrib.auth.models import User

    cache_key = f"ws_ticket:{ticket}"
    user_id = cache.get(cache_key)
    if not user_id:
        return AnonymousUser()

    # Single-use: delete ticket immediately upon verification
    cache.delete(cache_key)
    try:
        return User.objects.get(id=user_id)
    except User.DoesNotExist:
        return AnonymousUser()


@database_sync_to_async
def get_user_from_token(token):
    from django.contrib.auth.models import User

    try:
        validated = AccessToken(token)
        return User.objects.get(id=validated["user_id"])
    except (InvalidToken, TokenError, User.DoesNotExist):
        return AnonymousUser()


class JWTAuthMiddleware:
    """Authenticates WebSocket connections using short-lived single-use tickets
    (?ticket=<ticket>) or fallback JWT tokens (?token=<token>).
    Single-use tickets prevent exposing long-lived access tokens in server logs and browser URLs."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode()
        params = parse_qs(query_string)
        ticket = params.get("ticket", [None])[0]
        token = params.get("token", [None])[0]

        if ticket:
            scope["user"] = await get_user_from_ticket(ticket)
        elif token:
            scope["user"] = await get_user_from_token(token)
        else:
            scope["user"] = AnonymousUser()

        return await self.app(scope, receive, send)
