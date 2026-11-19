"""
Generador de los 8 gráficos estadísticos requeridos con matplotlib.
Renderiza en modo headless ('Agg') y devuelve imágenes PNG codificadas en Base64
para incrustarlas directamente en HTML y en los reportes PDF (xhtml2pdf).
"""
import base64
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import db

PALETA = [
    "#1e3a8a", "#2563eb", "#0d9488", "#059669", "#d97706",
    "#dc2626", "#7c3aed", "#db2777", "#4f46e5", "#0284c7",
]


def _fig_a_base64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def grafico_1_torta_departamentos():
    """1. Gráfico de torta: Distribución de empleados por departamento."""
    filas = db.consultar("""
        SELECT d.nombre AS etiqueta, COUNT(e.empleado_id) AS total
        FROM departamento d
        LEFT JOIN empleado e ON e.departamento_id = d.departamento_id
        GROUP BY d.departamento_id, d.nombre
        HAVING total > 0
        ORDER BY total DESC
    """)
    if not filas:
        return None
    etiquetas = [f["etiqueta"] for f in filas]
    valores = [int(f["total"]) for f in filas]

    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    wedges, texts, autotexts = ax.pie(
        valores,
        labels=etiquetas,
        autopct=lambda pct: f"{pct:.1f}%\n({int(round(pct / 100.0 * sum(valores)))})",
        startangle=140,
        colors=PALETA[: len(valores)],
        textprops={"fontsize": 8.5},
    )
    for at in autotexts:
        at.set_color("white")
        at.set_weight("bold")
    ax.set_title("1. Distribución de Empleados por Departamento", fontsize=11, fontweight="bold", pad=12)
    return _fig_a_base64(fig)


def grafico_2_barras_masa_salarial():
    """2. Gráfico de barras: Masa salarial (Sueldo Base) por departamento."""
    filas = db.consultar("""
        SELECT d.nombre AS etiqueta, COALESCE(SUM(e.sueldo_base), 0) / 1000000.0 AS millones
        FROM departamento d
        LEFT JOIN empleado e ON e.departamento_id = d.departamento_id
        GROUP BY d.departamento_id, d.nombre
        HAVING millones > 0
        ORDER BY millones DESC
    """)
    if not filas:
        return None
    etiquetas = [f["etiqueta"] for f in filas]
    valores = [float(f["millones"]) for f in filas]

    fig, ax = plt.subplots(figsize=(6.8, 4.0))
    bars = ax.bar(etiquetas, valores, color="#1e3a8a", width=0.55)
    ax.set_title("2. Masa Salarial Base por Departamento (Millones COP)", fontsize=11, fontweight="bold")
    ax.set_ylabel("Millones COP")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    plt.xticks(rotation=20, ha="right", fontsize=8.5)
    for bar in bars:
        h = bar.get_height()
        ax.annotate(f"${h:,.2f}M", xy=(bar.get_x() + bar.get_width() / 2, h),
                    xytext=(0, 3), textcoords="offset points", ha="center", fontsize=8, fontweight="bold")
    return _fig_a_base64(fig)


def grafico_3_frecuencia_eps_global():
    """3. Frecuencia global de afiliados por EPS."""
    filas = db.consultar("""
        SELECT x.nombre AS etiqueta, COUNT(e.empleado_id) AS total
        FROM eps x
        LEFT JOIN empleado e ON e.eps_id = x.eps_id
        GROUP BY x.eps_id, x.nombre
        HAVING total > 0
        ORDER BY total ASC
    """)
    if not filas:
        return None
    etiquetas = [f["etiqueta"] for f in filas]
    valores = [int(f["total"]) for f in filas]

    fig, ax = plt.subplots(figsize=(6.5, 3.8))
    bars = ax.barh(etiquetas, valores, color="#0d9488", height=0.55)
    ax.set_title("3. Frecuencia Global de Empleados por EPS", fontsize=11, fontweight="bold")
    ax.set_xlabel("Cantidad de Empleados")
    ax.grid(axis="x", linestyle="--", alpha=0.4)
    for bar in bars:
        w = bar.get_width()
        ax.annotate(f"{int(w)}", xy=(w, bar.get_y() + bar.get_height() / 2),
                    xytext=(4, 0), textcoords="offset points", va="center", fontsize=8.5, fontweight="bold")
    return _fig_a_base64(fig)


def grafico_4_frecuencia_pension_global():
    """4. Frecuencia global de afiliados por Fondo de Pensión."""
    filas = db.consultar("""
        SELECT x.nombre AS etiqueta, COUNT(e.empleado_id) AS total
        FROM fondo_pension x
        LEFT JOIN empleado e ON e.fondo_pension_id = x.fondo_pension_id
        GROUP BY x.fondo_pension_id, x.nombre
        HAVING total > 0
        ORDER BY total ASC
    """)
    if not filas:
        return None
    etiquetas = [f["etiqueta"] for f in filas]
    valores = [int(f["total"]) for f in filas]

    fig, ax = plt.subplots(figsize=(6.5, 3.8))
    bars = ax.barh(etiquetas, valores, color="#2563eb", height=0.55)
    ax.set_title("4. Frecuencia Global de Empleados por Fondo de Pensión", fontsize=11, fontweight="bold")
    ax.set_xlabel("Cantidad de Empleados")
    ax.grid(axis="x", linestyle="--", alpha=0.4)
    for bar in bars:
        w = bar.get_width()
        ax.annotate(f"{int(w)}", xy=(w, bar.get_y() + bar.get_height() / 2),
                    xytext=(4, 0), textcoords="offset points", va="center", fontsize=8.5, fontweight="bold")
    return _fig_a_base64(fig)


def grafico_5_eps_por_departamento():
    """5. Frecuencia de EPS desglosada por Departamento."""
    filas = db.consultar("""
        SELECT d.nombre AS dep, x.nombre AS ent, COUNT(e.empleado_id) AS total
        FROM empleado e
        JOIN departamento d ON d.departamento_id = e.departamento_id
        JOIN eps x ON x.eps_id = e.eps_id
        GROUP BY d.nombre, x.nombre
        ORDER BY d.nombre, x.nombre
    """)
    if not filas:
        return None
    deps = sorted({f["dep"] for f in filas})
    ents = sorted({f["ent"] for f in filas})
    matriz = {(f["dep"], f["ent"]): int(f["total"]) for f in filas}

    x = np.arange(len(deps))
    ancho = 0.8 / max(1, len(ents))
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for i, ent in enumerate(ents):
        vals = [matriz.get((d, ent), 0) for d in deps]
        ax.bar(x + i * ancho - 0.4 + ancho / 2, vals, width=ancho, label=ent, color=PALETA[i % len(PALETA)])

    ax.set_title("5. Distribución de EPS por Departamento", fontsize=11, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(deps, rotation=20, ha="right", fontsize=8.5)
    ax.set_ylabel("Empleados")
    ax.legend(title="EPS", fontsize=7.5, title_fontsize=8, loc="upper right")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    return _fig_a_base64(fig)


def grafico_6_pension_por_departamento():
    """6. Frecuencia de Fondo de Pensión desglosada por Departamento."""
    filas = db.consultar("""
        SELECT d.nombre AS dep, x.nombre AS ent, COUNT(e.empleado_id) AS total
        FROM empleado e
        JOIN departamento d ON d.departamento_id = e.departamento_id
        JOIN fondo_pension x ON x.fondo_pension_id = e.fondo_pension_id
        GROUP BY d.nombre, x.nombre
        ORDER BY d.nombre, x.nombre
    """)
    if not filas:
        return None
    deps = sorted({f["dep"] for f in filas})
    ents = sorted({f["ent"] for f in filas})
    matriz = {(f["dep"], f["ent"]): int(f["total"]) for f in filas}

    x = np.arange(len(deps))
    ancho = 0.8 / max(1, len(ents))
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for i, ent in enumerate(ents):
        vals = [matriz.get((d, ent), 0) for d in deps]
        ax.bar(x + i * ancho - 0.4 + ancho / 2, vals, width=ancho, label=ent, color=PALETA[(i + 2) % len(PALETA)])

    ax.set_title("6. Distribución de Fondo de Pensión por Departamento", fontsize=11, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(deps, rotation=20, ha="right", fontsize=8.5)
    ax.set_ylabel("Empleados")
    ax.legend(title="Fondo Pensión", fontsize=7.5, title_fontsize=8, loc="upper right")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    return _fig_a_base64(fig)


def grafico_7_peliculas_por_genero():
    """7. Top 12 géneros cinematográficos con más películas."""
    filas = db.consultar("""
        SELECT g.nombre AS etiqueta, COUNT(pg.pelicula_id) AS total
        FROM genero_pelicula g
        JOIN pelicula_genero pg ON pg.genero_id = g.genero_id
        GROUP BY g.genero_id, g.nombre
        ORDER BY total DESC
        LIMIT 12
    """)
    if not filas:
        return None
    filas.reverse()
    etiquetas = [f["etiqueta"] for f in filas]
    valores = [int(f["total"]) for f in filas]

    fig, ax = plt.subplots(figsize=(7.0, 4.3))
    bars = ax.barh(etiquetas, valores, color="#7c3aed", height=0.62)
    ax.set_title("7. Top 12 Géneros con Mayor Cantidad de Películas", fontsize=11, fontweight="bold")
    ax.set_xlabel("Cantidad de Películas")
    ax.grid(axis="x", linestyle="--", alpha=0.4)
    for bar in bars:
        w = bar.get_width()
        ax.annotate(f"{int(w):,}", xy=(w, bar.get_y() + bar.get_height() / 2),
                    xytext=(4, 0), textcoords="offset points", va="center", fontsize=8)
    return _fig_a_base64(fig)


def grafico_8_libros_por_anio():
    """8. Evolución de libros publicados por año (últimos 25 años registrados)."""
    filas = db.consultar("""
        SELECT YEAR(fecha_publicacion) AS anio, COUNT(*) AS total
        FROM libro
        WHERE fecha_publicacion IS NOT NULL
        GROUP BY YEAR(fecha_publicacion)
        ORDER BY anio DESC
        LIMIT 25
    """)
    if not filas:
        return None
    filas.reverse()
    anios = [str(f["anio"]) for f in filas]
    valores = [int(f["total"]) for f in filas]

    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    ax.plot(anios, valores, marker="o", color="#d97706", linewidth=2.2, markersize=5)
    ax.fill_between(anios, valores, color="#fef3c7", alpha=0.6)
    ax.set_title("8. Libros Publicados por Año (Últimos 25 Años con Registro)", fontsize=11, fontweight="bold")
    ax.set_ylabel("Cantidad de Libros")
    ax.grid(True, linestyle="--", alpha=0.4)
    plt.xticks(rotation=45, ha="right", fontsize=8)
    return _fig_a_base64(fig)


def generar_graficos_reporte(clave_reporte, incluir_nomina=True):
    """Devuelve lista de diccionarios con título e imagen base64 según permisos del usuario."""
    graficos_nomina = {
        grafico_1_torta_departamentos,
        grafico_2_barras_masa_salarial,
        grafico_3_frecuencia_eps_global,
        grafico_4_frecuencia_pension_global,
        grafico_5_eps_por_departamento,
        grafico_6_pension_por_departamento,
    }

    mapa = {
        "dashboard_estadistico": [
            ("Distribución de Empleados por Departamento", grafico_1_torta_departamentos),
            ("Masa Salarial Base por Departamento", grafico_2_barras_masa_salarial),
            ("Frecuencia Global por EPS", grafico_3_frecuencia_eps_global),
            ("Frecuencia Global por Fondo de Pensión", grafico_4_frecuencia_pension_global),
            ("Distribución de EPS por Departamento", grafico_5_eps_por_departamento),
            ("Distribución de Pensión por Departamento", grafico_6_pension_por_departamento),
            ("Top 12 Géneros de Películas", grafico_7_peliculas_por_genero),
            ("Libros Publicados por Año", grafico_8_libros_por_anio),
        ],
        "nomina_periodo": [
            ("Distribución de Empleados por Departamento", grafico_1_torta_departamentos),
            ("Masa Salarial Base por Departamento", grafico_2_barras_masa_salarial),
        ],
        "nomina_dependencia": [
            ("Masa Salarial Base por Departamento", grafico_2_barras_masa_salarial),
            ("Distribución de Empleados por Departamento", grafico_1_torta_departamentos),
        ],
        "afiliaciones": [
            ("Frecuencia Global por EPS", grafico_3_frecuencia_eps_global),
            ("Frecuencia Global por Fondo de Pensión", grafico_4_frecuencia_pension_global),
            ("Distribución de EPS por Departamento", grafico_5_eps_por_departamento),
            ("Distribución de Pensión por Departamento", grafico_6_pension_por_departamento),
        ],
        "top_libros": [
            ("Libros Publicados por Año", grafico_8_libros_por_anio),
        ],
        "libros_editorial": [
            ("Libros Publicados por Año", grafico_8_libros_por_anio),
        ],
        "peliculas": [
            ("Top 12 Géneros de Películas", grafico_7_peliculas_por_genero),
        ],
        "generos_decada": [
            ("Top 12 Géneros de Películas", grafico_7_peliculas_por_genero),
        ],
    }

    resultado = []
    for titulo, fn in mapa.get(clave_reporte, []):
        if not incluir_nomina and fn in graficos_nomina:
            continue
        img = fn()
        if img:
            resultado.append({"titulo": titulo, "img": img})
    return resultado