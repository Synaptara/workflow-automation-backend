from django.urls import re_path
from .consumers import RunStatusConsumer

websocket_urlpatterns = [
    re_path(r"ws/runs/(?P<run_id>[0-9a-f-]+)/$", RunStatusConsumer.as_asgi()),
]
