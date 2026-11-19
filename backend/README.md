# Backend del proyecto de Bases de Datos (Flask + MySQL)

**Integrante 3: Desarrollo Backend, Seguridad y CRUD.**

Este backend implementa los 4 MER del proyecto: **Seguridad y Auditoría**, **Nómina**, **Libros** y **Películas**. Está hecho para correr con **XAMPP** (MySQL/MariaDB, usuario `root` sin contraseña), igual que `ingesta_datos.py`.

---

## 1. Instalación y ejecución

1. Enciende **MySQL** en el panel de XAMPP.
2. Abre una terminal en esta carpeta e instala las dependencias:
   ```bash
   python -m venv venv
   venv\Scripts\activate            # Windows   (Linux/Mac: source venv/bin/activate)
   pip install -r requirements.txt
   ```
3. Crea la base, las tablas y el usuario administrador:
   ```bash
   python init_db.py --datos-ejemplo
   ```
   - Crea la base `proyecto_bd`, las 22 tablas, los roles y el usuario **admin / Admin123\***.
   - `--datos-ejemplo` carga los CSV de `datos_ejemplo/`. Los libros y películas de ejemplo son ficticios, tienen IDs desde 900001 y llevan "(Ejemplo)" en el título. Para cargar solo los datasets reales, omite esta opción.
   - `--reset` borra las tablas y las vuelve a crear.
4. Inicia la aplicación:
   ```bash
   python app.py
   ```
   Abre **http://127.0.0.1:5000** e inicia sesión con `admin` / `Admin123*`. Después cambia la contraseña.

Para usar otra base, usuario o contraseña de MySQL, copia `.env.example` como `.env` y edítalo.

---

## 2. Cómo se cumple cada tarea

| Tarea | Implementación | Archivos |
|---|---|---|
| **Entorno Flask + conexión robusta a MySQL** | SQLAlchemy con pool de conexiones. `pool_pre_ping` reconecta si se reinicia XAMPP y `pool_recycle` renueva las conexiones. Las transacciones hacen COMMIT o ROLLBACK automáticamente, todas las consultas usan parámetros (sin inyección SQL) y, si MySQL está apagado, se muestra una página de error clara. `/salud` indica el estado de la conexión. | `config.py`, `db.py`, `app.py` |
| **CRUD de todas las entidades** | CRUD genérico configurado desde los metadatos de cada tabla. Cubre catálogos, FK, PK compuesta (`liquidacion`) y relaciones N:M (`libro_autor`, `pelicula_genero`). Valida tipos y rangos, aplica reglas de negocio (fechas, ISBN, días 0-30) y traduce los errores de MySQL (duplicado, FK, CHECK) a mensajes en español. | `entidades.py`, `crud.py` |
| **Consultas dinámicas** | **a)** Cada listado tiene búsqueda libre, filtros por FK y N:M, filtros por rango (números y fechas), ordenamiento por cualquier columna, paginación y exportación a CSV. **b)** 9 reportes parametrizados: nómina por periodo, costo por dependencia, afiliaciones EPS/pensión/ARL, incapacidades y vacaciones por fechas, libros mejor calificados, autores con más libros, libros por editorial, películas por género y año, y películas por género y década. | `crud.py`, `consultas.py` |
| **Autenticación y validación** | Login, registro, cambio de contraseña y gestión de usuarios (ADMIN). Exige contraseña robusta (8+ caracteres, mayúscula, minúscula, número y símbolo). Tras **3 intentos fallidos** la cuenta queda bloqueada (`intentos_fallidos`, `activo`) y solo un ADMIN puede desbloquearla. El error es genérico ("usuario o contraseña incorrectos"), se crea una sesión nueva al entrar (evita la fijación de sesión), la sesión vence a los 30 minutos y todos los formularios tienen token CSRF. | `auth.py`, `seguridad.py`, `admin.py` |
| **Cifrado de contraseñas** | Hash **PBKDF2-SHA256** con sal y 600.000 iteraciones (`werkzeug.security`). La contraseña nunca se guarda en texto plano: solo `password_hash`. | `seguridad.py` |
| **Doble factor (Captcha)** | Captcha de imagen generado con Pillow. Funciona sin internet, la respuesta se guarda en el servidor, es de un solo uso y vence a los 5 minutos. Se valida **antes** de revisar la contraseña. Opcionalmente se puede usar **Google reCAPTCHA v2** (`CAPTCHA_MODO=recaptcha` + claves en `.env`). | `captcha.py` |
| **Roles y permisos** | **ADMIN**: todo, incluidos usuarios, roles y auditoría. **OPERADOR**: CRUD y cargas. **CONSULTA**: solo lectura y reportes. | `config.py` (`PERMISOS`) |
| **Auditoría** | Se registran el login (exitoso, fallido, bloqueado o con captcha incorrecto), el logout, los INSERT/UPDATE/DELETE con el antes y el después, las cargas, las exportaciones y los cambios de contraseña. Cada evento guarda usuario, IP y fecha. Se consulta con filtros en *Seguridad → Auditoría*. | `auditoria.py`, `admin.py` |
| **Carga de archivos desde la app** | Un usuario autenticado sube un CSV o XLSX con la estructura inicial. Reutiliza la lógica de `ingesta_datos.py`: limpieza, eliminación de duplicados internos, validación de FK, filtro de registros que ya existen e inserción padre → hijo. Además, todo ocurre en **una sola transacción**, cada fila rechazada queda con su motivo (descargable) y cada carga se guarda en `CARGA_ARCHIVO` con leídos, cargados, rechazados y estado. | `ingesta.py`, `cargas.py` |

---

## 3. Estructura de los archivos de carga

| Tipo | Columnas | Notas |
|---|---|---|
| **Nómina** | `codigo, nombre_completo, fecha_ingreso, sueldo, dependencia, cargo, eps, fondo_pension, arl, anio, mes, dias_trabajados, bonificacion, transporte` | Una fila = empleado + su liquidación del mes. Las columnas de liquidación son opcionales. Los catálogos que no existen se crean. |
| **Incapacidades / Vacaciones** | `codigo, fecha_inicio, fecha_fin, dias` | El empleado debe existir. Si `dias` está vacío, se calcula. |
| **Libros** (Goodreads `books.csv`) | `bookID, title, authors, average_rating, isbn, isbn13, language_code, num_pages, ratings_count, text_reviews_count, publication_date, publisher` | Los autores van separados por `/` y la fecha en M/D/AAAA. Los ISBN se leen como texto para no perder ceros. |
| **Películas** (MovieLens `movies.csv`) | `movieId, title, genres` | El año sale del título (`Toy Story (1995)`) y los géneros van separados por `|`. |

También se aceptan los nombres de columna del MER (`id_libro`, `titulo`, `autores`, `editorial`, `idioma`, `id_pelicula`, `anio`, `generos`, …). En la pantalla de carga se puede descargar una plantilla de cada tipo.

> Si los archivos iniciales del equipo tienen otros nombres de columna, basta con agregarlos al diccionario `ALIAS_*` correspondiente en `ingesta.py`.

---

## 4. Estructura del proyecto

```
app.py            Aplicación Flask (rutas base, errores, filtros)
config.py         Configuración (BD, sesión, captcha, permisos)
db.py             Conexión y pool a MySQL
init_db.py        Crea la base, las tablas, el admin y los datos de ejemplo
seguridad.py      Hash, política de contraseñas, roles, CSRF, cabeceras
captcha.py        Captcha local / reCAPTCHA
auth.py           Login, logout, registro, cambio de contraseña
admin.py          Usuarios y auditoría (ADMIN)
entidades.py      Metadatos de las tablas para el CRUD
crud.py           CRUD genérico + consultas dinámicas
consultas.py      Reportes parametrizados
ingesta.py        Motor de carga CSV/XLSX (evolución de ingesta_datos.py)
cargas.py         Pantallas de carga e historial
sql/schema.sql    DDL de los 4 MER + datos semilla
templates/        Vistas Jinja + Bootstrap 5
datos_ejemplo/    CSV de ejemplo / plantillas
tests/            Pruebas de integración (pytest)
```

## 5. Pruebas

Con MySQL encendido (usan una base aparte, `proyecto_bd_test`):
```bash
pip install pytest
python -m pytest -q tests
```
Prueban: login con captcha, captcha de un solo uso, CSRF, política de contraseñas, bloqueo tras 3 intentos y desbloqueo, permisos por rol, CRUD con PK simple, compuesta y N:M, integridad referencial, auditoría, reportes, exportación CSV y cargas con filas válidas e inválidas.
