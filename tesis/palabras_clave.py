import json
from rest_framework import serializers


def _normalizar(palabras):
    resultado = []
    vistas = set()
    for palabra in palabras:
        if not isinstance(palabra, str):
            raise ValueError("Cada palabra clave debe ser texto")
        palabra = palabra.strip()
        if palabra and palabra.casefold() not in vistas:
            resultado.append(palabra)
            vistas.add(palabra.casefold())
    return resultado


def palabras_clave_lista(texto):
    """Leer tanto valores CSV como listas JSON guardadas por versiones anteriores."""
    if isinstance(texto, list):
        return _normalizar(texto)
    texto = (texto or "").strip()
    if texto.startswith("["):
        palabras = json.loads(texto)
        if not isinstance(palabras, list):
            raise ValueError("Se esperaba una lista de palabras clave")
    else:
        palabras = texto.split(",")
    return _normalizar(palabras)


class PalabrasClaveField(serializers.Field):
    def to_internal_value(self, valor):
        if not isinstance(valor, (str, list)):
            raise serializers.ValidationError(
                "Usa texto separado por comas o una lista JSON de textos"
            )
        try:
            normalizado = ",".join(palabras_clave_lista(valor))
        except (ValueError, TypeError):
            raise serializers.ValidationError(
                "Usa texto separado por comas o una lista JSON de textos"
            )
        if len(normalizado) > 500:
            raise serializers.ValidationError("Máximo 500 caracteres de palabras clave")
        return normalizado

    def to_representation(self, valor):
        return palabras_clave_lista(valor)
