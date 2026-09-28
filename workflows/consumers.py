import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer


class RunStatusConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.run_id = self.scope["url_route"]["kwargs"]["run_id"]
        self.group_name = f"run_{self.run_id}"
        user = self.scope["user"]

        if not user.is_authenticated:
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
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def run_event(self, event):
        await self.send(
            text_data=json.dumps({"event": event["event"], "data": event["data"]})
        )
