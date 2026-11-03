import re
from django.core.exceptions import ValidationError


def normalizar_rut(valor):
    limpio = re.sub(r"[.\s-]", "", valor).upper()
    if not re.fullmatch(r"\d{7,8}[0-9K]", limpio):
        raise ValidationError("Ingresa un RUT chileno válido")
    cuerpo, digito = limpio[:-1], limpio[-1]
    total = sum(int(numero) * (2 + i % 6) for i, numero in enumerate(reversed(cuerpo)))
    resto = 11 - total % 11
    esperado = "0" if resto == 11 else "K" if resto == 10 else str(resto)
    if esperado != digito:
        raise ValidationError("El dígito verificador del RUT no es válido")
    return f"{int(cuerpo)}-{digito}"
