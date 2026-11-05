from django.shortcuts import get_object_or_404
from django.db import transaction
from rest_framework import serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import BasePermission
from rest_framework.throttling import UserRateThrottle
from usuarios.models import Usuario, SolicitudAcceso, Rol
from usuarios.serializers import UsuarioSerializer
from usuarios.cookies import borrar_refresh
from tesis.models import Tesis, AutorTesis, RegistroAcceso
from notificaciones.models import Notificacion
from .models import AceptacionPolitica
from .servicios import aceptar_politica
from .anonimizacion import anonimizar_usuario, UltimoAdministrador, MOTIVOS


class SoloAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.rol == Rol.ADMIN


class ThrottleMisDatos(UserRateThrottle):
    rate = "5/hour"
    scope = "mis_datos"


class AceptarPolitica(APIView):
    def post(self, request):
        aceptar_politica(request.user)
        return Response(UsuarioSerializer(request.user).data)


class MisDatos(APIView):
    throttle_classes = [ThrottleMisDatos]

    def get(self, request):
        u = request.user
        respuesta = Response(
            {
                "perfil": UsuarioSerializer(u).data,
                "aceptaciones_politica": list(
                    AceptacionPolitica.objects.filter(usuario=u).values(
                        "version", "fecha"
                    )
                ),
                "solicitudes_acceso": list(
                    SolicitudAcceso.objects.filter(usuario=u).values(
                        "id",
                        "rol_solicitado",
                        "carrera_id",
                        "sede_id",
                        "mensaje",
                        "estado",
                        "motivo_rechazo",
                        "creada",
                        "revisada_en",
                    )
                ),
                "tesis_subidas": list(
                    Tesis.objects.filter(subido_por=u).values(
                        "id",
                        "titulo",
                        "tipo",
                        "anio",
                        "estado",
                        "creado",
                        "fecha_publicacion",
                        "autoriza_publicacion",
                        "autorizacion_version",
                        "autorizacion_en",
                    )
                ),
                "autorias": list(
                    AutorTesis.objects.filter(usuario=u).values(
                        "tesis_id", "nombre_completo", "email", "orden"
                    )
                ),
                "lecturas": list(
                    RegistroAcceso.objects.filter(usuario=u).values(
                        "tesis_id", "fecha", "accion", "ip"
                    )
                ),
                "notificaciones": list(
                    Notificacion.objects.filter(usuario=u).values(
                        "id",
                        "tipo",
                        "titulo",
                        "mensaje",
                        "enlace",
                        "datos",
                        "leida",
                        "creada",
                    )
                ),
            }
        )
        respuesta["Content-Disposition"] = (
            'attachment; filename="mis-datos-tesiteca.json"'
        )
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class PerfilSerializer(serializers.Serializer):
    nombre_completo = serializers.CharField(max_length=200)

    def validate(self, datos):
        if set(self.initial_data) - {"nombre_completo"}:
            raise serializers.ValidationError(
                "Solo puedes modificar nombre_completo; los demás datos los corrige un administrador"
            )
        return datos


class Perfil(APIView):
    def patch(self, request):
        serial = PerfilSerializer(data=request.data)
        serial.is_valid(raise_exception=True)
        request.user.nombre_completo = serial.validated_data["nombre_completo"]
        request.user.save(update_fields=["nombre_completo"])
        return Response(UsuarioSerializer(request.user).data)


class EliminarSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    confirmacion = serializers.ChoiceField(
        choices=["ELIMINAR"],
        error_messages={"invalid_choice": "Escribe ELIMINAR para confirmar"},
    )


class Eliminar(APIView):
    @transaction.atomic
    def post(self, request):
        serial = EliminarSerializer(data=request.data)
        serial.is_valid(raise_exception=True)
        usuario = Usuario.objects.get(pk=request.user.pk)
        if not usuario.check_password(serial.validated_data["password"]):
            raise serializers.ValidationError({"password": "Contraseña incorrecta"})
        try:
            anonimizar_usuario(usuario, "solicitud_titular", ejecutado_por=usuario)
        except UltimoAdministrador as exc:
            return Response({"detail": str(exc)}, status=409)
        return borrar_refresh(Response(status=204))


class AnonimizarAdminSerializer(serializers.Serializer):
    motivo = serializers.ChoiceField(
        choices=MOTIVOS,
        error_messages={
            "invalid_choice": "Usa solicitud_titular, solicitud_administrativa o retencion; no incluyas datos personales"
        },
    )


class AnonimizarAdmin(APIView):
    permission_classes = [SoloAdmin]

    def post(self, request, pk):
        serial = AnonimizarAdminSerializer(data=request.data)
        serial.is_valid(raise_exception=True)
        usuario = get_object_or_404(Usuario, pk=pk)
        try:
            anonimizar_usuario(
                usuario, serial.validated_data["motivo"], ejecutado_por=request.user
            )
        except UltimoAdministrador as exc:
            return Response({"detail": str(exc)}, status=409)
        respuesta = Response(status=204)
        return borrar_refresh(respuesta) if usuario.pk == request.user.pk else respuesta
