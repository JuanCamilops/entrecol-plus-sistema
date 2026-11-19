import os
import re
import json
import calendar
import unicodedata
from datetime import datetime, date
import pandas as pd
import mysql.connector
from dotenv import load_dotenv

# Cargar variables de entorno desde backend/.env o .env en la raíz
load_dotenv(os.path.join("backend", ".env"))
load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "proyecto_integrador"),
    "charset": "utf8mb4",
}

RUTA_NOMINA = os.path.join("data_cruda", "Nomina.xlsx")
RUTA_MOVIES = os.path.join("data_cruda", "movies.dat")
RUTA_BOOKS = os.path.join("data_cruda", "Books.json")
BATCH_SIZE = 2500


# ==============================================================================
# UTILIDADES DE LIMPIEZA Y NORMALIZACIÓN
# ==============================================================================
def normalizar_texto_clave(texto):
    """Convierte nombres de columnas u hojas a minúsculas sin tildes ni espacios extra."""
    if texto is None:
        return ""
    s = str(texto).strip().lower()
    s = "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def limpiar_str(valor, max_len=None):
    if valor is None or pd.isna(valor):
        return None
    s = str(valor).strip()
    if s == "" or s.lower() in ("nan", "none", "null", "nat"):
        return None
    return s[:max_len] if max_len else s


def limpiar_codigo_empleado(valor):
    if valor is None or pd.isna(valor):
        return None
    s = str(valor).strip()
    if s.endswith(".0"):
        s = s[:-2]
    if not s or s.lower() in ("nan", "none", "null", "nat"):
        return None
    return s[:20]


def limpiar_monto(valor):
    if valor is None or pd.isna(valor):
        return 0.0
    try:
        limpio = str(valor).replace("$", "").replace(",", "").strip()
        return max(0.0, float(limpio)) if limpio else 0.0
    except ValueError:
        return 0.0


def parsear_fecha(valor):
    """Convierte múltiples formatos de fecha (Excel, Timestamp, NaT, strings) a date."""
    if valor is None or pd.isna(valor):
        return None
    if isinstance(valor, pd.Timestamp):
        return valor.date()
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor

    s = str(valor).strip()
    if not s or s.lower() in ("nan", "nat", "none", "null"):
        return None

    s = s.split(" ")[0]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue

    try:
        dt = pd.to_datetime(s, errors="coerce")
        return dt.date() if pd.notna(dt) else None
    except Exception:
        return None


def insertar_en_lotes(cursor, sql, datos, batch_size=BATCH_SIZE):
    for i in range(0, len(datos), batch_size):
        cursor.executemany(sql, datos[i : i + batch_size])

def obtener_o_crear_catalogo(cursor, tabla, col_id, col_nombre, valores):
    """Inserta valores únicos en tablas catálogo y retorna diccionario tolerante a mayúsculas/tildes."""
    unicos = sorted({v for v in valores if v})
    if unicos:
        sql_ins = f"INSERT IGNORE INTO {tabla} ({col_nombre}) VALUES (%s)"
        insertar_en_lotes(cursor, sql_ins, [(u,) for u in unicos])
    cursor.execute(f"SELECT {col_nombre}, {col_id} FROM {tabla}")
    mapa = {}
    for nombre_db, id_db in cursor.fetchall():
        mapa[nombre_db] = id_db
        mapa[nombre_db.lower()] = id_db
        mapa[normalizar_texto_clave(nombre_db)] = id_db
    return mapa


def buscar_id_catalogo(mapa, valor):
    return (
        mapa.get(valor)
        or mapa.get(valor.lower())
        or mapa.get(normalizar_texto_clave(valor))
    )

def buscar_columna(df, candidatos):
    """Encuentra la primera columna del DataFrame que coincida con alguno de los alias."""
    mapa = {normalizar_texto_clave(c): c for c in df.columns}
    for cand in candidatos:
        if cand in mapa:
            return mapa[cand]
    for cand in candidatos:
        for norm, orig in mapa.items():
            if cand in norm:
                return orig
    return None


# ==============================================================================
# 1. CARGA DE NÓMINA (Nomina.xlsx -> tablas de nómina)
# ==============================================================================
def cargar_nomina(conn):
    if not os.path.exists(RUTA_NOMINA):
        print(f"⚠️ No se encontró {RUTA_NOMINA}, saltando módulo de nómina.")
        return

    print("\n--- [1/3] Procesando Nomina.xlsx ---")
    excel = pd.ExcelFile(RUTA_NOMINA)
    hojas = excel.sheet_names
    print(f"Hojas detectadas en Excel: {hojas}")
    cursor = conn.cursor()

    # 1.1 Primera hoja: información general de empleados
    df_emp = pd.read_excel(RUTA_NOMINA, sheet_name=hojas[0])
    print(f"Columnas hoja empleados ({hojas[0]}): {list(df_emp.columns)}")

    col_id = buscar_columna(df_emp, ["codigo", "empleado_id", "id_empleado", "id", "cedula"])
    col_nom = buscar_columna(df_emp, ["nombre_del_empleado", "nombre_completo", "nombre", "empleado"])
    col_dep = buscar_columna(df_emp, ["dependencia", "departamento", "area"])
    col_car = buscar_columna(df_emp, ["cargo", "puesto", "rol"])
    col_ing = buscar_columna(df_emp, ["fecha_ingreso", "ingreso", "fecha_de_ingreso"])
    col_eps = buscar_columna(df_emp, ["eps", "salud"])
    col_arl = buscar_columna(df_emp, ["arl", "riesgos"])
    col_pen = buscar_columna(df_emp, ["pension", "fondo_pension", "afp"])
    col_sue = buscar_columna(df_emp, ["sueldo", "sueldo_base", "salario"])

    if not all([col_id, col_nom, col_dep, col_car]):
        raise ValueError(
            f"Faltan columnas obligatorias en {hojas[0]}. Detectadas: {list(df_emp.columns)}"
        )

    registros_emp = []
    deps, cargos, eps_set, arls, pensiones = set(), set(), set(), set(), set()

    for _, row in df_emp.iterrows():
        emp_id = limpiar_codigo_empleado(row[col_id])
        if not emp_id:
            continue

        nombre = limpiar_str(row[col_nom], 150)
        if not nombre:
            continue

        dep = limpiar_str(row[col_dep], 100) or "SIN DEPENDENCIA"
        car = limpiar_str(row[col_car], 100) or "SIN CARGO"
        eps_val = (limpiar_str(row[col_eps], 100) if col_eps else None) or "NO REGISTRA"
        arl_val = (limpiar_str(row[col_arl], 100) if col_arl else None) or "ARL Sura"
        pen_val = (limpiar_str(row[col_pen], 100) if col_pen else None) or "NO REGISTRA"

        f_ing = (parsear_fecha(row[col_ing]) if col_ing else None) or date(2024, 1, 1)
        sueldo = limpiar_monto(row[col_sue]) if col_sue else 0.0

        deps.add(dep)
        cargos.add(car)
        eps_set.add(eps_val)
        arls.add(arl_val)
        pensiones.add(pen_val)

        registros_emp.append((emp_id, nombre, dep, car, f_ing, eps_val, arl_val, pen_val, sueldo))

    map_dep = obtener_o_crear_catalogo(cursor, "departamento", "departamento_id", "nombre", deps)
    map_car = obtener_o_crear_catalogo(cursor, "cargo", "cargo_id", "nombre", cargos)
    map_eps = obtener_o_crear_catalogo(cursor, "eps", "eps_id", "nombre", eps_set)
    map_arl = obtener_o_crear_catalogo(cursor, "arl", "arl_id", "nombre", arls)
    map_pen = obtener_o_crear_catalogo(cursor, "fondo_pension", "fondo_pension_id", "nombre", pensiones)

    filas_empleado = [
        (
            emp_id,
            nombre,
            map_dep[dep],
            map_car[car],
            f_ing,
            map_eps[eps_val],
            map_arl[arl_val],
            map_pen[pen_val],
            sueldo,
        )
        for (emp_id, nombre, dep, car, f_ing, eps_val, arl_val, pen_val, sueldo) in registros_emp
    ]

    sql_emp = """
        INSERT INTO empleado (
            empleado_id, nombre_completo, departamento_id, cargo_id,
            fecha_ingreso, eps_id, arl_id, fondo_pension_id, sueldo_base
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            nombre_completo = VALUES(nombre_completo),
            departamento_id = VALUES(departamento_id),
            cargo_id = VALUES(cargo_id),
            sueldo_base = VALUES(sueldo_base)
    """
    insertar_en_lotes(cursor, sql_emp, filas_empleado)
    conn.commit()
    print(f"✅ Empleados cargados/actualizados: {len(filas_empleado)}")

    def asegurar_detalle_nomina(emp_id, anio, mes, dias_trab=30, dias_inc=0, dias_vac=0, bonif=0.0, aux=0.0):
        anio = int(anio)
        mes = int(mes)
        ultimo_dia = calendar.monthrange(anio, mes)[1]
        f_ini = date(anio, mes, 1)
        f_fin = date(anio, mes, ultimo_dia)

        cursor.execute(
            """
            INSERT IGNORE INTO periodo_nomina (anio, mes, fecha_inicio, fecha_fin)
            VALUES (%s, %s, %s, %s)
            """,
            (anio, mes, f_ini, f_fin),
        )
        cursor.execute(
            "SELECT periodo_id FROM periodo_nomina WHERE anio = %s AND mes = %s",
            (anio, mes),
        )
        periodo_id = cursor.fetchone()[0]

        dias_trab_int = int(min(30, max(0, round(float(dias_trab)))))
        dias_inc_val = max(0.0, float(dias_inc))
        dias_vac_val = max(0.0, float(dias_vac))

        cursor.execute(
            """
            INSERT INTO detalle_nomina (
                periodo_id, empleado_id, dias_trabajados, dias_incapacidad,
                dias_vacaciones, bonificacion, auxilio_transporte
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                dias_trabajados = VALUES(dias_trabajados),
                dias_incapacidad = VALUES(dias_incapacidad),
                dias_vacaciones = VALUES(dias_vacaciones),
                bonificacion = VALUES(bonificacion),
                auxilio_transporte = VALUES(auxilio_transporte)
            """,
            (periodo_id, emp_id, dias_trab_int, dias_inc_val, dias_vac_val, bonif, aux),
        )
        cursor.execute(
            "SELECT detalle_nomina_id FROM detalle_nomina WHERE periodo_id = %s AND empleado_id = %s",
            (periodo_id, emp_id),
        )
        return cursor.fetchone()[0]

    def registrar_novedad_unica(det_id, tipo_nov, f_ini, f_fin, obs):
        cursor.execute(
            """
            SELECT novedad_id FROM novedad_nomina
            WHERE detalle_nomina_id = %s AND tipo_novedad = %s AND fecha_inicio = %s
            """,
            (det_id, tipo_nov, f_ini),
        )
        if cursor.fetchone() is None:
            cursor.execute(
                """
                INSERT INTO novedad_nomina (
                    detalle_nomina_id, tipo_novedad, fecha_inicio, fecha_fin, observacion
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (det_id, tipo_nov, f_ini, f_fin, obs),
            )
            return 1
        return 0

    # 1.2 Hojas restantes: liquidaciones, incapacidades y vacaciones (Table 3)
    cursor.execute("SELECT empleado_id FROM empleado")
    empleados_validos = {str(r[0]).strip() for r in cursor.fetchall()}

    total_detalles = 0
    total_novedades = 0

    for sheet_name in hojas[1:]:
        df_hoja = pd.read_excel(RUTA_NOMINA, sheet_name=sheet_name)
        if df_hoja.empty:
            continue

        cols = {normalizar_texto_clave(c): c for c in df_hoja.columns}
        c_emp = cols.get("codigo") or buscar_columna(df_hoja, ["codigo", "empleado_id"])
        if not c_emp:
            continue

        c_dtrab = cols.get("numero_dias_trabajados_en_el_mes")
        c_dinc = cols.get("numero_dias_incapacidades_en_el_mes")
        c_v_ini = cols.get("fecha_de_inicio_de_vacaciones")
        c_v_fin = cols.get("fecha_terminacion_de_vacaciones")
        c_i_ini = cols.get("fecha_inicio_incapacidad")
        c_i_fin = cols.get("fecha_terminacion_incapacidad")
        c_bon = cols.get("bonificacion")
        c_aux = cols.get("transporte")
        c_obs_vac = cols.get("novedad_vacaciones")
        c_obs_inc = cols.get("novedad_incapacidad")

        for _, row in df_hoja.iterrows():
            emp_id = limpiar_codigo_empleado(row[c_emp])
            if not emp_id or emp_id not in empleados_validos:
                continue

            f_v_ini = parsear_fecha(row[c_v_ini]) if c_v_ini else None
            f_v_fin = parsear_fecha(row[c_v_fin]) if c_v_fin else f_v_ini
            f_i_ini = parsear_fecha(row[c_i_ini]) if c_i_ini else None
            f_i_fin = parsear_fecha(row[c_i_fin]) if c_i_fin else f_i_ini

            dias_vac = (
                ((f_v_fin - f_v_ini).days + 1)
                if (f_v_ini and f_v_fin and f_v_fin >= f_v_ini)
                else 0.0
            )
            if c_dinc and pd.notna(row[c_dinc]):
                try:
                    dias_inc = max(0.0, float(row[c_dinc]))
                except ValueError:
                    dias_inc = 0.0
            else:
                dias_inc = (
                    ((f_i_fin - f_i_ini).days + 1)
                    if (f_i_ini and f_i_fin and f_i_fin >= f_i_ini)
                    else 0.0
                )

            if c_dtrab and pd.notna(row[c_dtrab]):
                try:
                    d_trab = float(row[c_dtrab])
                except ValueError:
                    d_trab = 30.0
            else:
                d_trab = 30.0

            bonif = limpiar_monto(row[c_bon]) if c_bon else 0.0
            aux = limpiar_monto(row[c_aux]) if c_aux else 0.0

            fecha_ref = f_i_ini or f_v_ini or date(2026, 1, 1)
            det_id = asegurar_detalle_nomina(
                emp_id,
                fecha_ref.year,
                fecha_ref.month,
                dias_trab=d_trab,
                dias_inc=dias_inc,
                dias_vac=dias_vac,
                bonif=bonif,
                aux=aux,
            )
            total_detalles += 1

            if f_v_ini:
                f_fin_ok = f_v_fin if (f_v_fin and f_v_fin >= f_v_ini) else f_v_ini
                obs_v = limpiar_str(row[c_obs_vac], 255) if c_obs_vac else None
                total_novedades += registrar_novedad_unica(det_id, "VACACIONES", f_v_ini, f_fin_ok, obs_v)

            if f_i_ini:
                f_fin_ok = f_i_fin if (f_i_fin and f_i_fin >= f_i_ini) else f_i_ini
                obs_i = limpiar_str(row[c_obs_inc], 255) if c_obs_inc else None
                total_novedades += registrar_novedad_unica(det_id, "INCAPACIDAD", f_i_ini, f_fin_ok, obs_i)

    conn.commit()
    cursor.close()
    print(f"✅ Detalles de nómina procesados: {total_detalles} | Novedades insertadas: {total_novedades}")


# ==============================================================================
# 2. CARGA DE PELÍCULAS (movies.dat -> pelicula, genero_pelicula, pelicula_genero)
# ==============================================================================
def cargar_peliculas(conn):
    if not os.path.exists(RUTA_MOVIES):
        print(f"⚠️ No se encontró {RUTA_MOVIES}, saltando módulo de películas.")
        return

    print("\n--- [2/3] Procesando movies.dat ---")
    cursor = conn.cursor()

    peliculas = {}
    pelicula_generos_raw = []
    generos_unicos = set()
    patron_anio = re.compile(r"\((\d{4})\)\s*$")

    try:
        with open(RUTA_MOVIES, "r", encoding="utf-8") as f:
            lineas = f.readlines()
    except UnicodeDecodeError:
        with open(RUTA_MOVIES, "r", encoding="latin-1") as f:
            lineas = f.readlines()

    for linea in lineas:
        linea = linea.strip()
        if not linea:
            continue

        if "::" in linea:
            partes = linea.split("::")
        elif "\t" in linea:
            partes = linea.split("\t")
        else:
            partes = linea.split(",")

        if len(partes) < 2:
            continue

        try:
            movie_id = int(partes[0].strip())
        except ValueError:
            continue

        raw_title = partes[1].strip()
        raw_genres = partes[2].strip() if len(partes) >= 3 else ""

        anio = None
        m = patron_anio.search(raw_title)
        if m:
            anio_val = int(m.group(1))
            if 1880 <= anio_val <= 2030:
                anio = anio_val
            titulo = raw_title[: m.start()].strip() or raw_title
        else:
            titulo = raw_title

        titulo = titulo[:300]
        peliculas[movie_id] = (movie_id, titulo, anio)

        if raw_genres and raw_genres.lower() != "(no genres listed)":
            for g in raw_genres.split("|"):
                g_limpio = g.strip()[:60]
                if g_limpio:
                    generos_unicos.add(g_limpio)
                    pelicula_generos_raw.append((movie_id, g_limpio))

    map_generos = obtener_o_crear_catalogo(cursor, "genero_pelicula", "genero_id", "nombre", generos_unicos)

    sql_pel = """
        INSERT IGNORE INTO pelicula (pelicula_id, titulo, anio_estreno)
        VALUES (%s, %s, %s)
    """
    insertar_en_lotes(cursor, sql_pel, list(peliculas.values()))

    pares_pg = list({(mid, map_generos[g]) for (mid, g) in pelicula_generos_raw if g in map_generos})
    sql_pg = """
        INSERT IGNORE INTO pelicula_genero (pelicula_id, genero_id)
        VALUES (%s, %s)
    """
    insertar_en_lotes(cursor, sql_pg, pares_pg)

    conn.commit()
    cursor.close()
    print(f"✅ Películas cargadas: {len(peliculas)} | Géneros: {len(map_generos)} | Relaciones: {len(pares_pg)}")


# ==============================================================================
# 3. CARGA DE LIBROS (Books.json -> editorial, idioma, autor, libro, libro_autor)
# ==============================================================================
def cargar_libros(conn):
    if not os.path.exists(RUTA_BOOKS):
        print(f"⚠️ No se encontró {RUTA_BOOKS}, saltando módulo de libros.")
        return

    print("\n--- [3/3] Procesando Books.json ---")
    cursor = conn.cursor()

    with open(RUTA_BOOKS, "r", encoding="utf-8", errors="replace") as f:
        contenido = f.read().strip()

    if contenido.startswith("["):
        registros = json.loads(contenido)
    else:
        registros = [json.loads(line) for line in contenido.splitlines() if line.strip()]

    editoriales_set = set()
    idiomas_set = set()
    autores_set = set()
    libros_procesados = []

    seen_book_ids = set()
    seen_isbn = set()
    seen_isbn13 = set()

    for item in registros:
        norm_item = {normalizar_texto_clave(k): v for k, v in item.items()}

        raw_id = norm_item.get("bookid") or norm_item.get("book_id") or norm_item.get("id") or norm_item.get("libro_id")
        if raw_id is None:
            continue
        try:
            book_id = int(str(raw_id).strip())
        except ValueError:
            continue

        if book_id in seen_book_ids:
            continue
        seen_book_ids.add(book_id)

        titulo = limpiar_str(norm_item.get("title") or norm_item.get("titulo"), 500)
        if not titulo:
            continue

        isbn = limpiar_str(norm_item.get("isbn"), 13)
        if isbn:
            if isbn in seen_isbn:
                isbn = None
            else:
                seen_isbn.add(isbn)

        isbn13_raw = limpiar_str(norm_item.get("isbn13"), 13)
        isbn13 = isbn13_raw if (isbn13_raw and len(isbn13_raw) == 13) else None
        if isbn13:
            if isbn13 in seen_isbn13:
                isbn13 = None
            else:
                seen_isbn13.add(isbn13)

        idioma = limpiar_str(norm_item.get("language_code") or norm_item.get("idioma") or norm_item.get("language"), 10) or "N/A"
        idiomas_set.add(idioma)

        editorial = limpiar_str(norm_item.get("publisher") or norm_item.get("editorial"), 200) or "SIN EDITORIAL"
        editoriales_set.add(editorial)

        num_pag = None
        raw_pag = norm_item.get("num_pages") or norm_item.get("numero_paginas") or norm_item.get("pages")
        if raw_pag is not None and str(raw_pag).strip() != "":
            try:
                p_val = int(float(str(raw_pag).strip()))
                if p_val >= 0:
                    num_pag = p_val
            except ValueError:
                pass

        rating = None
        raw_rat = norm_item.get("average_rating") or norm_item.get("promedio_rating") or norm_item.get("rating")
        if raw_rat is not None and str(raw_rat).strip() != "":
            try:
                r_val = round(float(str(raw_rat).strip()), 2)
                if 0.0 <= r_val <= 5.0:
                    rating = r_val
            except ValueError:
                pass

        cant_rat = 0
        raw_crat = norm_item.get("ratings_count") or norm_item.get("cantidad_ratings")
        if raw_crat is not None:
            try:
                cant_rat = max(0, int(float(str(raw_crat).strip())))
            except ValueError:
                cant_rat = 0

        cant_res = 0
        raw_cres = norm_item.get("text_reviews_count") or norm_item.get("cantidad_resenas")
        if raw_cres is not None:
            try:
                cant_res = max(0, int(float(str(raw_cres).strip())))
            except ValueError:
                cant_res = 0

        f_pub = parsear_fecha(norm_item.get("publication_date") or norm_item.get("fecha_publicacion"))

        raw_autores = norm_item.get("authors") or norm_item.get("autores") or norm_item.get("autor")
        lista_autores = []
        if isinstance(raw_autores, list):
            candidatos_aut = raw_autores
        elif raw_autores is not None:
            candidatos_aut = str(raw_autores).split("/")
        else:
            candidatos_aut = []

        for a in candidatos_aut:
            a_limpio = limpiar_str(a, 200)
            if a_limpio and a_limpio not in lista_autores:
                lista_autores.append(a_limpio)
                autores_set.add(a_limpio)

        libros_procesados.append({
            "libro_id": book_id,
            "titulo": titulo,
            "isbn": isbn,
            "isbn13": isbn13,
            "idioma": idioma,
            "numero_paginas": num_pag,
            "promedio_rating": rating,
            "cantidad_ratings": cant_rat,
            "cantidad_resenas": cant_res,
            "fecha_publicacion": f_pub,
            "editorial": editorial,
            "autores": lista_autores,
        })

    map_idiomas = obtener_o_crear_catalogo(cursor, "idioma", "idioma_id", "codigo", idiomas_set)
    map_editoriales = obtener_o_crear_catalogo(cursor, "editorial", "editorial_id", "nombre", editoriales_set)
    map_autores = obtener_o_crear_catalogo(cursor, "autor", "autor_id", "nombre", autores_set)

    filas_libro = []
    filas_libro_autor = []

    for b in libros_procesados:
            filas_libro.append((
                b["libro_id"],
                b["titulo"],
                b["isbn"],
                b["isbn13"],
                buscar_id_catalogo(map_idiomas, b["idioma"]),
                b["numero_paginas"],
                b["promedio_rating"],
                b["cantidad_ratings"],
                b["cantidad_resenas"],
                b["fecha_publicacion"],
                buscar_id_catalogo(map_editoriales, b["editorial"]),
            ))
            for idx, nombre_autor in enumerate(b["autores"], start=1):
                autor_id = buscar_id_catalogo(map_autores, nombre_autor)
                if autor_id:
                    filas_libro_autor.append((b["libro_id"], autor_id, idx))

    sql_libro = """
        INSERT IGNORE INTO libro (
            libro_id, titulo, isbn, isbn13, idioma_id, numero_paginas,
            promedio_rating, cantidad_ratings, cantidad_resenas,
            fecha_publicacion, editorial_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    insertar_en_lotes(cursor, sql_libro, filas_libro)

    sql_la = """
        INSERT IGNORE INTO libro_autor (libro_id, autor_id, orden_autoria)
        VALUES (%s, %s, %s)
    """
    insertar_en_lotes(cursor, sql_la, filas_libro_autor)

    conn.commit()
    cursor.close()
    print(f"✅ Libros cargados: {len(filas_libro)} | Autores: {len(map_autores)} | Relaciones autoría: {len(filas_libro_autor)}")


# ==============================================================================
# PUNTO DE ENTRADA PRINCIPAL
# ==============================================================================
def main():
    inicio = datetime.now()
    print("Conectando a MySQL ('proyecto_integrador')...")
    conn = mysql.connector.connect(**DB_CONFIG)
    try:
        cargar_nomina(conn)
        cargar_peliculas(conn)
        cargar_libros(conn)
    finally:
        conn.close()
    duracion = (datetime.now() - inicio).total_seconds()
    print(f"\n🚀 Ingesta masiva completada exitosamente en {duracion:.2f} segundos.")


if __name__ == "__main__":
    main()