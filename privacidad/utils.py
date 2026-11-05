import ipaddress
import re


def truncar_ip(ip):
    try:
        direccion = ipaddress.ip_address(ip)
        prefijo = 24 if direccion.version == 4 else 48
        return str(
            ipaddress.ip_network(f"{direccion}/{prefijo}", strict=False).network_address
        )
    except (ValueError, TypeError):
        return ""


def familia_user_agent(valor):
    navegador = next(
        (
            nombre
            for patron, nombre in [
                ("Edg/", "Edge"),
                ("OPR/", "Opera"),
                ("Firefox/", "Firefox"),
                ("Chrome/", "Chrome"),
                ("Safari/", "Safari"),
            ]
            if patron in valor
        ),
        "Otro",
    )
    sistema = next(
        (
            nombre
            for patron, nombre in [
                ("Android", "Android"),
                ("iPhone", "iOS"),
                ("iPad", "iOS"),
                ("Windows", "Windows"),
                ("Macintosh", "macOS"),
                ("Linux", "Linux"),
            ]
            if patron in valor
        ),
        "Otro",
    )
    return f"{navegador} / {sistema}" if valor else ""


def enmascarar_rut(rut):
    compacto = re.sub(r"[.\s-]", "", rut or "")
    if len(compacto) < 2:
        return ""
    cuerpo, digito = compacto[:-1], compacto[-1]
    prefijo = cuerpo[:-6] or "*"
    return f"{prefijo}.***.***-{digito}"
