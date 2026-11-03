import re


def normalizar_resumen(texto):
    lineas = texto.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    parrafos = []
    actual = ""
    for linea in lineas:
        linea = re.sub(r"[^\S\n]+", " ", linea).strip()
        if not linea:
            if actual:
                parrafos.append(actual)
                actual = ""
            continue
        if not actual:
            actual = linea
        elif actual.endswith("-") and linea[0].islower():
            actual = actual[:-1] + linea
        elif actual.endswith((".", "!", "?", ":", ";")) or re.match(
            r"^(?:[-•*]|\d+[.)])(?:\s|$)", linea
        ):
            parrafos.append(actual)
            actual = linea
        else:
            actual += " " + linea
    if actual:
        parrafos.append(actual)
    return "\n\n".join(parrafos)


def resumen_breve(texto, limite=280):
    if len(texto) <= limite:
        return texto
    corte = texto[: limite - 1]
    if not texto[limite - 1].isspace() and not texto[limite - 2].isspace():
        corte = corte.rsplit(" ", 1)[0] if " " in corte else ""
    return corte.rstrip() + "…"
