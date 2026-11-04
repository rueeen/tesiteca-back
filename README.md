# Tesiteca · Biblioteca de Tesis INACAP

Django 5.2, DRF, SimpleJWT y SQLite. Python 3.11+ en desarrollo; Python 3.12+ en la instalación de PythonAnywhere documentada en [DEPLOY.md](DEPLOY.md). PDFs privados con marca fija y por lector, revisión editorial, permisos por carrera/área y sede. La cuenta gratuita usa polling, un worker y proxy Netlify firmado.

## Instalación y actualización

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# Completar SECRET_KEY con un valor generado localmente.
python manage.py migrate
python manage.py seed_demo
python manage.py crear_admin rvalencia@inacap.cl
python manage.py runserver
```

No sobrescribir un `.env` existente ni versionar secretos, cookies, SQLite o archivos privados. Producción WSGI instala **solo `requirements.txt`**. `requirements-asgi.txt` añade Uvicorn/Redis para planes compatibles; `requirements-dev.txt` añade Daphne para todas las pruebas.

El acceso ahora usa **contraseña**. Los usuarios que ingresaban con el flujo anterior conservan sus datos y pasan a ACTIVA si estaban activos. Quienes no tienen contraseña utilizable deben usar **Olvidé mi contraseña**. No se genera ni publica una contraseña por defecto. El administrador inicial se prepara con `crear_admin`, que valida correo `@inacap.cl`, pide nombre y contraseña de forma privada, registra la aprobación y envía el enlace de correo. Solo después de validarlo habilita acceso, también a `/admin/`. `--sin-verificar` es una excepción de emergencia explícita y emite una advertencia.

Antes de actualizar producción respaldar SQLite y archivos privados. Las migraciones conservan usuarios, tesis, autorías y archivos; renombran el campo académico anterior a `periodo` y normalizan resúmenes. Los identificadores del modelo de acceso retirado permanecen exclusivamente en las migraciones históricas necesarias para actualizar instalaciones anteriores.

## Flujo de cuentas

1. Registro con correo institucional, RUT chileno válido, sede y contraseña de al menos 10 caracteres. Estudiantes `@inacapmail.cl` solicitan solo ESTUDIANTE; funcionarios `@inacap.cl`, COORDINADOR o DIRECTOR. ADMIN nunca se solicita.
2. Un correo de verificación (48 h, un solo uso). Si `PREAPROBACION_LISTA_BLANCA=True` y hay una entrada activa en la lista blanca, queda preaprobado; de lo contrario pasa a aprobación y se notifica en la app a los revisores correspondientes.
3. Coordinador: estudiantes de su carrera y sede. Director: estudiantes/coordinadores de su área y sede. ADMIN: alcance nacional y único aprobador de DIRECTOR. Si un director no indicó carrera y existe más de un área, ADMIN debe seleccionar una carrera para determinar su área al aprobar.
4. El login correcto de una cuenta ACTIVA devuelve access y usuario. No envía correo. Una solicitud rechazada puede volver a presentarse sin repetir la verificación de correo.
5. La recuperación por correo dura una hora, solo para cuentas activas. Restablecer invalida los refresh anteriores y elimina bloqueos por intentos. El cambio autenticado exige contraseña actual y rota la sesión.

Correos de negocio: solo verificación y recuperación, con texto y HTML. En desarrollo se imprimen en consola; en producción usar Gmail SMTP según [DEPLOY.md](DEPLOY.md). No se envían correos al aprobar/rechazar cuentas ni tesis; `NOTIFICAR_APROBACION_POR_CORREO=False` reserva una futura decisión. `probar_correo` es una herramienta administrativa de diagnóstico.

Límites: registro 5/h por IP; login 20/min por IP y bloqueo tras cinco fallos por email en 15 minutos; verificación tres envíos por email cada 24 h; recuperación tres por email cada hora. Las respuestas de registro, reenvío y recuperación son genéricas; los errores de validación son por campo. Los estados solo se revelan después de verificar la contraseña.

## Contrato de la API

### Cuentas

| Método y ruta | Body | Respuesta |
|---|---|---|
| `POST /api/auth/registro/` | `{email, password, password2, nombre_completo, rut, carrera, sede, rol_solicitado?, mensaje?}` | 201 `{detail}` genérico; 400 por campo |
| `POST /api/auth/verificar-correo/` | `{token}` | 200 `{estado: "ACTIVA" | "PENDIENTE_APROBACION"}`; 400 `{detail}` |
| `POST /api/auth/reenviar-verificacion/` | `{email}` | 200 `{detail}` genérico |
| `POST /api/auth/login/` | `{email, password}` | 200 `{access, usuario}` + cookie; 401 genérico; 403 `{codigo, detail, motivo?}`; 429 |
| `POST /api/auth/recuperar/` | `{email}` | 200 `{detail}` genérico |
| `POST /api/auth/restablecer/` | `{uid, token, password, password2}` | 200 `{detail}`; 400 |
| `POST /api/auth/cambiar-password/` | `{actual, nueva, nueva2}` (JWT) | 200 `{access}` + cookie nueva |
| `POST /api/auth/refresh/` | Cookie, ignora body | 200 `{access, usuario}` + cookie rotada; sin cookie 204 sin body; cookie inválida 401 y se elimina |
| `POST /api/auth/logout/` | Cookie | 204, revoca y elimina cookie, incluso con access vencido |
| `GET /api/auth/me/` | JWT | Datos de usuario |

Códigos 403: `correo_no_verificado`, `pendiente_aprobacion`, `rechazada` (con motivo), `desactivada`. El usuario contiene `id, email, rut, nombre_completo, rol, estado_cuenta, carrera, area, sede`; las relaciones se anidan y pueden ser null según el rol.

Access solo en memoria; refresh solo en cookie httpOnly, SameSite=Strict, Path=/api/auth/, Secure en producción. No guardar tokens en localStorage ni incluirlos en URLs. Refresh/logout exigen `X-Requested-With: XMLHttpRequest`; Origin, si viene, debe pertenecer a `CSRF_TRUSTED_ORIGINS`. Usar `credentials: "include"`. Son 30/min por IP. La sesión se restaura con una llamada a refresh; centralizar renovaciones concurrentes. Desactivar la lista blanca desactiva la cuenta y revoca sus refresh. La recuperación invalida los enlaces usados al cambiar el hash de contraseña.

### Solicitudes

- `GET /api/solicitudes/?estado=PENDIENTE|APROBADA|RECHAZADA&carrera=&sede=&search=`: paginación `{count,next,previous,results}`.
- Cada elemento: `{id, usuario:{id,email,nombre_completo,rut}, rol_solicitado, carrera, sede, mensaje, estado, motivo_rechazo, creada, revisada_por, revisada_en, puede_cambiar_rol}`.
- `GET /api/solicitudes/resumen/` → `{pendientes}`.
- `POST /api/solicitudes/{id}/aprobar/` con `{rol?,carrera?,sede?}` → item actualizado. Solo ADMIN puede cambiar lo solicitado.
- `POST /api/solicitudes/{id}/rechazar/` con `{motivo}` obligatorio, máximo 300 caracteres.

Las solicitudes pendientes pueden aprobarse antes de validar el correo: permanecen en PENDIENTE_VERIFICACION. En el historial APROBADA también aparecen esas cuentas; cada item añade `correo_validado` y `estado_cuenta`. Se conserva historial APROBADA/RECHAZADA, siempre limitado al ámbito del aprobador. Aprobar actualiza la lista blanca. Importar un preaprobado cuyo usuario ya verificó y está pendiente aprueba automáticamente; no habilita cuentas que aún no verificaron correo.

### Catálogos y objetos

- `CarreraMini`: `{id,nombre,codigo,area,permite_repositorio,nivel_formacion:{id,nombre},duracion_semestres}`.
- `SedeMini`: `{id,nombre,ciudad,region:{id,nombre}}`.
- `UsuarioMini`: `{id,nombre_completo,email}`.
- Catálogos de registro públicos: sedes, carreras, regiones y niveles (siguen pasando por el proxy firmado en producción).
- `GET /api/catalogos/sedes/`: activas, por `orden`, de norte a sur.
- `GET /api/catalogos/regiones/`: 16 regiones de norte a sur, IDs romanos; Metropolitana usa `RM` (el CSV también acepta `XIII`).
- `GET /api/catalogos/niveles/`: TECNICO («Técnico de Nivel Superior»), PROFESIONAL («Profesional»), INGENIERIA («Ingeniería»).
- `GET /api/catalogos/carreras/`: activas, CarreraMini más `extensiones_material`.
- `GET /api/catalogos/areas/`, `tipos/`, `anios/`, `profesores-guia/`: catálogos autenticados. Profesores son strings.
- `GET /api/catalogos/tipos/` devuelve exactamente, en este orden: `[{"id":"PROYECTO_TITULO","nombre":"Proyecto de título"},{"id":"PROYECTO_INTEGRADO","nombre":"Proyecto integrado"}]`. Son los únicos códigos aceptados en POST/PATCH y en el filtro `tipo`; valores distintos devuelven 400 en español. La migración convierte los códigos antiguos a `PROYECTO_TITULO` sin modificar los demás datos.
- `GET/POST /api/admin/sedes/`, `PATCH /api/admin/sedes/{id}/`: solo ADMIN; `nombre,ciudad,region,orden,activa`.

La carrera tiene duración de 2–10 semestres, editable en Django admin. El seed configura IEI como INGENIERIA/8 y AP como TECNICO/4; **confirmar duración de AP con la malla vigente**.

### Biblioteca, período y resumen

`GET /api/tesis/` lista solo PUBLICADAS visibles. Estudiante: su carrera en todas las sedes por defecto, más las propias según estado. `VISIBILIDAD_ENTRE_SEDES=False` limita las publicaciones a su sede. Coordinador: carrera+sede; director: área+sede; ADMIN: nacional.

Búsqueda `search` en título, resumen, palabras, autores y guía; `en_contenido=true` añade texto PDF. Filtros: `carrera,sede,region,nivel_formacion,tipo,anio,anio_desde,anio_hasta,profesor_guia,palabra_clave,tiene_repositorio`. Orden por año, título o fecha de publicación (prefijo `-` para descendente). Paginación de 12, máximo 48 con `page_size`.

Listado: `id,titulo,resumen,autores` (nombres), `carrera` (objeto), `sede: SedeMini` (`id,nombre,ciudad,region:{id,nombre}`), `anio,tipo` (objeto), `periodo,periodo_texto,profesor_guia,palabras_clave` (lista), `num_paginas,tiene_repositorio`. El resumen de máximo 280 caracteres se corta por palabra y termina en «…» si se recorta.

Detalle y elementos de `mis-tesis/`/`pendientes/`: además incluye resumen completo, sede anidada, estado/estado_nombre, observación, subido_por/revisado_por anidados, fechas, autores `{nombre_completo,email}`, materiales, `pdf` protegido y flags `puede_editar,puede_revisar,puede_reenviar`.

**El período es el semestre del año académico**, no el nivel de carrera. Escritura `periodo=1|2`; lectura `periodo:{id:1,nombre:"Primer semestre"}` y `periodo_texto:"2026 · Primer semestre"` (segundo si 2). Los registros antiguos sin período conservan null y muestran el año en `periodo_texto`.

`POST /api/tesis/` y `PATCH /api/tesis/{id}/` aceptan multipart: `titulo,resumen,palabras_clave,tipo,anio,periodo,carrera,sede,profesor_guia,pdf,autores,repositorio_url?,publicar?`. PDF obligatorio al crear. Sede por defecto la del usuario; si no tiene sede, solo puede omitirse cuando hay una única activa. Usuarios no ADMIN no pueden subir a otra sede. Autores es JSON `[{nombre_completo,email}]`; palabras clave acepta CSV o JSON de strings, recorta espacios y deduplica sin distinguir mayúsculas.

El resumen normaliza saltos del PDF, reúne palabras cortadas con guion, mantiene párrafos/viñetas y colapsa espacios. Se aplica al escribir y mediante migración a las tesis existentes. La creación del PDF y su marca se revierte ante fallos y se limpian archivos nuevos.

Acciones: `/api/tesis/mis-tesis/`, `pendientes/`, `/{id}/aprobar/`, `rechazar/` con observación, `reenviar/`. El autor solo edita/elimina BORRADOR o RECHAZADA. Los revisores reciben avisos solo de tesis de su sede. Materiales `solo_carrera` siguen restringidos por carrera (y por área/sede del director), ocultando URL/descarga cuando no hay permiso.

## Lista blanca y sedes oficiales

### Excel/CSV: solo estudiantes

`GET /api/admin/autorizados/plantilla/` descarga una plantilla XLSX con las hojas **Estudiantes**, **Instrucciones**, **Carreras** y **Sedes**. Primera fila exacta:

```csv
email,rut,nombre_completo,carrera_codigo,sede
estudiante@inacapmail.cl,12345678-5,Estudiante Demo,IEI,Arica
```

`POST /api/admin/autorizados/importar/` recibe CSV UTF-8 o XLSX en `archivo`, máximo 5 MB/10000 filas. El rol siempre es ESTUDIANTE y el área se deriva de la carrera. El correo debe ser `@inacapmail.cl`, carrera y sede son obligatorias, y RUT es opcional pero debe tener dígito verificador válido si se informa. La sede se busca sin distinguir mayúsculas ni tildes. Se hace upsert por email; los errores por fila no detienen las válidas. Se conserva la columna opcional `activo` al final para activar/desactivar, sin cambiar el rol.

Una fila de funcionario se rechaza y un funcionario existente nunca se modifica desde Excel. **Las plantillas antiguas con `rol` o `area` se rechazan por completo con 400**: «La plantilla cambió: descarga la nueva desde el panel». No se convierten ni se adivinan columnas.

El alcance sigue siendo carrera+sede para coordinadores, área+sede para directores y nacional para ADMIN. La lista blanca es preaprobación con `PREAPROBACION_LISTA_BLANCA=True`; siempre se exige validar el correo.

### Formulario de funcionarios

`POST /api/admin/funcionarios/` acepta:

```json
{"email":"coordinador@inacap.cl","nombre_completo":"Nombre completo","rut":"12345678-5","rol":"COORDINADOR","carrera":1,"sede":1}
```

Correo obligatorio `@inacap.cl`. RUT opcional y validado. COORDINADOR requiere carrera, de la cual se deriva el área. DIRECTOR requiere `area` y no tiene carrera. ADMIN no se crea aquí: usar `crear_admin`.

ADMIN puede registrar funcionarios de cualquier sede. DIRECTOR solo puede registrar o modificar coordinadores de carreras de su área en su sede; no puede reasignar un funcionario que ya pertenece a otro ámbito. COORDINADOR recibe 403.

Respuesta 201: `{autorizado, cuenta: {existe:true, estado_cuenta} | null, siguiente_paso}`. **El alta no envía correo.** Si existe cuenta, registra la aprobación y actualiza el rol/carrera/área/sede; con correo validado queda ACTIVA, sin él permanece PENDIENTE_VERIFICACION. Si cambia el rol de una cuenta activa, se revocan sus refresh. Si no existe cuenta, el funcionario entra a Solicitar acceso, crea su contraseña y valida el correo. Los datos activos de la lista blanca tienen prioridad sobre rol, carrera, área y sede elegidos en el formulario de registro. Con la preaprobación deshabilitada se conserva la revisión por el panel para nuevas cuentas.

### Listado y edición de autorizados

`GET /api/admin/autorizados/?tipo=estudiantes|funcionarios` filtra los registros; cada item añade `estado_cuenta` (null si no hay cuenta). Se conservan búsqueda y filtros por rol, carrera y activo. Los funcionarios de este filtro son coordinadores y directores.

`PATCH /api/admin/autorizados/{id}/`: solo ADMIN cambia rol y datos personales. El resto solo activa/desactiva en su ámbito; DIRECTOR también puede cambiar la carrera de un coordinador a otra de su área, manteniendo sede. Para pasar de ESTUDIANTE a un rol de funcionario el correo debe ser `@inacap.cl`. Desactivar revoca sesiones; reactivar no recupera refresh revocados. Los cambios de metadata se reflejan en las cuentas existentes y sus aprobaciones.

No hay una lista fija de sedes en código. Solo Arica se crea por seed. Cargar la lista oficial desde CSV o `/api/admin/sedes/`:

```bash
python manage.py importar_sedes docs/sedes_ejemplo.csv
# Para la lista oficial del propietario: python manage.py importar_sedes sedes.csv
```

Columnas exactas `nombre,ciudad,region,orden`. Región acepta nombre o número romano. Upsert por nombre en una transacción; se imprime el resumen. El ejemplo contiene únicamente Arica. Las sedes inactivas no aparecen en catálogos.

## PDFs, notificaciones y despliegue

PDFs en `PRIVATE_MEDIA_ROOT`, **nunca público ni static**. Validación de tamaño, firma, cifrado, SHA-256 único y extracción de texto. Marca fija con tamaño/rotación/origen de página y marca del lector con email, fecha e IP validada por proxy. `/api/tesis/{id}/pdf/` requiere JWT y devuelve inline/no-store/nosniff; `pdf-original/` solo ADMIN. Las marcas ayudan a la trazabilidad, no impiden capturas.

Notificaciones persistidas: `GET /api/notificaciones/?leida=false&desde_id=`, `resumen/`, `POST /{id}/leer/`, `leer-todas/`. Tipo nuevo `SOLICITUD_ACCESO`, enlace `/solicitudes`. Solo propias; polling no pierde datos. WS es opcional para planes compatibles: ticket de un solo uso/30 s en `/api/notificaciones/ticket/`, nunca JWT en query strings; orígenes permitidos y grupo por usuario. El plan gratuito mantiene `NOTIFICACIONES_WS=False`.

El proxy verifica HS256, emisor netlify, expiración, sitio y contexto production antes de confiar en la IP. `EXIGIR_PROXY_NETLIFY=True` bloquea `/api/*` directo excepto salud. La API añade no-store/private y Vary por sesión; producción solo JSON (Accept exclusivo de HTML da 406 JSON), desarrollo conserva API navegable. `GET /api/salud/` no expone secretos. Consultar [DEPLOY.md](DEPLOY.md) para Gmail, secretos, Netlify y mantenimiento mensual.

## Validación y demo

```bash
pip install -r requirements-dev.txt
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
python manage.py seed_demo --con-ejemplos
```

Pruebas con correo en memoria, PDFs temporales y una base anterior migrada en un proceso aislado. Se mantienen casos de JWT, importación, watermark, privacidad, proxy, revisión y notificaciones, adaptando el login retirado a contraseña.

Demo: demo1/demo2 estudiantes IEI; demo3 estudiante AP; demo4 coordinador AP; demo5 coordinador IEI; demo6 director del área; todos en `@inacapmail.cl` como fixtures ficticios heredados. Sus cuentas existentes ya validadas usan recuperación para establecer contraseña; los nuevos ejemplos quedan preaprobados y deben reenviar/validar el enlace antes de recuperar la contraseña. Solo las cuentas reales nuevas respetan la regla de dominio del registro. 15 tesis: 11 publicadas, 3 en revisión, 1 rechazada. Los ejemplos alternan Proyecto integrado (impares) y Proyecto de título (pares); el seed también actualiza ese campo en los ejemplos existentes sin regenerar sus PDFs. `--reset-ejemplos` reemplaza las tesis «Demo » y sus PDFs; no usar en producción sin revisar los datos que se van a eliminar.

## Regla de cuenta y actualización de marcas

ACTIVA requiere correo validado y una SolicitudAcceso APROBADA. Ambos pasos pueden ocurrir en cualquier orden; una aprobación previa se conserva hasta que se valide el enlace. Login, refresh y cambio de contraseña usan la misma regla (`is_active`, ACTIVA y fecha de verificación), sin consultar la lista blanca para decidir la sesión. La aprobación sincroniza el registro de autorizados; desactivarlo sigue revocando las sesiones. `mantenimiento` crea los autorizados faltantes de cuentas activas y muestra el total.

El admin de Django crea usuarios aprobados pero pendientes de verificación y envía un enlace; no permite activar una cuenta sin correo validado. Las nuevas cuentas de ORM/manager también parten pendientes, sin dar por verificado el correo. La migración conserva las cuentas legadas operativas con correo y aprobación registrados.

Las marcas usan el área visible CropBox después de normalizar rotación, tres diagonales con relleno oscuro/contorno blanco y rótulos sobre fondo blanco semiopaco. `python manage.py regenerar_marcas` actualiza todas desde los originales; `--id N` selecciona una. Muestra progreso, continúa ante errores y comparte la regeneración segura con el admin, eliminando el archivo marcado anterior solo después del commit. Ver [DEPLOY.md](DEPLOY.md) para la actualización.
