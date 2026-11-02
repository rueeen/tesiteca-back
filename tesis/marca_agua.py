from io import BytesIO
from reportlab.pdfgen import canvas
from pypdf import PdfReader, PdfWriter, Transformation
from django.core.files.base import ContentFile
from django.utils import timezone


def _marcar(origen, dibujar):
    lector = PdfReader(origen)
    salida = PdfWriter()
    for pagina in lector.pages:
        # Normalizar la rotación conserva el aspecto visual y permite situar las capas.
        if pagina.rotation:
            pagina.transfer_rotation_to_content()
        ancho, alto = float(pagina.mediabox.width), float(pagina.mediabox.height)
        capa = BytesIO()
        lienzo = canvas.Canvas(capa, pagesize=(ancho, alto))
        dibujar(lienzo, ancho, alto)
        lienzo.save()
        capa.seek(0)
        # La capa se dibuja en coordenadas locales y luego se sitúa en el origen
        # real de la página. Transformar también sus cajas evita recortar la marca.
        marca = PdfReader(capa).pages[0]
        izquierda = float(pagina.mediabox.left)
        abajo = float(pagina.mediabox.bottom)
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


def generar_marca_fija(tesis):
    def dibujar(c, ancho, alto):
        c.saveState()
        c.setFillColorRGB(0.4, 0.4, 0.4)
        c.setFillAlpha(0.12)
        c.translate(ancho / 2, alto / 2)
        c.rotate(45)
        texto = "INACAP · Biblioteca de Tesis · Uso académico exclusivo"
        c.setFont("Helvetica", min(24, max(7, ancho / 29)))
        c.drawCentredString(0, 0, texto)
        c.restoreState()
        c.setFont("Helvetica", 6)
        c.drawCentredString(
            ancho / 2,
            12,
            f"{tesis.carrera} · {tesis.anio} · ID {tesis.id} — Prohibida su reproducción total o parcial sin citar",
        )

    with tesis.pdf_original.open("rb") as original:
        marcado = _marcar(original, dibujar)
    tesis.pdf_marcado.save("marcado.pdf", ContentFile(marcado.getvalue()), save=False)
    tesis.save(update_fields=["pdf_marcado"])


def aplicar_marca_lector(ruta_pdf, usuario, ip):
    fecha = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S %Z")

    def dibujar(c, ancho, alto):
        c.setFont("Helvetica", 6)
        c.drawString(
            12, alto - 12, f"Consultado por {usuario.email} · {fecha} · IP {ip}"
        )

    return _marcar(ruta_pdf, dibujar)
