"""
Consultas dinámicas parametrizadas (reportes), gráficos estadísticos (matplotlib)
y exportación / vista previa en PDF (xhtml2pdf) y CSV.
"""
import csv
import io
from datetime import date, datetime

from flask import Blueprint, Response, abort, g, render_template, request
from xhtml2pdf import pisa

import auditoria
import db
import graficos
from seguridad import permiso_requerido

bp = Blueprint("consultas", __name__, url_prefix="/consultas")

DEVENGADO = "ROUND(e.sueldo_base / 30 * l.dias_trabajados, 2)"

REPORTES = {
    # ------------------------- TABLERO ESTADÍSTICO (8 GRÁFICOS) -------------------------
    "dashboard_estadistico": {
        "modulo": "Estadísticas",
        "titulo": "Informe Estadístico Ejecutivo (8 Gráficos)",
        "descripcion": "Consolidado visual de Nómina, Seguridad Social, Películas y Libros listo para vista previa y exportación PDF.",
        "params": [],
        "orden_opciones": {"Módulo": "Módulo", "Indicador": "Indicador", "Valor": "Valor"},
        "orden_defecto": "Módulo",
        "sql": """
            SELECT 'Nómina' AS `Módulo`, 'Total Empleados Activos' AS `Indicador`, CAST(COUNT(*) AS CHAR) AS `Valor` FROM empleado
            UNION ALL
            SELECT 'Nómina', 'Masa Salarial Base Mensual (COP)', CONCAT('$', FORMAT(COALESCE(SUM(sueldo_base), 0), 0)) FROM empleado
            UNION ALL
            SELECT 'Nómina', 'Departamentos Activos', CAST(COUNT(*) AS CHAR) FROM departamento
            UNION ALL
            SELECT 'Nómina', 'Novedades Registradas (Incap. / Vac.)', CAST(COUNT(*) AS CHAR) FROM novedad_nomina
            UNION ALL
            SELECT 'Películas', 'Total Películas Catalogadas', FORMAT(COUNT(*), 0) FROM pelicula
            UNION ALL
            SELECT 'Películas', 'Géneros Cinematográficos', CAST(COUNT(*) AS CHAR) FROM genero_pelicula
            UNION ALL
            SELECT 'Libros', 'Total Libros Catalogados', FORMAT(COUNT(*), 0) FROM libro
            UNION ALL
            SELECT 'Libros', 'Total Autores Registrados', FORMAT(COUNT(*), 0) FROM autor
        """,
    },
    # ------------------------- NÓMINA -------------------------
    "nomina_periodo": {
        "modulo": "Nómina", "titulo": "Nómina liquidada por periodo y departamento",
        "descripcion": "Devengado = sueldo_base / 30 × días trabajados + bonificación + auxilio de transporte.",
        "params": [
            {"nombre": "periodo", "etiqueta": "Periodo", "tipo": "select", "requerido": True,
             "opciones": "SELECT periodo_id AS id, CONCAT(anio, '-', LPAD(mes, 2, '0')) AS txt "
                         "FROM periodo_nomina ORDER BY anio DESC, mes DESC",
             "defecto_sql": "SELECT periodo_id FROM periodo_nomina ORDER BY anio DESC, mes DESC LIMIT 1"},
            {"nombre": "dependencia", "etiqueta": "Departamento", "tipo": "select",
             "opciones": "SELECT departamento_id AS id, nombre AS txt FROM departamento ORDER BY nombre"},
            {"nombre": "limite", "etiqueta": "Top N", "tipo": "int", "defecto": 50, "maximo": 500},
        ],
        "orden_opciones": {
            "Empleado": "e.nombre_completo",
            "Departamento": "d.nombre",
            "Sueldo": "e.sueldo_base",
            "Total devengado": f"({DEVENGADO} + l.bonificacion + l.auxilio_transporte)",
        },
        "orden_defecto": "Departamento",
        "sql": f"""
            SELECT e.empleado_id AS `Código`, e.nombre_completo AS `Empleado`, d.nombre AS `Departamento`,
                   c.nombre AS `Cargo`, e.sueldo_base AS `Sueldo`, l.dias_trabajados AS `Días`,
                   {DEVENGADO} AS `Salario devengado`, l.bonificacion AS `Bonificación`,
                   l.auxilio_transporte AS `Transporte`,
                   {DEVENGADO} + l.bonificacion + l.auxilio_transporte AS `Total devengado`
            FROM detalle_nomina l
            JOIN empleado e ON e.empleado_id = l.empleado_id
            JOIN departamento d ON d.departamento_id = e.departamento_id
            JOIN cargo c ON c.cargo_id = e.cargo_id
            WHERE l.periodo_id = :periodo
              AND (:dependencia IS NULL OR e.departamento_id = :dependencia)
            ORDER BY {{ORDER_BY}}
            LIMIT :limite""",
    },
    "nomina_dependencia": {
        "modulo": "Nómina", "titulo": "Costo de nómina por departamento y mes",
        "params": [
            {"nombre": "anio", "etiqueta": "Año", "tipo": "int", "requerido": True,
             "defecto_sql": "SELECT MAX(anio) FROM periodo_nomina"},
        ],
        "orden_opciones": {
            "Periodo": "p.anio, p.mes",
            "Departamento": "d.nombre",
            "Total devengado": f"SUM({DEVENGADO} + l.bonificacion + l.auxilio_transporte)",
        },
        "orden_defecto": "Total devengado",
        "orden_dir_defecto": "DESC",
        "sql": f"""
            SELECT CONCAT(p.anio, '-', LPAD(p.mes, 2, '0')) AS `Periodo`, d.nombre AS `Departamento`,
                   COUNT(*) AS `Empleados liquidados`, SUM(l.dias_trabajados) AS `Días`,
                   SUM({DEVENGADO} + l.bonificacion + l.auxilio_transporte) AS `Total devengado`
            FROM detalle_nomina l
            JOIN periodo_nomina p ON p.periodo_id = l.periodo_id
            JOIN empleado e ON e.empleado_id = l.empleado_id
            JOIN departamento d ON d.departamento_id = e.departamento_id
            WHERE p.anio = :anio
            GROUP BY p.anio, p.mes, d.departamento_id, d.nombre
            ORDER BY {{ORDER_BY}}""",
    },
    "afiliaciones": {
        "modulo": "Nómina", "titulo": "Empleados por EPS, fondo de pensión y ARL",
        "params": [
            {"nombre": "tipo", "etiqueta": "Entidad", "tipo": "select",
             "lista": [("EPS", "EPS"), ("Pensión", "Fondo de pensión"), ("ARL", "ARL")]},
        ],
        "orden_opciones": {
            "Tipo": "r.`Tipo`",
            "Entidad": "r.`Entidad`",
            "Empleados": "r.`Empleados`",
            "Suma de sueldos": "r.`Suma de sueldos`",
        },
        "orden_defecto": "Empleados",
        "orden_dir_defecto": "DESC",
        "sql": """
            SELECT * FROM (
                SELECT 'EPS' AS `Tipo`, x.nombre AS `Entidad`, COUNT(e.empleado_id) AS `Empleados`,
                       COALESCE(SUM(e.sueldo_base), 0) AS `Suma de sueldos`
                FROM eps x LEFT JOIN empleado e ON e.eps_id = x.eps_id GROUP BY x.eps_id, x.nombre
                UNION ALL
                SELECT 'Pensión', x.nombre, COUNT(e.empleado_id), COALESCE(SUM(e.sueldo_base), 0)
                FROM fondo_pension x LEFT JOIN empleado e ON e.fondo_pension_id = x.fondo_pension_id
                GROUP BY x.fondo_pension_id, x.nombre
                UNION ALL
                SELECT 'ARL', x.nombre, COUNT(e.empleado_id), COALESCE(SUM(e.sueldo_base), 0)
                FROM arl x LEFT JOIN empleado e ON e.arl_id = x.arl_id GROUP BY x.arl_id, x.nombre
            ) r
            WHERE (:tipo IS NULL OR r.`Tipo` = :tipo)
            ORDER BY {ORDER_BY}""",
    },
    "novedades": {
        "modulo": "Nómina", "titulo": "Incapacidades y vacaciones por rango de fechas (F1 vs F2)",
        "params": [
            {"nombre": "desde", "etiqueta": "Fecha F1 (Desde)", "tipo": "date", "requerido": True,
             "defecto": lambda: date(date.today().year, 1, 1)},
            {"nombre": "hasta", "etiqueta": "Fecha F2 (Hasta)", "tipo": "date", "requerido": True,
             "defecto": lambda: date(date.today().year, 12, 31)},
            {"nombre": "empleado", "etiqueta": "Empleado (código o nombre)", "tipo": "text"},
        ],
        "orden_opciones": {
            "Inicio": "n.fecha_inicio",
            "Empleado": "e.nombre_completo",
            "Novedad": "n.tipo_novedad",
            "Días": "(DATEDIFF(n.fecha_fin, n.fecha_inicio) + 1)",
        },
        "orden_defecto": "Inicio",
        "sql": """
            SELECT CASE n.tipo_novedad WHEN 'INCAPACIDAD' THEN 'Incapacidad' ELSE 'Vacaciones' END AS `Novedad`,
                   e.empleado_id AS `Código`, e.nombre_completo AS `Empleado`,
                   n.fecha_inicio AS `Inicio`, n.fecha_fin AS `Fin`,
                   DATEDIFF(n.fecha_fin, n.fecha_inicio) + 1 AS `Días`,
                   COALESCE(n.observacion, '') AS `Observación`
            FROM novedad_nomina n
            JOIN detalle_nomina dn ON dn.detalle_nomina_id = n.detalle_nomina_id
            JOIN empleado e ON e.empleado_id = dn.empleado_id
            WHERE n.fecha_inicio <= :hasta AND n.fecha_fin >= :desde
              AND (:empleado IS NULL OR e.empleado_id LIKE :empleado_like OR e.nombre_completo LIKE :empleado_like)
            ORDER BY {ORDER_BY}""",
    },
    # ------------------------- LIBROS -------------------------
    "top_libros": {
        "modulo": "Libros", "titulo": "Libros mejor calificados (Top N)",
        "params": [
            {"nombre": "idioma", "etiqueta": "Idioma", "tipo": "select",
             "opciones": "SELECT idioma_id AS id, codigo AS txt FROM idioma ORDER BY codigo"},
            {"nombre": "autor", "etiqueta": "Autor contiene", "tipo": "text"},
            {"nombre": "min_ratings", "etiqueta": "Mínimo de ratings", "tipo": "int", "defecto": 100},
            {"nombre": "limite", "etiqueta": "Top N", "tipo": "int", "defecto": 20, "maximo": 500},
        ],
        "orden_opciones": {
            "Rating": "l.promedio_rating",
            "Ratings": "l.cantidad_ratings",
            "Título": "l.titulo",
            "Año": "YEAR(l.fecha_publicacion)",
        },
        "orden_defecto": "Rating",
        "orden_dir_defecto": "DESC",
        "sql": """
            SELECT l.libro_id AS `ID`, l.titulo AS `Título`,
                   (SELECT GROUP_CONCAT(a.nombre ORDER BY la.orden_autoria, a.nombre SEPARATOR ' / ')
                      FROM libro_autor la JOIN autor a ON a.autor_id = la.autor_id
                     WHERE la.libro_id = l.libro_id) AS `Autores`,
                   ed.nombre AS `Editorial`, i.codigo AS `Idioma`, l.promedio_rating AS `Rating`,
                   l.cantidad_ratings AS `Ratings`, YEAR(l.fecha_publicacion) AS `Año`
            FROM libro l
            JOIN editorial ed ON ed.editorial_id = l.editorial_id
            JOIN idioma i ON i.idioma_id = l.idioma_id
            WHERE (:idioma IS NULL OR l.idioma_id = :idioma)
              AND l.cantidad_ratings >= COALESCE(:min_ratings, 0)
              AND (:autor IS NULL OR EXISTS (
                    SELECT 1 FROM libro_autor la JOIN autor a ON a.autor_id = la.autor_id
                     WHERE la.libro_id = l.libro_id AND a.nombre LIKE :autor_like))
            ORDER BY {ORDER_BY}, l.cantidad_ratings DESC
            LIMIT :limite""",
    },
    "autores": {
        "modulo": "Libros", "titulo": "Autores con más libros publicados",
        "params": [
            {"nombre": "min_libros", "etiqueta": "Mínimo de libros", "tipo": "int", "defecto": 2},
            {"nombre": "limite", "etiqueta": "Top N", "tipo": "int", "defecto": 20, "maximo": 500},
        ],
        "orden_opciones": {
            "Libros": "COUNT(*)",
            "Rating promedio": "AVG(l.promedio_rating)",
            "Autor": "a.nombre",
        },
        "orden_defecto": "Libros",
        "orden_dir_defecto": "DESC",
        "sql": """
            SELECT a.nombre AS `Autor`, COUNT(*) AS `Libros`,
                   ROUND(AVG(l.promedio_rating), 2) AS `Rating promedio`,
                   SUM(l.cantidad_ratings) AS `Total ratings`,
                   MIN(YEAR(l.fecha_publicacion)) AS `Primer libro`,
                   MAX(YEAR(l.fecha_publicacion)) AS `Último libro`
            FROM autor a
            JOIN libro_autor la ON la.autor_id = a.autor_id
            JOIN libro l ON l.libro_id = la.libro_id
            GROUP BY a.autor_id, a.nombre
            HAVING COUNT(*) >= COALESCE(:min_libros, 1)
            ORDER BY {ORDER_BY}
            LIMIT :limite""",
    },
    "libros_editorial": {
        "modulo": "Libros", "titulo": "Libros por editorial y rango de años (F1 vs F2)",
        "params": [
            {"nombre": "editorial", "etiqueta": "Editorial contiene", "tipo": "text"},
            {"nombre": "anio_desde", "etiqueta": "Año F1 (Desde)", "tipo": "int"},
            {"nombre": "anio_hasta", "etiqueta": "Año F2 (Hasta)", "tipo": "int"},
            {"nombre": "limite", "etiqueta": "Top N", "tipo": "int", "defecto": 30, "maximo": 500},
        ],
        "orden_opciones": {
            "Libros": "COUNT(*)",
            "Rating promedio": "AVG(l.promedio_rating)",
            "Editorial": "ed.nombre",
        },
        "orden_defecto": "Libros",
        "orden_dir_defecto": "DESC",
        "sql": """
            SELECT ed.nombre AS `Editorial`, COUNT(*) AS `Libros`,
                   ROUND(AVG(l.promedio_rating), 2) AS `Rating promedio`,
                   ROUND(AVG(l.numero_paginas)) AS `Páginas promedio`
            FROM libro l JOIN editorial ed ON ed.editorial_id = l.editorial_id
            WHERE (:editorial IS NULL OR ed.nombre LIKE :editorial_like)
              AND (:anio_desde IS NULL OR YEAR(l.fecha_publicacion) >= :anio_desde)
              AND (:anio_hasta IS NULL OR YEAR(l.fecha_publicacion) <= :anio_hasta)
            GROUP BY ed.editorial_id, ed.nombre
            ORDER BY {ORDER_BY}
            LIMIT :limite""",
    },
    # ------------------------- PELÍCULAS -------------------------
    "peliculas": {
        "modulo": "Películas", "titulo": "Buscar películas por género y años (F1 vs F2)",
        "params": [
            {"nombre": "genero", "etiqueta": "Género", "tipo": "select",
             "opciones": "SELECT genero_id AS id, nombre AS txt FROM genero_pelicula ORDER BY nombre"},
            {"nombre": "titulo", "etiqueta": "Título contiene", "tipo": "text"},
            {"nombre": "anio_desde", "etiqueta": "Año F1 (Desde)", "tipo": "int"},
            {"nombre": "anio_hasta", "etiqueta": "Año F2 (Hasta)", "tipo": "int"},
            {"nombre": "limite", "etiqueta": "Top N", "tipo": "int", "defecto": 50, "maximo": 500},
        ],
        "orden_opciones": {
            "Año": "p.anio_estreno",
            "Título": "p.titulo",
            "ID": "p.pelicula_id",
        },
        "orden_defecto": "Año",
        "orden_dir_defecto": "DESC",
        "sql": """
            SELECT p.pelicula_id AS `ID`, p.titulo AS `Título`, p.anio_estreno AS `Año`,
                   (SELECT GROUP_CONCAT(g.nombre ORDER BY g.nombre SEPARATOR ' / ')
                      FROM pelicula_genero pg JOIN genero_pelicula g ON g.genero_id = pg.genero_id
                     WHERE pg.pelicula_id = p.pelicula_id) AS `Géneros`
            FROM pelicula p
            WHERE (:genero IS NULL OR EXISTS (SELECT 1 FROM pelicula_genero pg
                                              WHERE pg.pelicula_id = p.pelicula_id AND pg.genero_id = :genero))
              AND (:titulo IS NULL OR p.titulo LIKE :titulo_like)
              AND (:anio_desde IS NULL OR p.anio_estreno >= :anio_desde)
              AND (:anio_hasta IS NULL OR p.anio_estreno <= :anio_hasta)
            ORDER BY {ORDER_BY}, p.titulo
            LIMIT :limite""",
    },
    "generos_decada": {
        "modulo": "Películas", "titulo": "Películas por género y década",
        "params": [
            {"nombre": "genero", "etiqueta": "Género", "tipo": "select",
             "opciones": "SELECT genero_id AS id, nombre AS txt FROM genero_pelicula ORDER BY nombre"},
        ],
        "orden_opciones": {
            "Género": "g.nombre",
            "Década": "`Década`",
            "Películas": "COUNT(*)",
        },
        "orden_defecto": "Género",
        "sql": """
            SELECT g.nombre AS `Género`, FLOOR(p.anio_estreno / 10) * 10 AS `Década`, COUNT(*) AS `Películas`
            FROM pelicula p
            JOIN pelicula_genero pg ON pg.pelicula_id = p.pelicula_id
            JOIN genero_pelicula g ON g.genero_id = pg.genero_id
            WHERE p.anio_estreno IS NOT NULL AND (:genero IS NULL OR g.genero_id = :genero)
            GROUP BY g.genero_id, g.nombre, FLOOR(p.anio_estreno / 10)
            ORDER BY {ORDER_BY}""",
    },
}


def _leer_params(rep, args):
    """Convierte los valores del formulario y resuelve el ordenamiento seguro (ASC/DESC)."""
    params, valores, errores = {}, {}, []
    enviado = "ejecutar" in args
    for p in rep["params"]:
        crudo = (args.get(p["nombre"]) or "").strip()
        if not crudo and not enviado:
            if "defecto" in p:
                crudo = str(p["defecto"]() if callable(p["defecto"]) else p["defecto"])
            elif "defecto_sql" in p:
                v = db.escalar(p["defecto_sql"])
                crudo = "" if v is None else str(v)
        valores[p["nombre"]] = crudo
        val = None
        if crudo:
            try:
                if p["tipo"] == "int" or (p["tipo"] == "select" and "opciones" in p):
                    val = int(crudo)
                    if p.get("maximo") and val > p["maximo"]:
                        val = p["maximo"]
                elif p["tipo"] == "date":
                    val = date.fromisoformat(crudo)
                else:
                    val = crudo
            except ValueError:
                errores.append(f"{p['etiqueta']}: valor no válido.")
        if val is None and p.get("requerido"):
            errores.append(f"{p['etiqueta']} es obligatorio.")
        params[p["nombre"]] = val
        if p["tipo"] == "text":
            params[p["nombre"] + "_like"] = f"%{val}%" if val else None

    if "limite" in params and params["limite"] is None:
        params["limite"] = 50

    # Ordenamiento dinámico por lista blanca
    opciones_ord = rep.get("orden_opciones", {})
    orden_sel = args.get("orden") if args.get("orden") in opciones_ord else rep.get("orden_defecto")
    dir_def = rep.get("orden_dir_defecto", "ASC")
    dir_sel = args.get("dir", dir_def).upper()
    if dir_sel not in ("ASC", "DESC"):
        dir_sel = dir_def

    valores["orden"] = orden_sel or ""
    valores["dir"] = dir_sel
    expr_ord = opciones_ord.get(orden_sel, "1")
    order_clause = f"{expr_ord} {dir_sel}"

    return params, valores, errores, order_clause


def _renderizar_pdf(html_str):
    """Convierte HTML UTF-8 en bytes de un archivo PDF válido usando xhtml2pdf."""
    try:
        src_buf = io.BytesIO(html_str.encode("utf-8"))
        pdf_buf = io.BytesIO()
        status = pisa.CreatePDF(src_buf, dest=pdf_buf, encoding="utf-8")
        if status.err:
            return None
        pdf_buf.seek(0)
        return pdf_buf.getvalue()
    except Exception:
        import logging
        logging.exception("Error renderizando PDF con xhtml2pdf")
        return None


@bp.route("/")
@permiso_requerido("leer")
def indice():
    return render_template("consultas/indice.html", reportes=REPORTES)


@bp.route("/<clave>")
@permiso_requerido("leer")
def ejecutar(clave):
    rep = REPORTES.get(clave) or abort(404)
    params, valores, errores, order_clause = _leer_params(rep, request.args)
    opciones = {}
    for p in rep["params"]:
        if p["tipo"] == "select":
            opciones[p["nombre"]] = (db.consultar(p["opciones"]) if "opciones" in p
                                     else [{"id": i, "txt": t} for i, t in p["lista"]])

    filas, columnas, charts = [], [], []
    if not errores:
        sql_final = rep["sql"].replace("{ORDER_BY}", order_clause)
        filas = db.consultar(sql_final, params)
        columnas = list(filas[0].keys()) if filas else []
        charts = graficos.generar_graficos_reporte(clave)

        exportar = request.args.get("exportar")
        if exportar == "csv":
            auditoria.registrar("EXPORTAR_CSV", None, {"reporte": clave, "filas": len(filas), "filtros": valores})
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(columnas)
            w.writerows([[f[c] for c in columnas] for f in filas])
            return Response("\ufeff" + buf.getvalue(), mimetype="text/csv",
                            headers={"Content-Disposition": f"attachment; filename={clave}.csv"})

        if exportar in ("pdf", "pdf_preview"):
            auditoria.registrar("EXPORTAR_PDF", None, {"reporte": clave, "filas": len(filas), "modo": exportar})
            usuario_actual = g.get("usuario")
            nombre_usuario = usuario_actual["username"] if usuario_actual else "Sistema"
            html_pdf = render_template(
                "consultas/reporte_pdf.html",
                rep=rep,
                filas=filas,
                columnas=columnas,
                charts=charts,
                valores=valores,
                fecha_generacion=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                generado_por=nombre_usuario,
            )
            pdf_bytes = _renderizar_pdf(html_pdf)
            if pdf_bytes is None:
                abort(500, description="Error al generar el documento PDF.")
            disposicion = "inline" if exportar == "pdf_preview" else "attachment"
            return Response(
                pdf_bytes,
                mimetype="application/pdf",
                headers={"Content-Disposition": f"{disposicion}; filename=reporte_{clave}.pdf"},
            )

    return render_template(
        "consultas/reporte.html",
        clave=clave,
        rep=rep,
        valores=valores,
        opciones=opciones,
        filas=filas,
        columnas=columnas,
        charts=charts,
        errores=errores,
    )