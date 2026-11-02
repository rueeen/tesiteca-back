from urllib.parse import parse_qs
from channels.db import database_sync_to_async
from .tickets import consumir_ticket


class TicketAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        parametros = parse_qs(
            scope.get("query_string", b"").decode("utf-8", errors="replace")
        )
        tickets = parametros.get("ticket", [])
        usuario = await database_sync_to_async(consumir_ticket)(
            tickets[0] if len(tickets) == 1 else ""
        )
        if usuario is None:
            await send({"type": "websocket.close", "code": 4401})
            return
        scope = dict(scope, user=usuario)
        await self.app(scope, receive, send)
