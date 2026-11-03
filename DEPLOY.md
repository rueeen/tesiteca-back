# Deploy en PythonAnywhere · cuenta gratuita de rvavalencia

API: **https://rvavalencia.pythonanywhere.com**. Frontend: **https://tesiteca.netlify.app**. Proyecto: `/home/rvavalencia/tesiteca-back`.

Esta instalación usa **una web app WSGI con un worker**, sin WebSockets ni Redis. Mantener `NOTIFICACIONES_WS=False`: las notificaciones están en SQLite y llegan al frontend por polling. La cuenta tiene **512 MiB de disco en total**, salida a internet restringida y solo permite SMTP de Gmail. No dispone de tareas programadas en las cuentas gratuitas nuevas; renovar y mantener la app manualmente cada mes.

## 1. Preparar desde una consola Bash

```bash
cd ~
git clone https://github.com/rueeen/tesiteca-back.git
cd ~/tesiteca-back
python3.12 -m venv ~/.virtualenvs/tesiteca
source ~/.virtualenvs/tesiteca/bin/activate
pip install --no-cache-dir -r requirements.txt
cp .env.produccion.example .env
chmod 600 .env
nano .env
```

Elegir **la misma versión Python 3.12 o superior** en el virtualenv y en la pestaña Web. Si el repositorio ya existe, conservar `.env` y usar el procedimiento de actualización de abajo en lugar de volver a clonarlo.

Completar en `.env`:

- `SECRET_KEY`: generar con `python -c "import secrets; print(secrets.token_urlsafe(50))"`.
- `NETLIFY_PROXY_SECRET`: generar con `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Debe ser idéntico a `TESITECA_PROXY_SECRET` del frontend Netlify.
- `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` y `DEFAULT_FROM_EMAIL`: cuenta Gmail dedicada y su contraseña de aplicación. El remitente debe usar la misma dirección Gmail.

No versionar, enviar a logs ni compartir estos valores. La plantilla tiene los dominios reales, `EXIGIR_PROXY_NETLIFY=True`, `NOTIFICACIONES_WS=False`, límites de subida de 20 MiB y `SEED_ADMIN_EMAIL=rvalencia@inacap.cl`. No usar la plantilla de desarrollo en producción. Las variables del proceso tienen prioridad sobre `.env`.

Para Gmail: activar la verificación en dos pasos de la cuenta Google y generar una **contraseña de aplicación de 16 caracteres** en Cuenta Google → Seguridad → Contraseñas de aplicaciones. No usar la contraseña normal. La cuenta gratuita de PythonAnywhere no permite SMTP institucional; mantener `smtp.gmail.com:587`, TLS y `EMAIL_TIMEOUT=10`.

```bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py seed_demo
python manage.py crear_admin rvalencia@inacap.cl
python manage.py probar_correo rvalencia@inacap.cl
python manage.py verificar_deploy
```

`seed_demo` crea sede, área, carreras y el ADMIN en la lista blanca. Agregar `--con-ejemplos` **solo para una demo**; genera PDFs que consumen cuota. `crear_admin` pide nombre y contraseña con entrada privada y habilita el primer acceso ADMIN, también a `/admin/`. El login de la API usa contraseña; registro, verificación de correo y aprobación preceden al primer acceso. La lista blanca funciona como preaprobación. Revisar también spam tras `probar_correo`. El comando muestra host, puerto y usuario, nunca la contraseña. `verificar_deploy` marca ✔/✘ y termina con código 1 ante fallos críticos. También se puede ejecutar `python manage.py check --deploy`: los avisos sobre HSTS para subdominios/preload requieren decidir la política del dominio y no se silencian.

## 2. Crear la web app WSGI

Pestaña **Web → Add a new web app → Manual configuration** (no elegir el asistente Django). Seleccionar la versión de Python del virtualenv.

- **Source code:** `/home/rvavalencia/tesiteca-back`
- **Virtualenv:** `/home/rvavalencia/.virtualenvs/tesiteca`
- **WSGI configuration file:** reemplazar su contenido completo por:

```python
import os
import sys

path = "/home/rvavalencia/tesiteca-back"
if path not in sys.path:
    sys.path.insert(0, path)
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

En **Static files**, agregar solamente:

| URL | Directorio |
|---|---|
| `/static/` | `/home/rvavalencia/tesiteca-back/staticfiles` |

**No crear ningún mapeo hacia `private_media`, ni como static ni como media pública.** Los PDFs se sirven exclusivamente mediante vistas autenticadas.

Activar **Force HTTPS** y pulsar **Reload**. La configuración también habilita cookies seguras y redirección HTTPS. Verificar HTTPS antes de mantener HSTS activo durante un año; no activar políticas para subdominios o preload sin revisarlas.

## 3. Proxy firmado y verificación

Si cambias el nombre del sitio en Netlify, actualiza `FRONTEND_URL`, `NETLIFY_SITE_URL`, `CSRF_TRUSTED_ORIGINS` y `WS_ALLOWED_ORIGINS` en `.env` y presiona **Reload**; si no, el proxy responde 403.

Configurar en Netlify el proxy de `/api/*` hacia `https://rvavalencia.pythonanywhere.com/api/*`, **con firma de proxy** usando la variable `TESITECA_PROXY_SECRET` (consultar la configuración y README del frontend). No enviar ese secreto al bundle público del navegador. El valor debe coincidir con `NETLIFY_PROXY_SECRET` del backend.

Netlify agrega `x-nf-sign`, un JWS HS256 con emisor `netlify`, expiración obligatoria, `site_url=https://tesiteca.netlify.app` y `deploy_context=production`. El backend admite 30 segundos de desfase. Solo después de validar la firma confía en `x-nf-client-connection-ip`. Sin firma válida usa `REMOTE_ADDR` y, al exigir proxy, bloquea la API excepto salud. No registrar `x-nf-sign` ni el secreto. **TRUSTED_IP_HEADER fue eliminado**; no habilitar confianza directa en cabeceras de IP.

Comprobar desde el navegador:

1. `https://rvavalencia.pythonanywhere.com/api/salud/` → `estado: ok`, `debug: false`, `via_proxy: false`, `notificaciones_ws: false`, `correo: smtp`, `base_datos: ok`. `version` muestra el hash corto Git o `APP_VERSION` si no hay Git (por defecto `dev`). Salud es público y limitado a 30/min; no muestra secretos.
2. `https://rvavalencia.pythonanywhere.com/api/tesis/` directo → **403**, `Acceso solo a través del sitio oficial`. Esa es la señal de que el bloqueo funciona.
3. `https://tesiteca.netlify.app/api/salud/` → `via_proxy: true` y la misma versión del backend. Si aparece false, corregir el firmado antes de abrir el sistema.
4. Login desde el frontend: contraseña correcta, cuenta ACTIVA, cookie httpOnly/Strict, renovación y cierre de sesión. Refresh sin cookie devuelve 204; cookie inválida devuelve 401. Admin permanece accesible directamente en `https://rvavalencia.pythonanywhere.com/admin/` y CSRF permite ambos dominios.
5. Comprobar que las respuestas API llevan `Cache-Control: no-store, private` y `Vary` incluye Authorization y Cookie. El PDF conserva `Cache-Control: no-store`. No configurar reglas de Netlify que reemplacen esas cabeceras con caché pública.

La cookie de refresh es first-party porque el navegador usa el mismo origen del frontend. CORS queda vacío en producción. Netlify corta las peticiones de proxy a los **26 segundos**: los límites de 20 MiB reducen presión, pero no garantizan que PDFs complejos terminen dentro del plazo. No instalar WebSockets en este plan.

## 4. Rutina mensual

1. Pestaña Web → botón **Run until 1 month from today**. Sin renovación la app se desactiva.
2. En consola:

```bash
cd ~/tesiteca-back
source ~/.virtualenvs/tesiteca/bin/activate
python manage.py mantenimiento
```

El comando elimina tokens JWT expirados, intentos de login de más de 30 días y cuentas sin verificar de más de siete días, tickets vencidos/usados, **archivos** de importación de más de 30 días (conserva el registro del lote), y notificaciones **leídas** de más de 180 días. No elimina tesis ni notificaciones pendientes de leer. Es idempotente.

Muestra tamaños de archivos privados, SQLite y virtualenv, su suma y un aviso por encima de 400 MiB. La cuota de 512 MiB también incluye código, cachés y otros archivos: revisar el uso real en **Files**. Si hay caché pip antigua, ejecutar `pip cache purge`. Usar `--no-cache-dir` al instalar. Mantener respaldos de SQLite y archivos privados fuera de la cuenta, con acceso protegido por los datos personales que contienen.

## 5. Actualizar después de un merge

```bash
cd ~/tesiteca-back
git pull
source ~/.virtualenvs/tesiteca/bin/activate
pip install --no-cache-dir -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py verificar_deploy
```

Después pulsar **Reload** en Web y volver a comprobar salud directa y vía Netlify. Conservar `.env`. `pip install` no elimina paquetes antiguos: si se reutiliza un virtualenv que tenía ASGI/Daphne, recrearlo limpio con la misma versión Python y solo `requirements.txt` para recuperar ese espacio. Detener la app o coordinar una ventana antes de sustituir su virtualenv.

## 6. Problemas comunes

| Síntoma | Revisar |
|---|---|
| 502/504 desde Netlify | App expirada o recargando; renovar/Reload y consultar logs. También puede superarse el límite de 26 segundos. |
| `DisallowedHost` | `ALLOWED_HOSTS=rvavalencia.pythonanywhere.com`. |
| 403 en `/api/` desde Netlify | Secretos iguales, firma HS256, contexto production, URL del sitio exacta y expiración. Las vistas previas de Netlify quedan rechazadas deliberadamente. |
| 403 en refresh/logout o admin | Origen permitido en CSRF; refresh/logout requieren `X-Requested-With: XMLHttpRequest`. |
| No llegan enlaces de verificación/recuperación | `probar_correo`, spam, contraseña de aplicación y cuenta Gmail; comprobar que el backend no esté en consola. |
| `Disk quota exceeded` | `mantenimiento`, Files, `pip cache purge`; revisar PDFs y respaldos. |
| Versión de salud antigua | Actualizar checkout y pulsar Reload; la versión Git se obtiene al arrancar el proceso. |

Logs: pestaña **Web → Error log / Server log**. No copiar secretos ni firmas a tickets de soporte.

## Dependencias y ampliación futura

- `requirements.txt`: WSGI gratuito; incluye Channels porque lo importa el servicio de notificaciones, pero **no** incluye Uvicorn, channels-redis ni Daphne.
- `requirements-asgi.txt`: añade Uvicorn y channels-redis para un futuro plan con ASGI.
- `requirements-dev.txt`: añade Daphne para importar `channels.testing` y ejecutar **todas** las pruebas. No es la instalación de producción.

Para desarrollo: `pip install -r requirements-dev.txt && python manage.py test`. En un futuro plan con dos apps WSGI/ASGI, instalar la variante ASGI y compartir base de datos y Redis. `InMemoryChannelLayer` no comunica procesos separados. Las cuentas gratuitas de esta guía solo usan polling y mantenimiento mensual manual.

Validación local de esta preparación (Linux, Python 3.12, virtualenv nuevo, solo `requirements.txt`): **site-packages 113,71 MB / 108,45 MiB ocupados en disco** (`du -sk`: 111048 KiB), inferior a 135 MB. La suma de tamaños de archivos es 83,80 MB / 79,92 MiB; la diferencia corresponde a la asignación de bloques del sistema de archivos. El tamaño puede variar con la plataforma y las dependencias transitivas. La suite completa se ejecutó desde otro virtualenv limpio con `requirements-dev.txt`.

En producción la API solo ofrece JSON. Usar `Accept: application/json` o `*/*`; una petición que acepte exclusivamente `text/html` recibe 406 en JSON, nunca la interfaz navegable de DRF. Con `DEBUG=True` la API navegable permanece habilitada para desarrollo.


## Actualizar a cuentas con contraseña, períodos y sedes

Respaldar SQLite y archivos privados antes de migrar. Las cuentas activas existentes se conservan como ACTIVA y con correo verificado. Quienes ingresaban con el flujo anterior no tienen contraseña utilizable: deben usar **Olvidé mi contraseña**. No se envía una contraseña por correo. Las referencias al modelo eliminado solo permanecen en las migraciones históricas de actualización.

```bash
cd ~/tesiteca-back
git pull
source ~/.virtualenvs/tesiteca/bin/activate
pip install --no-cache-dir -r requirements.txt
python manage.py migrate
python manage.py crear_admin rvalencia@inacap.cl
python manage.py verificar_deploy
```

Después pulsar **Reload** y desplegar el frontend compatible. La migración renombra el campo de período conservando sus valores, normaliza resúmenes y configura nivel/duración de IEI y AP. Confirmar la duración de AP con la malla vigente. Usuarios no ADMIN necesitan sede; si una instalación antigua tiene usuarios sin sede y varias sedes activas, asignarla antes de migrar para evitar adjudicarles una sede incorrecta.

Solo Arica se crea automáticamente. El propietario carga las sedes oficiales con `python manage.py importar_sedes sedes.csv` (columnas `nombre,ciudad,region,orden`) o mediante el panel ADMIN. `docs/sedes_ejemplo.csv` contiene solo el formato de Arica. Las regiones pueden indicarse por nombre o número romano. `VISIBILIDAD_ENTRE_SEDES=True` permite a estudiantes ver publicaciones de su carrera en otras sedes; coordinadores/directores conservan alcance de sede.

SMTP solo se utiliza para enlaces de verificación (48 h) y recuperación (1 h), más la prueba administrativa explícita. No se envían correos al aprobar o rechazar. Mantener `NOTIFICAR_APROBACION_POR_CORREO=False`; el aviso de solicitudes llega por polling. El mantenimiento mensual limpia también intentos de login y cuentas pendientes de verificación antiguas.
