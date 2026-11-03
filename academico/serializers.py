from rest_framework import serializers
from .models import Carrera, Sede
from .opciones import NivelFormacion, Region


class MiniSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    nombre = serializers.CharField(read_only=True)


class SedeMiniSerializer(serializers.ModelSerializer):
    region = serializers.SerializerMethodField()

    class Meta:
        model = Sede
        fields = ["id", "nombre", "ciudad", "region"]

    def get_region(self, obj):
        return {"id": obj.region, "nombre": obj.get_region_display()}


class CarreraMiniSerializer(serializers.ModelSerializer):
    nivel_formacion = serializers.SerializerMethodField()

    class Meta:
        model = Carrera
        fields = [
            "id",
            "nombre",
            "codigo",
            "area",
            "permite_repositorio",
            "nivel_formacion",
            "duracion_semestres",
        ]

    def get_nivel_formacion(self, obj):
        return {"id": obj.nivel_formacion, "nombre": obj.get_nivel_formacion_display()}


def tipo_mini(codigo):
    from tesis.models import Tesis

    return {
        "id": codigo,
        "nombre": dict(Tesis._meta.get_field("tipo").choices).get(codigo, codigo),
    }
