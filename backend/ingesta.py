"""
Motor de ingesta de archivos (CSV / XLSX) para los módulos Nómina, Libros y Películas.
"""
import calendar
import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
from sqlalchemy import text

import auditoria
import db
from config import Config


# ======================= utilidades de limpieza =======================
def clave_norm(s):
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(s.casefold().split())


def limpiar_texto(v):
    if v is None:
        return None
    v = " ".join(str(v).split())
    return v or None


def a_entero(v):
    v = limpiar_texto(v)
    if v is None:
        return None
    if re.fullmatch(r"-?\d+(\.0+)?", v):
        return int(float(v))
    raise ValueError(f"'{v}' no es un entero")


def a_decimal(v):
    v = limpiar_texto(v)
    if v is None:
        return None
    s = v.replace("$", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    elif s.count(",") > 1:
        s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"'{v}' no es un número")
    if not d.is_finite():
        raise ValueError(f"'{v}' no es un número")
    return d


def a_fecha(v, formatos):
    v = limpiar_texto(v)
    if v is None:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}", v):
        v = v[:10]
    for f in formatos:
        try:
            return datetime.strptime(v, f).date()
        except ValueError:
            continue
    raise ValueError(f"fecha '{v}' no válida")


def a_codigo_isbn(v, largo):
    v = limpiar_texto(v)
    if v is None:
        return None
    v = re.sub(r"\.0+$", "", v).replace("-", "").upper()
    if "E+" in v:
        raise ValueError("ISBN en notación científica (formatea la columna como texto en Excel)")
    if len(v) < largo and v.isdigit():
        v = v.zfill(largo)
    if len(v) != largo:
        raise ValueError(f"ISBN '{v}' debe tener {largo} caracteres")
    return v


FECHAS_ISO_DMY = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y")
FECHAS_ISO_MDY = ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y")


def normalizar_columna(c):
    c = unicodedata.normalize("NFKD", str(c))
    c = "".join(ch for ch in c if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "_", c.strip().lower()).strip("_")


# ======================= lectura del archivo =======================
class ErrorArchivo(Exception):
    pass


def leer_archivo(ruta, lineas_malas):
    ruta = Path(ruta)
    ext = ruta.suffix.lower()
    if ext == ".xlsx":
        try:
            df = pd.read_excel(ruta, dtype=str, engine="openpyxl")
        except Exception as e:
            raise ErrorArchivo(f"No se pudo leer el Excel: {e}")
    elif ext == ".csv":
        crudo = ruta.read_bytes()
        texto = None
        for cod in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                texto = crudo.decode(cod)
                break
            except UnicodeDecodeError:
                continue
        if not texto or not texto.strip():
            raise ErrorArchivo("El archivo está vacío.")
        cabecera = texto.splitlines()[0]
        sep = max([",", ";", "\t", "|"], key=cabecera.count)

        def linea_mala(campos):
            lineas_malas.append(campos)
            return None

        try:
            df = pd.read_csv(io.StringIO(texto), sep=sep, dtype=str, keep_default_na=False,
                             engine="python", on_bad_lines=linea_mala, skipinitialspace=True)
        except Exception as e:
            raise ErrorArchivo(f"No se pudo leer el CSV: {e}")
    else:
        raise ErrorArchivo("Formato no permitido. Usa .csv o .xlsx")
    df = df.fillna("")
    df.columns = [normalizar_columna(c) for c in df.columns]
    df = df.loc[:, [c for c in df.columns if c and not c.startswith("unnamed")]]
    df = df[~(df.apply(lambda f: all(str(x).strip() == "" for x in f), axis=1))] if len(df) else df
    return df


# ======================= resultado =======================
@dataclass
class Resultado:
    leidos: int = 0
    cargados: int = 0
    rechazos: list = field(default_factory=list)
    resumen: dict = field(default_factory=dict)

    def rechazar(self, fila, motivo):
        self.rechazos.append((fila, motivo))

    @property
    def rechazados(self):
        return len(self.rechazos)


def _mapa_catalogo(conn, tabla, pk, col):
    filas = conn.execute(text(f"SELECT `{pk}`, `{col}` FROM `{tabla}`")).all()
    return {clave_norm(nombre): i for i, nombre in filas}


def _asegurar_catalogo(conn, tabla, pk, col, nombres, resumen=None):
    mapa = _mapa_catalogo(conn, tabla, pk, col)
    nuevos, vistos = [], set()
    for n in nombres:
        k = clave_norm(n)
        if k not in mapa and k not in vistos:
            vistos.add(k)
            nuevos.append({"n": n})
    if nuevos:
        conn.execute(text(f"INSERT IGNORE INTO `{tabla}` (`{col}`) VALUES (:n)"), nuevos)
        mapa = _mapa_catalogo(conn, tabla, pk, col)
        if resumen is not None:
            resumen[f"nuevos_{tabla}"] = len(nuevos)
    return mapa


def _exigir_columnas(df, requeridas):
    faltan = [c for c in requeridas if c not in df.columns]
    if faltan:
        raise ErrorArchivo("Faltan columnas obligatorias: " + ", ".join(faltan) +
                           ". Columnas encontradas: " + ", ".join(df.columns))


def _renombrar(df, alias):
    return df.rename(columns={c: alias[c] for c in df.columns if c in alias and alias[c] not in df.columns})


def _asegurar_periodo(conn, anio, mes):
    p_id = conn.execute(
        text("SELECT periodo_id FROM periodo_nomina WHERE anio = :a AND mes = :m"),
        {"a": anio, "m": mes},
    ).scalar()
    if p_id is None:
        f_ini = date(anio, mes, 1)
        f_fin = date(anio, mes, calendar.monthrange(anio, mes)[1])
        p_id = conn.execute(
            text("INSERT INTO periodo_nomina (anio, mes, fecha_inicio, fecha_fin) VALUES (:a, :m, :fi, :ff)"),
            {"a": anio, "m": mes, "fi": f_ini, "ff": f_fin},
        ).lastrowid
    return p_id


# ======================= NÓMINA =======================
ALIAS_NOMINA = {
    "empleado_id": "codigo", "id_empleado": "codigo",
    "nombre": "nombre_completo", "empleado": "nombre_completo",
    "salario": "sueldo", "sueldo_base": "sueldo",
    "departamento": "dependencia",
    "fecha_de_ingreso": "fecha_ingreso", "pension": "fondo_pension", "fondo": "fondo_pension",
    "fondo_de_pension": "fondo_pension", "ano": "anio", "year": "anio", "dias": "dias_trabajados",
    "auxilio_transporte": "transporte", "bonificaciones": "bonificacion",
}
COLS_NOMINA = ["codigo", "nombre_completo", "fecha_ingreso", "sueldo",
               "dependencia", "cargo", "eps", "fondo_pension", "arl"]
COLS_LIQ = ["anio", "mes", "dias_trabajados"]
CATALOGOS_NOMINA = {
    "dependencia": ("departamento", "departamento_id", "nombre", "departamento_id"),
    "cargo": ("cargo", "cargo_id", "nombre", "cargo_id"),
    "eps": ("eps", "eps_id", "nombre", "eps_id"),
    "fondo_pension": ("fondo_pension", "fondo_pension_id", "nombre", "fondo_pension_id"),
    "arl": ("arl", "arl_id", "nombre", "arl_id"),
}


def cargar_nomina(conn, df, r):
    df = _renombrar(df, ALIAS_NOMINA)
    _exigir_columnas(df, COLS_NOMINA)
    con_liq = all(c in df.columns for c in COLS_LIQ)

    existentes = {str(c) for (c,) in conn.execute(text("SELECT empleado_id FROM empleado")).all()}
    liq_existentes = set(conn.execute(text(
        "SELECT l.empleado_id, p.anio, p.mes FROM detalle_nomina l "
        "JOIN periodo_nomina p ON p.periodo_id = l.periodo_id")).all())

    validas, empleados_nuevos, vistos_liq = [], {}, set()
    for idx, f in df.iterrows():
        fila = idx + 2
        try:
            codigo = limpiar_texto(f["codigo"])
            if codigo and codigo.endswith(".0"):
                codigo = codigo[:-2]
            nombre = limpiar_texto(f["nombre_completo"])
            if not codigo or not nombre:
                raise ValueError("código y nombre son obligatorios")
            if len(codigo) > 20:
                raise ValueError("código de más de 20 caracteres")
            emp = {"empleado_id": codigo, "nombre_completo": nombre[:150],
                   "fecha_ingreso": a_fecha(f["fecha_ingreso"], FECHAS_ISO_DMY),
                   "sueldo_base": a_decimal(f["sueldo"])}
            if emp["fecha_ingreso"] is None or emp["sueldo_base"] is None:
                raise ValueError("fecha de ingreso y sueldo son obligatorios")
            if emp["sueldo_base"] < 0:
                raise ValueError("sueldo negativo")
            cats = {}
            for col in CATALOGOS_NOMINA:
                cats[col] = limpiar_texto(f[col])
                if not cats[col]:
                    raise ValueError(f"'{col}' vacío")
            liq = None
            if con_liq and any(limpiar_texto(f[c]) for c in COLS_LIQ):
                anio, mes, dias = a_entero(f["anio"]), a_entero(f["mes"]), a_entero(f["dias_trabajados"])
                if anio is None or mes is None or dias is None:
                    raise ValueError("anio, mes y dias_trabajados son obligatorios para la liquidación")
                if not 1 <= mes <= 12:
                    raise ValueError("mes fuera de 1-12")
                if not 0 <= dias <= 30:
                    raise ValueError("días trabajados fuera de 0-30")
                liq = {"anio": anio, "mes": mes, "dias_trabajados": dias,
                       "bonificacion": a_decimal(f.get("bonificacion", "")) or Decimal(0),
                       "auxilio_transporte": a_decimal(f.get("transporte", "")) or Decimal(0)}
        except ValueError as e:
            r.rechazar(fila, str(e))
            continue

        es_nuevo = codigo not in existentes and codigo not in empleados_nuevos
        if liq:
            llave = (codigo, liq["anio"], liq["mes"])
            if llave in liq_existentes or llave in vistos_liq:
                if not es_nuevo:
                    r.rechazar(fila, "la liquidación de ese empleado y periodo ya existe")
                    continue
                liq = None
            else:
                vistos_liq.add(llave)
        elif not es_nuevo:
            r.rechazar(fila, "el empleado ya existe")
            continue
        if es_nuevo:
            empleados_nuevos[codigo] = (emp, cats)
        validas.append((fila, codigo, liq))

    if not validas:
        return

    ids_cat = {}
    for col, (tabla, pk, nom, _) in CATALOGOS_NOMINA.items():
        ids_cat[col] = _asegurar_catalogo(conn, tabla, pk, nom,
                                          [c[col] for _, c in empleados_nuevos.values()], r.resumen)
    filas_emp = []
    for emp, cats in empleados_nuevos.values():
        reg = dict(emp)
        for col, (_, _, _, col_emp) in CATALOGOS_NOMINA.items():
            reg[col_emp] = ids_cat[col][clave_norm(cats[col])]
        filas_emp.append(reg)
    if filas_emp:
        conn.execute(text(
            "INSERT INTO empleado (empleado_id, nombre_completo, fecha_ingreso, sueldo_base, departamento_id, "
            "cargo_id, eps_id, fondo_pension_id, arl_id) VALUES (:empleado_id, :nombre_completo, :fecha_ingreso, "
            ":sueldo_base, :departamento_id, :cargo_id, :eps_id, :fondo_pension_id, :arl_id)"), filas_emp)
    r.resumen["empleados"] = len(filas_emp)

    liqs = [(c, l) for _, c, l in validas if l]
    if liqs:
        mapa_p = {(l["anio"], l["mes"]): _asegurar_periodo(conn, l["anio"], l["mes"]) for _, l in liqs}
        conn.execute(text(
            "INSERT INTO detalle_nomina (empleado_id, periodo_id, dias_trabajados, bonificacion, auxilio_transporte) "
            "VALUES (:empleado_id, :periodo_id, :dias_trabajados, :bonificacion, :auxilio_transporte)"),
            [{"empleado_id": c, "periodo_id": mapa_p[(l["anio"], l["mes"])], **{k: l[k] for k in
              ("dias_trabajados", "bonificacion", "auxilio_transporte")}} for c, l in liqs])
    r.resumen["liquidaciones"] = len(liqs)
    r.cargados = len(validas)


def _cargar_novedad(conn, df, r, tipo_novedad):
    df = _renombrar(df, {"empleado": "codigo", "empleado_id": "codigo",
                         "inicio": "fecha_inicio", "fin": "fecha_fin", "codigo_empleado": "codigo"})
    _exigir_columnas(df, ["codigo", "fecha_inicio", "fecha_fin"])
    empleados = {str(c) for (c,) in conn.execute(text("SELECT empleado_id FROM empleado")).all()}
    existentes = set(conn.execute(text(
        "SELECT dn.empleado_id, n.fecha_inicio FROM novedad_nomina n "
        "JOIN detalle_nomina dn ON dn.detalle_nomina_id = n.detalle_nomina_id "
        "WHERE n.tipo_novedad = :t"), {"t": tipo_novedad}).all())

    filas, vistos = [], set()
    for idx, f in df.iterrows():
        fila = idx + 2
        try:
            codigo = limpiar_texto(f["codigo"])
            if codigo and codigo.endswith(".0"):
                codigo = codigo[:-2]
            ini = a_fecha(f["fecha_inicio"], FECHAS_ISO_DMY)
            fin = a_fecha(f["fecha_fin"], FECHAS_ISO_DMY)
            if not codigo or not ini or not fin:
                raise ValueError("código, fecha_inicio y fecha_fin son obligatorios")
            if fin < ini:
                raise ValueError("fecha_fin anterior a fecha_inicio")
            dias = a_entero(f.get("dias", "")) or (fin - ini).days + 1
            if dias <= 0:
                raise ValueError("días debe ser mayor a 0")
            obs = limpiar_texto(f.get("observacion", ""))
        except ValueError as e:
            r.rechazar(fila, str(e))
            continue
        if codigo not in empleados:
            r.rechazar(fila, f"el empleado '{codigo}' no existe")
            continue
        if (codigo, ini) in existentes or (codigo, ini) in vistos:
            r.rechazar(fila, "ya existe un registro de ese empleado con esa fecha de inicio")
            continue
        vistos.add((codigo, ini))
        filas.append({"c": codigo, "i": ini, "f": fin, "d": dias, "obs": obs[:255] if obs else None})

    for item in filas:
        p_id = _asegurar_periodo(conn, item["i"].year, item["i"].month)
        det_id = conn.execute(
            text("SELECT detalle_nomina_id FROM detalle_nomina WHERE periodo_id = :p AND empleado_id = :e"),
            {"p": p_id, "e": item["c"]},
        ).scalar()
        if det_id is None:
            det_id = conn.execute(
                text("INSERT INTO detalle_nomina (periodo_id, empleado_id, dias_trabajados) VALUES (:p, :e, 30)"),
                {"p": p_id, "e": item["c"]},
            ).lastrowid
        col_dias = "dias_incapacidad" if tipo_novedad == "INCAPACIDAD" else "dias_vacaciones"
        conn.execute(
            text(f"UPDATE detalle_nomina SET {col_dias} = {col_dias} + :d WHERE detalle_nomina_id = :id"),
            {"d": item["d"], "id": det_id},
        )
        conn.execute(
            text("INSERT INTO novedad_nomina (detalle_nomina_id, tipo_novedad, fecha_inicio, fecha_fin, observacion) "
                 "VALUES (:det, :tipo, :i, :f, :obs)"),
            {"det": det_id, "tipo": tipo_novedad, "i": item["i"], "f": item["f"], "obs": item["obs"]},
        )
    r.cargados = len(filas)


def cargar_incapacidades(conn, df, r):
    _cargar_novedad(conn, df, r, "INCAPACIDAD")


def cargar_vacaciones(conn, df, r):
    _cargar_novedad(conn, df, r, "VACACIONES")


# ======================= LIBROS =======================
ALIAS_LIBROS = {
    "bookid": "libro_id", "book_id": "libro_id", "id_libro": "libro_id",
    "title": "titulo", "authors": "autores", "autor": "autores",
    "average_rating": "promedio_rating", "rating_promedio": "promedio_rating",
    "language_code": "idioma", "codigo_idioma": "idioma",
    "num_pages": "numero_paginas", "num_paginas": "numero_paginas",
    "ratings_count": "cantidad_ratings", "text_reviews_count": "cantidad_resenas",
    "publication_date": "fecha_publicacion", "publisher": "editorial",
}


def cargar_libros(conn, df, r):
    df = _renombrar(df, ALIAS_LIBROS)
    _exigir_columnas(df, ["libro_id", "titulo", "autores", "editorial", "idioma"])
    existentes = {i for (i,) in conn.execute(text("SELECT libro_id FROM libro")).all()}
    isbn_exist = {i for (i,) in conn.execute(text("SELECT isbn FROM libro WHERE isbn IS NOT NULL")).all()}
    isbn13_exist = {i for (i,) in conn.execute(text("SELECT isbn13 FROM libro WHERE isbn13 IS NOT NULL")).all()}

    libros, vistos = [], set()
    for idx, f in df.iterrows():
        fila = idx + 2
        try:
            id_libro = a_entero(f["libro_id"])
            titulo = limpiar_texto(f["titulo"])
            editorial = limpiar_texto(f["editorial"])
            idioma = limpiar_texto(f["idioma"])
            autores = []
            for a in str(f["autores"]).split("/"):
                a = limpiar_texto(a)
                if a and clave_norm(a) not in {clave_norm(x) for x in autores}:
                    autores.append(a[:200])
            if not id_libro or id_libro <= 0:
                raise ValueError("libro_id vacío o inválido")
            if not titulo or not editorial or not idioma:
                raise ValueError("título, editorial e idioma son obligatorios")
            if not autores:
                raise ValueError("el libro debe tener al menos un autor")
            rating = a_decimal(f.get("promedio_rating", ""))
            if rating is not None and not 0 <= rating <= 5:
                raise ValueError("rating fuera de 0-5")
            paginas = a_entero(f.get("numero_paginas", ""))
            if paginas is not None and paginas < 0:
                raise ValueError("número de páginas negativo")
            isbn = a_codigo_isbn(f.get("isbn", ""), 10)
            if isbn in isbn_exist:
                isbn = None
            elif isbn:
                isbn_exist.add(isbn)
            isbn13 = a_codigo_isbn(f.get("isbn13", ""), 13)
            if isbn13 in isbn13_exist:
                isbn13 = None
            elif isbn13:
                isbn13_exist.add(isbn13)

            reg = {
                "libro_id": id_libro, "titulo": titulo[:500],
                "isbn": isbn, "isbn13": isbn13,
                "numero_paginas": paginas, "promedio_rating": rating,
                "cantidad_ratings": a_entero(f.get("cantidad_ratings", "")) or 0,
                "cantidad_resenas": a_entero(f.get("cantidad_resenas", "")) or 0,
                "fecha_publicacion": a_fecha(f.get("fecha_publicacion", ""), FECHAS_ISO_MDY),
                "_editorial": editorial[:200], "_idioma": idioma[:10], "_autores": autores,
            }
        except ValueError as e:
            r.rechazar(fila, str(e))
            continue
        if id_libro in vistos:
            r.rechazar(fila, f"libro_id {id_libro} repetido en el archivo")
            continue
        if id_libro in existentes:
            r.rechazar(fila, f"el libro {id_libro} ya existe")
            continue
        vistos.add(id_libro)
        libros.append(reg)
    if not libros:
        return

    m_ed = _asegurar_catalogo(conn, "editorial", "editorial_id", "nombre", [l["_editorial"] for l in libros], r.resumen)
    m_id = _asegurar_catalogo(conn, "idioma", "idioma_id", "codigo", [l["_idioma"] for l in libros], r.resumen)
    m_au = _asegurar_catalogo(conn, "autor", "autor_id", "nombre", [a for l in libros for a in l["_autores"]], r.resumen)
    for l in libros:
        l["editorial_id"] = m_ed[clave_norm(l["_editorial"])]
        l["idioma_id"] = m_id[clave_norm(l["_idioma"])]

    conn.execute(text(
        "INSERT INTO libro (libro_id, titulo, isbn, isbn13, numero_paginas, promedio_rating, cantidad_ratings, "
        "cantidad_resenas, fecha_publicacion, editorial_id, idioma_id) VALUES (:libro_id, :titulo, :isbn, "
        ":isbn13, :numero_paginas, :promedio_rating, :cantidad_ratings, :cantidad_resenas, :fecha_publicacion, "
        ":editorial_id, :idioma_id)"),
        [{k: v for k, v in l.items() if not k.startswith("_")} for l in libros])

    relaciones = []
    for l in libros:
        for orden, a in enumerate(l["_autores"], start=1):
            relaciones.append({"l": l["libro_id"], "a": m_au[clave_norm(a)], "o": orden})
    conn.execute(text("INSERT INTO libro_autor (libro_id, autor_id, orden_autoria) VALUES (:l, :a, :o)"), relaciones)
    r.resumen["relaciones_libro_autor"] = len(relaciones)
    r.cargados = len(libros)


# ======================= PELÍCULAS =======================
ALIAS_PELICULAS = {
    "movieid": "pelicula_id", "movie_id": "pelicula_id", "id_pelicula": "pelicula_id",
    "title": "titulo", "genres": "generos", "genero": "generos",
    "year": "anio_estreno", "ano": "anio_estreno", "anio": "anio_estreno",
}
RE_ANIO_TITULO = re.compile(r"^(.*?)\s*\((\d{4})(?:[–-]\d{0,4})?\)\s*$")


def cargar_peliculas(conn, df, r):
    df = _renombrar(df, ALIAS_PELICULAS)
    _exigir_columnas(df, ["pelicula_id", "titulo", "generos"])
    existentes = {i for (i,) in conn.execute(text("SELECT pelicula_id FROM pelicula")).all()}
    pelis, vistos = [], set()
    for idx, f in df.iterrows():
        fila = idx + 2
        try:
            id_p = a_entero(f["pelicula_id"])
            titulo = limpiar_texto(f["titulo"])
            if not id_p or id_p <= 0 or not titulo:
                raise ValueError("pelicula_id y título son obligatorios")
            anio = a_entero(f.get("anio_estreno", ""))
            m = RE_ANIO_TITULO.match(titulo)
            if m:
                titulo = m.group(1) or titulo
                anio = anio or int(m.group(2))
            if anio is not None and not 1880 <= anio <= 2100:
                raise ValueError(f"año {anio} fuera de rango")
            generos = []
            for g in re.split(r"[|/;]", str(f["generos"])):
                g = limpiar_texto(g)
                if g and g.lower() != "(no genres listed)" and clave_norm(g) not in {clave_norm(x) for x in generos}:
                    generos.append(g[:60])
            if not generos:
                raise ValueError("la película debe tener al menos un género")
        except ValueError as e:
            r.rechazar(fila, str(e))
            continue
        if id_p in vistos:
            r.rechazar(fila, f"pelicula_id {id_p} repetido en el archivo")
            continue
        if id_p in existentes:
            r.rechazar(fila, f"la película {id_p} ya existe")
            continue
        vistos.add(id_p)
        pelis.append({"pelicula_id": id_p, "titulo": titulo[:300], "anio_estreno": anio, "_generos": generos})
    if not pelis:
        return
    m_g = _asegurar_catalogo(conn, "genero_pelicula", "genero_id", "nombre",
                             [g for p in pelis for g in p["_generos"]], r.resumen)
    conn.execute(text("INSERT INTO pelicula (pelicula_id, titulo, anio_estreno) VALUES (:pelicula_id, :titulo, :anio_estreno)"),
                 [{k: v for k, v in p.items() if not k.startswith("_")} for p in pelis])
    rel = {(p["pelicula_id"], m_g[clave_norm(g)]) for p in pelis for g in p["_generos"]}
    conn.execute(text("INSERT INTO pelicula_genero (pelicula_id, genero_id) VALUES (:p, :g)"),
                 [{"p": p, "g": g} for p, g in rel])
    r.resumen["relaciones_pelicula_genero"] = len(rel)
    r.cargados = len(pelis)


# ======================= registro de tipos de carga =======================
TIPOS_CARGA = {
    "nomina": {"titulo": "Nómina (empleados + liquidación)", "modulo": "Nómina", "funcion": cargar_nomina,
               "columnas": COLS_NOMINA + ["anio", "mes", "dias_trabajados", "bonificacion", "transporte"],
               "obligatorias": COLS_NOMINA, "ejemplo": "nomina.csv",
               "nota": "Las columnas de liquidación son opcionales. Departamentos, cargos, EPS, fondos y ARL "
                       "que no existan se crean. Fechas AAAA-MM-DD o DD/MM/AAAA."},
    "incapacidades": {"titulo": "Incapacidades", "modulo": "Nómina", "funcion": cargar_incapacidades,
                      "columnas": ["codigo", "fecha_inicio", "fecha_fin", "dias"],
                      "obligatorias": ["codigo", "fecha_inicio", "fecha_fin"], "ejemplo": "incapacidades.csv",
                      "nota": "El empleado debe existir. Si 'dias' está vacío se calcula con las fechas."},
    "vacaciones": {"titulo": "Vacaciones", "modulo": "Nómina", "funcion": cargar_vacaciones,
                   "columnas": ["codigo", "fecha_inicio", "fecha_fin", "dias"],
                   "obligatorias": ["codigo", "fecha_inicio", "fecha_fin"], "ejemplo": "vacaciones.csv",
                   "nota": "El empleado debe existir. Si 'dias' está vacío se calcula con las fechas."},
    "libros": {"titulo": "Libros (estructura Goodreads books.csv)", "modulo": "Libros", "funcion": cargar_libros,
               "columnas": ["bookID", "title", "authors", "average_rating", "isbn", "isbn13", "language_code",
                            "num_pages", "ratings_count", "text_reviews_count", "publication_date", "publisher"],
               "obligatorias": ["bookID", "title", "authors", "language_code", "publisher"],
               "ejemplo": "libros.csv",
               "nota": "Varios autores separados por '/'. Fecha en formato M/D/AAAA (como el dataset)."},
    "peliculas": {"titulo": "Películas (estructura MovieLens movies.csv)", "modulo": "Películas",
                  "funcion": cargar_peliculas, "columnas": ["movieId", "title", "genres"],
                  "obligatorias": ["movieId", "title", "genres"], "ejemplo": "peliculas.csv",
                  "nota": "El año se toma del título, p. ej. 'Toy Story (1995)'. Géneros separados por '|'."},
}


# ======================= proceso completo de una carga =======================
def procesar_carga(ruta, nombre_original, tipo, id_usuario, ip=None):
    if tipo not in TIPOS_CARGA:
        raise ValueError("Tipo de carga desconocido")
    ruta = Path(ruta)
    with db.transaccion() as conn:
        id_carga = conn.execute(text(
            "INSERT INTO carga_archivo (id_usuario, nombre_archivo, tipo_archivo, estado) "
            "VALUES (:u, :n, :t, 'PROCESANDO')"),
            {"u": id_usuario, "n": nombre_original[:255], "t": tipo}).lastrowid

    r = Resultado()
    lineas_malas = []
    estado, mensaje = "ERROR", ""
    try:
        df = leer_archivo(ruta, lineas_malas)
        r.leidos = len(df) + len(lineas_malas)
        for i, campos in enumerate(lineas_malas, 1):
            r.rechazar("?", f"línea mal formada (columnas de más): {','.join(campos)[:80]}")
        if df.empty and not lineas_malas:
            raise ErrorArchivo("El archivo no tiene filas de datos.")
        with db.transaccion() as conn:
            TIPOS_CARGA[tipo]["funcion"](conn, df, r)
            estado = ("SIN_CAMBIOS" if r.cargados == 0 else "PARCIAL" if r.rechazados else "COMPLETADA")
            conn.execute(text(
                "UPDATE carga_archivo SET registros_leidos = :l, registros_cargados = :c, "
                "registros_rechazados = :r, estado = :e WHERE id_carga = :id"),
                {"l": r.leidos, "c": r.cargados, "r": r.rechazados, "e": estado, "id": id_carga})
            auditoria.registrar("CARGA_ARCHIVO", TIPOS_CARGA[tipo]["modulo"].lower(), {
                "id_carga": id_carga, "archivo": nombre_original, "tipo": tipo, "leidos": r.leidos,
                "cargados": r.cargados, "rechazados": r.rechazados, "resumen": r.resumen,
                "primeros_rechazos": r.rechazos[:20]}, id_usuario=id_usuario, conn=conn, ip=ip)
        mensaje = f"Se cargaron {r.cargados} de {r.leidos} registros."
    except ErrorArchivo as e:
        mensaje = str(e)
    except Exception as e:
        mensaje = f"Error inesperado, no se guardó ningún registro: {e.__class__.__name__}: {e}"[:500]
    if estado == "ERROR":
        r.cargados = 0
        db.ejecutar("UPDATE carga_archivo SET registros_leidos = :l, registros_cargados = 0, "
                    "registros_rechazados = :r, estado = 'ERROR' WHERE id_carga = :id",
                    {"l": r.leidos, "r": r.leidos, "id": id_carga})
        auditoria.registrar("CARGA_ERROR", TIPOS_CARGA[tipo]["modulo"].lower(),
                            {"id_carga": id_carga, "archivo": nombre_original, "error": mensaje},
                            id_usuario=id_usuario, ip=ip)

    if r.rechazos:
        carpeta = Path(Config.UPLOAD_FOLDER) / "rechazos"
        carpeta.mkdir(parents=True, exist_ok=True)
        with open(carpeta / f"rechazos_{id_carga}.csv", "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["fila_archivo", "motivo"])
            w.writerows(r.rechazos)

    return {"id_carga": id_carga, "estado": estado, "mensaje": mensaje, "leidos": r.leidos,
            "cargados": r.cargados, "rechazados": r.rechazos if estado != "ERROR" else r.leidos,
            "rechazos": r.rechazos[:200], "resumen": r.resumen}