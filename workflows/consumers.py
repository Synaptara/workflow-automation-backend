import json
import uuid

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer


class RunStatusConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        raw_run_id = self.scope["url_route"]["kwargs"].get("run_id", "")
        try:
            self.run_id = str(uuid.UUID(str(raw_run_id)))
        except ValueError:
            await self.close()
            return

        self.group_name = f"run_{self.run_id}"
        user = self.scope.get("user")

        if not user or not user.is_authenticated:
            await self.close()
            return

        if not await self._run_belongs_to_user(self.run_id, user):
            await self.close()
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    @database_sync_to_async
    def _run_belongs_to_user(self, run_id, user):
        from .models import WorkflowRun

        return WorkflowRun.objects.filter(id=run_id, workflow__owner=user).exists()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def run_event(self, event):
        await self.send(
            text_data=json.dumps({"event": event["event"], "data": event["data"]})
        )


class UserNotificationConsumer(AsyncWebsocketConsumer):
    """Listens globally for events associated with the authenticated user."""

    async def connect(self):
        user = self.scope.get("user")

        if not user or not user.is_authenticated:
            await self.close()
            return

        self.group_name = f"user_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def notify_event(self, event):
        await self.send(
            text_data=json.dumps({"event": event["event"], "data": event["data"]})
        )
