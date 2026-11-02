import hashlib
import secrets
from datetime import timedelta
from django.utils import timezone
from .models import TicketWS


def crear_ticket(usuario):
    ticket = secrets.token_urlsafe(32)
    registro = TicketWS.objects.create(
        usuario=usuario,
        ticket_hash=hashlib.sha256(ticket.encode()).hexdigest(),
        expira_en=timezone.now() + timedelta(seconds=30),
    )
    return ticket, registro.expira_en


def consumir_ticket(ticket):
    if not ticket or len(ticket) > 128:
        return None
    filtro = TicketWS.objects.filter(
        ticket_hash=hashlib.sha256(ticket.encode()).hexdigest(),
        usado=False,
        expira_en__gt=timezone.now(),
        usuario__is_active=True,
    )
    registro = filtro.select_related("usuario").first()
    if registro and filtro.update(usado=True) == 1:
        return registro.usuario
    return None
