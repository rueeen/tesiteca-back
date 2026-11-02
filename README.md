# Biblioteca de Tesis · INACAP Arica

Backend Django 5.2, DRF y SQLite para la demo de Informática, Ciberseguridad y Telecomunicaciones. Requiere Python 3.11 o superior. El proyecto está en la raíz de este repositorio.

## Instalación local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(64))"
# Copiar el resultado a SECRET_KEY en .env; configurar SEED_ADMIN_EMAIL.
python manage.py migrate
python manage.py seed_demo --con-ejemplos
python manage.py runserver
```

No versionar `.env`, SQLite ni los archivos privados. `SECRET_KEY` es obligatorio, incluso en desarrollo. Los valores de entorno del proceso tienen prioridad sobre `.env`. La configuración local preparada en la nube usa `/workspace/venv-tesiteca`; activar con `source /workspace/venv-tesiteca/bin/activate` desde `/workspace/tesiteca-back`.

`seed_demo` es idempotente: crea Arica, el área y las carreras IEI/AP. `SEED_ADMIN_EMAIL`, si se configura con un correo institucional, agrega ese ADMIN a la lista blanca. `--con-ejemplos` agrega 15 tesis de 5–10 páginas (11 publicadas, 3 en revisión y 1 rechazada) y seis personas ficticias. Cada tesis pertenece a la carrera de quien la sube y de sus autores vinculados. `--reset-ejemplos` elimina las tesis cuyo título empieza por `Demo ` y sus archivos antes de regenerar los ejemplos; usarlo para actualizar el seed antiguo. Los enlaces de repositorios de ejemplo son ficticios. No cargar ejemplos en producción.

## Variables

Ver `.env.example`. Configurar `DEBUG=False`, `ALLOWED_HOSTS` y `CORS_ALLOWED_ORIGINS` para cada despliegue. `PRIVATE_MEDIA_ROOT` admite una ruta absoluta; una relativa se resuelve desde el directorio de trabajo. Debe quedar fuera de directorios públicos. Los límites son `MAX_PDF_MB=30` y `MAX_MATERIAL_MB=50`. Los tokens duran `ACCESS_TOKEN_MINUTES=60` y `REFRESH_TOKEN_DAYS=7`.

Correo local: `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend`. En producción usar `django.core.mail.backends.smtp.EmailBackend` y configurar `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` y `DEFAULT_FROM_EMAIL`. Guardar las credenciales en variables o en `.env` protegido, nunca en Git.

## Autenticación de la API

```bash
curl -X POST http://127.0.0.1:8000/api/auth/solicitar-codigo/ \
  -H 'Content-Type: application/json' -d '{"email":"demo1@inacapmail.cl"}'
# Leer el código de seis dígitos en la consola del servidor:
curl -X POST http://127.0.0.1:8000/api/auth/verificar-codigo/ \
  -H 'Content-Type: application/json' -d '{"email":"demo1@inacapmail.cl","codigo":"123456"}'
```

La respuesta devuelve `access`, `refresh` y `usuario`. Enviar `Authorization: Bearer <access>` en las demás solicitudes. Renovar en `POST /api/auth/refresh/` con `{"refresh":"..."}`. Consultar perfil en `GET /api/auth/me/`.

Las solicitudes de código tienen respuesta genérica para correos institucionales; dominios ajenos se rechazan con 400. Se cuentan también las solicitudes de emails no autorizados para que el límite no revele la lista blanca. Código válido durante 10 minutos, cinco intentos, un solo uso y tres solicitudes por correo en 10 minutos. Además existe throttle de 10/min por IP por endpoint. La caché de desarrollo es local al proceso; configurar caché compartida si se despliegan varios workers. Desactivar un autorizado impide nuevos logins; un JWT previamente emitido sigue vigente hasta su expiración.

El rol ADMIN de la API no habilita automáticamente el panel Django. Para el panel:

```bash
python manage.py createsuperuser
```

Su contraseña se usa solo en `/admin/`. El login de la API sigue requiriendo lista blanca y código.

## Lista blanca

Usuarios ADMIN, coordinadores y directores pueden descargar `GET /api/admin/autorizados/plantilla/` e importar con `POST /api/admin/autorizados/importar/` (multipart, campo `archivo`, CSV UTF-8 o XLSX, máximo 5 MB y 10000 filas).

Columnas exactas, en este orden:

```csv
email,rut,nombre_completo,rol,carrera_codigo,area,sede
estudiante@inacapmail.cl,12345678-9,Estudiante Demo,ESTUDIANTE,AP,,Arica
coordinador@inacap.cl,11222333-4,Coordinador Demo,COORDINADOR,IEI,,Arica
```

Roles: `ESTUDIANTE`, `COORDINADOR`, `DIRECTOR`, `ADMIN`. Carrera obligatoria para estudiantes y coordinadores; área por nombre exacto obligatoria para directores; sede por nombre exacto, opcional. Los códigos de carrera y nombres de catálogos deben existir. Se normalizan emails y se actualiza por email. Una fila inválida no detiene las demás. Se devuelve `total_filas`, `creados`, `actualizados`, `errores` con número de fila Excel (encabezado en fila 1). La actualización no reactiva automáticamente una persona previamente desactivada.

`GET /api/admin/autorizados/` admite búsqueda y filtros `rol`, `carrera`, `activo`. `PATCH /api/admin/autorizados/{id}/` edita datos y activa/desactiva. Los coordinadores administran estudiantes de su carrera y los directores estudiantes/coordinadores de carreras de su área. No pueden cambiar un registro para elevarlo fuera de ese ámbito. El archivo de importación se conserva en almacenamiento privado, sin URL pública.

## Biblioteca y flujo editorial

- Catálogos autenticados: `/api/catalogos/sedes/`, `areas/`, `carreras/`, `tipos/`, `anios/`, `profesores-guia/`.
- `GET /api/tesis/`: solo publicaciones visibles. Busca con `search`; `en_contenido=true` incluye texto del PDF. Filtros: `carrera`, `sede`, `tipo`, `anio`, `anio_desde`, `anio_hasta`, `profesor_guia`, `palabra_clave`, `tiene_repositorio`. Orden por `anio`, `titulo`, `fecha_publicacion` con prefijo `-` opcional. Paginación de 12, máximo 48 con `page_size`.
- `POST /api/tesis/`: multipart con `titulo`, `resumen`, `palabras_clave` como texto separado por comas o lista JSON, `tipo` (`TESIS`, `PROYECTO_TITULO`, `INFORME_PRACTICA`), `anio`, `semestre` opcional (1 o 2), ID de `carrera` y `sede` opcional (por defecto la del usuario o la única sede activa), `profesor_guia`, `pdf`, `autores` (JSON `[{"nombre_completo":"...","email":"..."}]`) y `repositorio_url` opcional. `publicar=true` permite publicación directa para coordinador/director/admin dentro de su ámbito. Estudiantes siempre envían a revisión y se agregan como autores vinculados.
- `GET/PATCH/DELETE /api/tesis/{id}/`: detalle y edición. Estudiantes solo editan/eliminan sus tesis en BORRADOR o RECHAZADA. Coordinadores/directores administran su ámbito; ADMIN todo. La carrera de una tesis existente no se cambia. Reemplazar PDF regenera hash, texto y marcas. Cambiar año regenera el pie de página.
- `GET /api/tesis/mis-tesis/`: subidas y autorías vinculadas, todos los estados. `GET /api/tesis/pendientes/`: revisión del ámbito del funcionario.
- `POST /api/tesis/{id}/aprobar/`, `rechazar/` (JSON `{"observacion":"..."}` obligatorio) y `reenviar/`. Aprobar/rechazar requiere EN_REVISION; reenviar requiere autor y estado BORRADOR/RECHAZADA.

Estudiantes ven publicadas de su carrera y sus propias autorías en cualquier estado. Los funcionarios ven las tesis de su ámbito y las propias. El listado nunca entrega rutas privadas ni texto extraído.

## PDFs y material

`GET /api/tesis/{id}/pdf/` requiere JWT y devuelve PDF inline con marca fija y marca del lector (email, fecha, IP de la conexión), `Cache-Control: no-store` y `nosniff`. El frontend debe solicitarlo con Authorization y mostrar un Blob en su visor. No poner tokens en URLs. `GET /api/tesis/{id}/pdf-original/` está reservado a ADMIN. Las marcas ayudan a la trazabilidad; no impiden copiar o capturar un documento.

Se valida firma `%PDF`, tamaño, lectura completa, ausencia de cifrado y SHA-256 único. Las marcas respetan dimensiones y normalizan rotación por página. Los fallos al generar la marca revierten la fila y limpian los nuevos archivos. SQLite y archivos no constituyen una única transacción frente a un cierre abrupto del proceso; incluir ambos en respaldos y revisar archivos huérfanos tras incidentes.

`GET/POST /api/tesis/{id}/materiales/`: `tipo`, `titulo`, `descripcion`, `solo_carrera`, y `url` o `archivo`. Repositorios: solo carreras habilitadas, HTTPS GitHub con formato propietario/repositorio, siempre restringidos a la carrera. Enlaces: HTTPS. Archivos: extensión permitida en `Carrera.extensiones_material` y límite configurable. No se habilitan formatos especiales adicionales.

`POST /api/materiales/{id}/acceso/` devuelve URL y registra acceso. `GET /api/materiales/{id}/descargar/` sirve adjuntos autenticados. `DELETE /api/materiales/{id}/` usa permisos de edición de la tesis. Un material restringido conserva metadatos pero omite URL/descarga e indica `restringido: true`. También acceden ADMIN y directores del área. Se registran usuario, tesis, acción, IP y user-agent. Al eliminar una tesis se conserva el registro de acceso con referencia nula. El admin ofrece acciones de aprobación y regeneración, y registros de acceso de solo lectura.

## Validación

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

Las pruebas usan SQLite temporal, correo en memoria y archivos aislados: login/JWT, límites y expiración, importación/upsert y permisos, visibilidad, revisión, materiales, PDF cifrado/duplicado, rotación, marcas, descarga autenticada y rollback. El seed se puede ejecutar dos veces sin duplicar las tesis de ejemplo, también con `--reset-ejemplos`.

## PythonAnywhere

1. Clonar el repositorio en una consola Bash y crear un virtualenv Python 3.11+; instalar `requirements.txt`.
2. Crear `.env` con SECRET_KEY nuevo, `DEBUG=False`, `ALLOWED_HOSTS=tuusuario.pythonanywhere.com`, el origen HTTPS del frontend y SMTP. Usar `PRIVATE_MEDIA_ROOT=/home/tuusuario/privado/tesis` y permisos restringidos.
3. En la carpeta del proyecto ejecutar `python manage.py migrate`, `python manage.py seed_demo` y `python manage.py collectstatic --noinput`. Crear superusuario si se necesita el panel.
4. Crear una web app manual de Python y seleccionar el virtualenv. WSGI:

```python
import os
import sys
ruta = '/home/tuusuario/tesiteca-back'
sys.path.insert(0, ruta)
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

5. En Web mapear solamente `/static/` a `staticfiles/`. **PRIVATE_MEDIA_ROOT no debe mapearse como static ni como media pública**. No añadir rutas de Django para servirlo.
6. Recargar la app y comprobar login, biblioteca y PDF autenticado. Configurar límites de subida del hosting para los tamaños elegidos, SMTP permitido por el plan y HTTPS. Respaldar SQLite y archivos privados; no usar `runserver` en producción. Revisar `python manage.py check --deploy` y activar cookies seguras/redirección HTTPS según la configuración real del proxy del hosting.

El despliegue real en PythonAnywhere y el envío SMTP requieren la cuenta y configuración del propietario; no forman parte de la validación local.


## Usuarios demo

| Correo | Rol | Carrera / área |
|---|---|---|
| demo1@inacapmail.cl | ESTUDIANTE | IEI |
| demo2@inacapmail.cl | ESTUDIANTE | IEI |
| demo3@inacapmail.cl | ESTUDIANTE | AP |
| demo4@inacapmail.cl | COORDINADOR | AP |
| demo5@inacapmail.cl | COORDINADOR | IEI |
| demo6@inacapmail.cl | DIRECTOR | Informática, Ciberseguridad y Telecomunicaciones |

Ingresar mediante código de correo (consola en desarrollo). `demo1` tiene una tesis rechazada con observación para probar el reenvío. Hay pendientes para los coordinadores de ambas carreras. El comando imprime esta tabla al terminar.

Para reemplazar las tesis del esquema anterior y limpiar sus PDFs:

```bash
python manage.py migrate
python manage.py seed_demo --con-ejemplos --reset-ejemplos
```

## Contrato de la API

Objetos reutilizables:

```json
// CarreraMini
{ "id": 1, "nombre": "Ingeniería en Informática", "codigo": "IEI", "area": 1, "permite_repositorio": true }
// Mini (sede, área, tipo)
{ "id": 1, "nombre": "Arica" }          // tipo usa id = código: { "id": "TESIS", "nombre": "Tesis" }
// UsuarioMini
{ "id": 4, "nombre_completo": "Persona ficticia 4", "email": "demo4@inacapmail.cl" }
```

### `GET /api/auth/me/` y `usuario` en la respuesta de `verificar-codigo/`
```json
{ "id": 1, "email": "...", "rut": "", "nombre_completo": "...", "rol": "ESTUDIANTE",
  "carrera": CarreraMini | null, "area": Mini | null, "sede": Mini | null }
```

### Catálogos
- `GET /api/catalogos/carreras/` → `[CarreraMini + "extensiones_material"]` (como hoy).
- **Nuevo** `GET /api/catalogos/tipos/` → `[{ "id": "TESIS", "nombre": "Tesis" }, { "id": "PROYECTO_TITULO", "nombre": "Proyecto de título" }, { "id": "INFORME_PRACTICA", "nombre": "Informe de práctica" }]` (generado desde los `choices` del modelo).
- `GET /api/catalogos/profesores-guia/` → `["Ana Pérez", ...]` (lista de strings, sin cambios).

### Listado `GET /api/tesis/` (paginado `{count, next, previous, results}`)
```json
{ "id": 7, "titulo": "...", "resumen": "...(≤280)", "autores": ["Nombre 1", "Nombre 2"],
  "carrera": CarreraMini, "anio": 2025, "tipo": { "id": "TESIS", "nombre": "Tesis" },
  "profesor_guia": "Ana Pérez", "palabras_clave": ["web", "educación"],
  "num_paginas": 7, "tiene_repositorio": true }
```

### Detalle `GET /api/tesis/{id}/` — también usado en cada item de `mis-tesis/` y `pendientes/`
```json
{ "id": 7, "titulo": "...", "resumen": "...", "palabras_clave": ["web", "educación"],
  "tipo": { "id": "TESIS", "nombre": "Tesis" }, "anio": 2025, "semestre": 1,
  "carrera": CarreraMini, "sede": Mini, "profesor_guia": "...",
  "estado": "EN_REVISION", "estado_nombre": "En revisión", "observacion_revision": "",
  "subido_por": UsuarioMini, "revisado_por": UsuarioMini | null,
  "fecha_publicacion": "...", "num_paginas": 7, "tamano_bytes": 12345, "creado": "...", "actualizado": "...",
  "autores": [{ "nombre_completo": "...", "email": "..." }],
  "materiales": [{ "id": 3, "tipo": "REPOSITORIO", "titulo": "Repositorio", "descripcion": "",
                   "url": "https://github.com/..." /* omitido si restringido */,
                   "solo_carrera": true, "restringido": false, "creado": "..." }],
  "pdf": "/api/tesis/7/pdf/",
  "puede_editar": false, "puede_revisar": false, "puede_reenviar": false }
```
- `puede_editar` = `permisos.edita(usuario, tesis)`.
- `puede_revisar` = `permisos.revisa(usuario, tesis) and tesis.estado == EN_REVISION`.
- `puede_reenviar` = el usuario es autor/subió la tesis y está en BORRADOR o RECHAZADA.

### Escritura `POST /api/tesis/` y `PATCH /api/tesis/{id}/` (multipart)
| Campo | Formato |
|---|---|
| `titulo`, `resumen`, `profesor_guia` | texto |
| `tipo` | código (`TESIS`, …) |
| `carrera` | id |
| `sede` | id **opcional**: si no viene, usar `usuario.sede`; si el usuario no tiene sede y hay **una sola** sede activa, usar esa; si no, error de validación en `sede` |
| `anio`, `semestre` | número |
| `palabras_clave` | aceptar **string separado por comas** (`"iot, web"`) **o** JSON de lista (`'["iot","web"]'`). Normalizar: trim, quitar vacíos, quitar duplicados sin importar mayúsculas, guardar como `"iot,web"` |
| `autores` | JSON `[{"nombre_completo": "...", "email": "..."}]` (como hoy) |
| `pdf` | archivo (obligatorio al crear) |
| `repositorio_url` | URL GitHub opcional (como hoy) |
| `publicar` | `"true"/"false"` (como hoy) |

La respuesta de `POST`/`PATCH` es el **detalle** del contrato.

### Autorizados `GET /api/admin/autorizados/`
Cada item en lectura: `carrera`: CarreraMini | null, `area`: Mini | null, `sede`: Mini | null (en escritura siguen aceptando IDs). Implementarlo en `to_representation` del `AutorizadoSerializer`.
