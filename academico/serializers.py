from rest_framework import serializers
from .models import Carrera


class MiniSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    nombre = serializers.CharField(read_only=True)


class CarreraMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Carrera
        fields = ["id", "nombre", "codigo", "area", "permite_repositorio"]


def tipo_mini(codigo):
    from tesis.models import Tesis

    return {
        "id": codigo,
        "nombre": dict(Tesis._meta.get_field("tipo").choices).get(codigo, codigo),
    }
