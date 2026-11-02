from django.db.models import Max
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from .models import Notificacion
from .serializers import NotificacionSerializer
from .tickets import crear_ticket


class ThrottleTicket(UserRateThrottle):
    scope = "ticket"


def resumen_usuario(usuario):
    qs = Notificacion.objects.filter(usuario=usuario)
    return {
        "no_leidas": qs.filter(leida=False).count(),
        "ultima_id": qs.aggregate(ultima=Max("id"))["ultima"] or 0,
    }


class NotificacionesViewSet(viewsets.GenericViewSet):
    serializer_class = NotificacionSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return Notificacion.objects.filter(usuario=self.request.user)

    def list(self, request):
        qs = self.get_queryset()
        leida = request.query_params.get("leida")
        if leida is not None:
            if leida.lower() not in ("true", "false"):
                raise ValidationError({"leida": "Usa true o false"})
            qs = qs.filter(leida=leida.lower() == "true")
        desde = request.query_params.get("desde_id")
        if desde is not None:
            try:
                desde = int(desde)
                if desde < 0:
                    raise ValueError
            except ValueError:
                raise ValidationError({"desde_id": "Usa un entero no negativo"})
            qs = qs.filter(id__gt=desde)
        pagina = self.paginate_queryset(qs)
        return self.get_paginated_response(self.get_serializer(pagina, many=True).data)

    @action(detail=False, methods=["get"])
    def resumen(self, request):
        return Response(resumen_usuario(request.user))

    @action(detail=True, methods=["post"])
    def leer(self, request, pk=None):
        notificacion = self.get_object()
        notificacion.leida = True
        notificacion.save(update_fields=["leida"])
        return Response(status=204)

    @action(detail=False, methods=["post"], url_path="leer-todas")
    def leer_todas(self, request):
        return Response(
            {"actualizadas": self.get_queryset().filter(leida=False).update(leida=True)}
        )

    @action(detail=False, methods=["post"], throttle_classes=[ThrottleTicket])
    def ticket(self, request):
        ticket, expira = crear_ticket(request.user)
        return Response({"ticket": ticket, "expira_en": expira.isoformat()})
