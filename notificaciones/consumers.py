from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.conf import settings
from .views import resumen_usuario


class NotificacionesConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        if not settings.NOTIFICACIONES_WS:
            await self.close(code=4403)
            return
        self.grupo = f'usuario_{self.scope["user"].pk}'
        await self.channel_layer.group_add(self.grupo, self.channel_name)
        await self.accept()
        resumen = await database_sync_to_async(resumen_usuario)(self.scope["user"])
        await self.send_json({"tipo": "resumen", **resumen})

    async def disconnect(self, close_code):
        if hasattr(self, "grupo"):
            await self.channel_layer.group_discard(self.grupo, self.channel_name)

    async def notificacion_nueva(self, event):
        await self.send_json(
            {"tipo": "notificacion", "notificacion": event["notificacion"]}
        )

    async def receive_json(self, content, **kwargs):
        if isinstance(content, dict) and content.get("tipo") == "ping":
            await self.send_json({"tipo": "pong"})
