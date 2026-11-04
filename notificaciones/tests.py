from usuarios.tests_helpers import crear_usuario_activo
import hashlib
from datetime import timedelta
from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from django.core.cache import cache
from rest_framework.test import APIClient
from usuarios.models import Usuario
from .models import Notificacion, TicketWS
from .tickets import crear_ticket, consumir_ticket
from .servicios import notificar


@override_settings(
    NOTIFICACIONES_WS=True,
    NOTIFICAR_POR_CORREO=False,
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class WebSocketTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.usuario = crear_usuario_activo(
            "socket@inacap.cl", nombre_completo="Socket", rol="ADMIN"
        )

    def conectar(self, ticket, origen="http://localhost:5173", extra=""):
        from config.asgi import application

        return WebsocketCommunicator(
            application,
            f"/ws/notificaciones/?ticket={ticket}{extra}",
            headers=[(b"origin", origen.encode())],
        )

    def test_ticket_hash_vigencia_unico_y_throttle(self):
        cliente = APIClient()
        cliente.force_authenticate(self.usuario)
        antes = timezone.now()
        r = cliente.post("/api/notificaciones/ticket/")
        self.assertEqual(r.status_code, 200)
        ticket = TicketWS.objects.get()
        self.assertEqual(
            ticket.ticket_hash, hashlib.sha256(r.data["ticket"].encode()).hexdigest()
        )
        self.assertGreaterEqual(ticket.expira_en, antes + timedelta(seconds=30))
        self.assertLess(ticket.expira_en, timezone.now() + timedelta(seconds=31))
        self.assertEqual(consumir_ticket(r.data["ticket"]).id, self.usuario.id)
        self.assertIsNone(consumir_ticket(r.data["ticket"]))
        for _ in range(19):
            self.assertEqual(
                cliente.post("/api/notificaciones/ticket/").status_code, 200
            )
        self.assertEqual(cliente.post("/api/notificaciones/ticket/").status_code, 429)

    async def test_socket_resumen_ping_y_entrega_real(self):
        ticket, _ = await database_sync_to_async(crear_ticket)(self.usuario)
        socket = self.conectar(ticket)
        conectado, _ = await socket.connect()
        self.assertTrue(conectado)
        self.assertEqual(
            await socket.receive_json_from(),
            {"tipo": "resumen", "no_leidas": 0, "ultima_id": 0},
        )
        await socket.send_json_to({"tipo": "ping"})
        self.assertEqual(await socket.receive_json_from(), {"tipo": "pong"})
        await database_sync_to_async(notificar)(
            [self.usuario],
            "TESIS_APROBADA",
            "Aprobada",
            "Mensaje",
            "/tesis/1",
            datos={"tesis_id": 1},
        )
        mensaje = await socket.receive_json_from()
        self.assertEqual(mensaje["tipo"], "notificacion")
        self.assertEqual(mensaje["notificacion"]["datos"], {"tesis_id": 1})
        await socket.send_json_to({"tipo": "leer-todas"})
        self.assertTrue(await socket.receive_nothing(timeout=0.05))
        reutilizado = self.conectar(ticket)
        conectado, codigo = await reutilizado.connect()
        self.assertFalse(conectado)
        self.assertEqual(codigo, 4401)
        await reutilizado.disconnect()
        await socket.disconnect()

    async def test_socket_ticket_invalido_expirado_y_usuario_inactivo(self):
        for tipo in ["invalido", "expirado", "inactivo", "jwt"]:
            if tipo in ["expirado", "inactivo"]:
                ticket, _ = await database_sync_to_async(crear_ticket)(self.usuario)
                if tipo == "expirado":
                    await database_sync_to_async(TicketWS.objects.update)(
                        expira_en=timezone.now() - timedelta(seconds=1)
                    )
                else:
                    await database_sync_to_async(
                        Usuario.objects.filter(pk=self.usuario.pk).update
                    )(is_active=False)
            else:
                ticket = "jwt-no-admitido" if tipo == "jwt" else "invalido"
            socket = self.conectar(
                ticket, extra="&token=jwt-no-admitido" if tipo == "jwt" else ""
            )
            conectado, codigo = await socket.connect()
            self.assertFalse(conectado)
            self.assertEqual(codigo, 4401)
            await socket.disconnect()

    async def test_origen_no_permitido_no_consume_ticket(self):
        ticket, _ = await database_sync_to_async(crear_ticket)(self.usuario)
        socket = self.conectar(ticket, "https://maligno.test")
        conectado, _ = await socket.connect()
        self.assertFalse(conectado)
        await socket.disconnect()
        self.assertFalse(
            await database_sync_to_async(lambda: TicketWS.objects.get().usado)()
        )

    @override_settings(NOTIFICACIONES_WS=False)
    async def test_ws_deshabilitado(self):
        ticket, _ = await database_sync_to_async(crear_ticket)(self.usuario)
        socket = self.conectar(ticket)
        conectado, codigo = await socket.connect()
        self.assertFalse(conectado)
        self.assertEqual(codigo, 4403)
        await socket.disconnect()
