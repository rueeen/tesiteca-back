from rest_framework import serializers, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from .models import Sede, Area, Carrera
from tesis.models import Tesis
from tesis.permisos import visibles


class SedeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sede
        fields = ["id", "nombre", "ciudad"]


class AreaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Area
        fields = ["id", "nombre"]


class CarreraSerializer(serializers.ModelSerializer):
    class Meta:
        model = Carrera
        fields = [
            "id",
            "nombre",
            "codigo",
            "area",
            "permite_repositorio",
            "extensiones_material",
        ]


class Sedes(generics.ListAPIView):
    queryset = Sede.objects.filter(activa=True).order_by("nombre")
    serializer_class = SedeSerializer
    pagination_class = None


class Areas(generics.ListAPIView):
    queryset = Area.objects.filter(activa=True).order_by("nombre")
    serializer_class = AreaSerializer
    pagination_class = None


class Carreras(generics.ListAPIView):
    queryset = Carrera.objects.filter(activa=True, area__activa=True).order_by("nombre")
    serializer_class = CarreraSerializer
    pagination_class = None


class Anios(APIView):
    def get(self, request):
        return Response(
            list(
                visibles(Tesis.objects.all(), request.user)
                .order_by("-anio")
                .values_list("anio", flat=True)
                .distinct()
            )
        )


class Profesores(APIView):
    def get(self, request):
        return Response(
            list(
                visibles(Tesis.objects.all(), request.user)
                .exclude(profesor_guia="")
                .order_by("profesor_guia")
                .values_list("profesor_guia", flat=True)
                .distinct()
            )
        )
