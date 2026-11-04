from io import BytesIO
from math import hypot, sqrt
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from pypdf import PdfReader, PdfWriter, Transformation
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

TEXTO_DIAGONAL = "INACAP · Biblioteca de Tesis · Uso académico exclusivo"


def _marcar(origen, dibujar):
    lector = PdfReader(origen)
    salida = PdfWriter()
    for pagina in lector.pages:
        if pagina.rotation:
            pagina.transfer_rotation_to_content()
        visible = pagina.cropbox
        izquierda, abajo = float(visible.left), float(visible.bottom)
        ancho, alto = float(visible.width), float(visible.height)
        capa = BytesIO()
        lienzo = canvas.Canvas(capa, pagesize=(ancho, alto))
        dibujar(lienzo, ancho, alto)
        lienzo.save()
        capa.seek(0)
        marca = PdfReader(capa).pages[0]
        marca.add_transformation(Transformation().translate(izquierda, abajo))
        for caja in (marca.mediabox, marca.cropbox, marca.trimbox):
            caja.lower_left = (izquierda, abajo)
            caja.upper_right = (izquierda + ancho, abajo + alto)
        pagina.merge_page(marca)
        salida.add_page(pagina)
    resultado = BytesIO()
    salida.write(resultado)
    resultado.seek(0)
    return resultado


def _ajustar_texto(texto, ancho):
    fuente = 6.5
    while fuente > 5 and stringWidth(texto, "Helvetica", fuente) > ancho:
        fuente -= 0.25
    if stringWidth(texto, "Helvetica", fuente) > ancho:
        while texto and stringWidth(texto + "…", "Helvetica", fuente) > ancho:
            texto = texto[:-1]
        texto += "…"
    return texto, fuente


def _rotulo(c, texto, ancho, alto, encabezado=False):
    texto, fuente = _ajustar_texto(texto, max(1, ancho - 26))
    largo = stringWidth(texto, "Helvetica", fuente)
    x = 13 if encabezado else (ancho - largo) / 2
    y = alto - 10 - fuente if encabezado else 10
    c.saveState()
    c.setFillColorRGB(1, 1, 1)
    c.setFillAlpha(0.85)
    c.rect(x - 3, y - 3, largo + 6, fuente + 6, fill=1, stroke=0)
    c.setFillAlpha(1)
    c.setFillColorRGB(0.25, 0.25, 0.25)
    c.setFont("Helvetica", fuente)
    c.drawString(x, y, texto)
    c.restoreState()


def generar_marca_fija(tesis):
    def dibujar(c, ancho, alto):
        # El límite geométrico mantiene visibles las tres diagonales, incluso en horizontal.
        largo_maximo = 2 * sqrt(2) * max(1, min(ancho / 2 - 10, alto / 4 - 10))
        fuente = max(
            10,
            min(
                28,
                hypot(ancho, alto) / 38,
                largo_maximo / stringWidth(TEXTO_DIAGONAL, "Helvetica", 1),
            ),
        )
        for fraccion in (0.25, 0.5, 0.75):
            c.saveState()
            c.setFillColorRGB(0.25, 0.25, 0.25)
            c.setFillAlpha(0.22)
            c.setStrokeColorRGB(1, 1, 1)
            c.setStrokeAlpha(0.35)
            c.setLineWidth(0.6)
            c.translate(ancho / 2, alto * fraccion)
            c.rotate(45)
            texto = c.beginText()
            texto.setFont("Helvetica", fuente)
            texto.setTextRenderMode(2)
            texto.setTextOrigin(
                -stringWidth(TEXTO_DIAGONAL, "Helvetica", fuente) / 2, 0
            )
            texto.textLine(TEXTO_DIAGONAL)
            c.drawText(texto)
            c.restoreState()
        _rotulo(
            c,
            f"{tesis.carrera} · {tesis.anio} · ID {tesis.id} — Prohibida su reproducción total o parcial sin citar",
            ancho,
            alto,
        )

    with tesis.pdf_original.open("rb") as original:
        marcado = _marcar(original, dibujar)
    tesis.pdf_marcado.save("marcado.pdf", ContentFile(marcado.getvalue()), save=False)
    tesis.save(update_fields=["pdf_marcado"])


def regenerar_marca(tesis):
    anterior = tesis.pdf_marcado.name
    storage = tesis.pdf_marcado.storage
    try:
        with transaction.atomic():
            generar_marca_fija(tesis)
            if anterior and anterior != tesis.pdf_marcado.name:
                transaction.on_commit(lambda: storage.delete(anterior), robust=True)
    except Exception:
        nuevo = tesis.pdf_marcado.name
        if nuevo and nuevo != anterior:
            storage.delete(nuevo)
        tesis.pdf_marcado.name = anterior
        raise


def aplicar_marca_lector(ruta_pdf, usuario, ip):
    fecha = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S %Z")

    def dibujar(c, ancho, alto):
        _rotulo(
            c,
            f"Consultado por {usuario.email} · {fecha} · IP {ip}",
            ancho,
            alto,
            encabezado=True,
        )

    return _marcar(ruta_pdf, dibujar)
