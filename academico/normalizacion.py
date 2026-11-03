import unicodedata


def normalizar_nombre(valor):
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", valor.casefold().strip())
        if not unicodedata.combining(c)
    )
