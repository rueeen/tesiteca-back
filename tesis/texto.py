import re


def normalizar_resumen(texto: str) -> str:
    if not texto:
        return ""
    texto = (
        texto.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u00a0", " ")
        .replace("\t", " ")
    )
    parrafos = []
    actual = ""
    for original in texto.split("\n"):
        linea = original.strip()
        if not linea:
            if actual:
                parrafos.append(actual)
                actual = ""
        elif re.match(r"^([-•*]|\d{1,2}[.)])\s+", linea):
            if actual:
                parrafos.append(actual)
            actual = linea
        elif not actual:
            actual = linea
        elif actual.endswith("-") and len(actual) >= 2 and actual[-2].isalnum():
            actual = (actual[:-1] if linea[0].islower() else actual) + linea
        else:
            cierre = actual.rstrip(")\"”»'")
            termina_oracion = bool(cierre) and cierre[-1] in ".!?:;"
            primero = linea[0]
            empieza_mayuscula = (
                primero in "¿¡\"“«'(" or primero.isdigit() or primero.isupper()
            )
            if termina_oracion and empieza_mayuscula:
                parrafos.append(actual)
                actual = linea
            else:
                actual += " " + linea
    if actual:
        parrafos.append(actual)
    return "\n\n".join(re.sub(r" {2,}", " ", parrafo) for parrafo in parrafos).strip()


def resumen_breve(texto, limite=280):
    if len(texto) <= limite:
        return texto
    corte = texto[: limite - 1]
    if not texto[limite - 1].isspace() and not texto[limite - 2].isspace():
        corte = corte.rsplit(" ", 1)[0] if " " in corte else ""
    return corte.rstrip() + "…"
