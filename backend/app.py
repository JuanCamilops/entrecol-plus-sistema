"""
Aplicación Flask del proyecto de Bases de Datos.
Ejecutar:  python backend\app.py   ->  http://127.0.0.1:5000
"""
import logging
from datetime import date, datetime
from decimal import Decimal

from flask import Flask, g, jsonify, render_template, request, url_for
from sqlalchemy.exc import OperationalError

import db
from config import Config


def create_app(config=Config):
    app = Flask(__name__)
    app.config.from_object(config)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db.init_engine(config)

    import admin, auth, cargas, consultas, crud
    from seguridad import (cabeceras_seguridad, cargar_usuario_actual, login_requerido,
                           tiene_permiso, token_csrf, validar_csrf)

    for bp in (auth.bp, crud.bp, consultas.bp, cargas.bp, admin.bp):
        app.register_blueprint(bp)

    @app.before_request
    def antes():
        cargar_usuario_actual()
        validar_csrf()

    @app.after_request
    def aplicar_cabeceras(resp):
        resp = cabeceras_seguridad(resp)
        if resp.mimetype == "application/pdf":
            resp.headers.pop("Content-Security-Policy", None)
            resp.headers["X-Frame-Options"] = "SAMEORIGIN"
        return resp

    def url_con(**cambios):
        """URL de la página actual conservando los filtros y cambiando solo lo indicado."""
        args = request.args.to_dict()
        args.update(cambios)
        args = {k: v for k, v in args.items() if v not in (None, "")}
        return url_for(request.endpoint, **(request.view_args or {}), **args)

    def pk_de(e, fila):
        return {k: fila[k] for k in e.pk}

    @app.context_processor
    def contexto():
        return {"csrf_token": token_csrf, "usuario": g.get("usuario"), "tiene_permiso": tiene_permiso,
                "menu": crud.menu_entidades() if g.get("usuario") else {},
                "url_con": url_con, "pk_de": pk_de}

    @app.template_filter("num")
    def f_num(v, dec=0):
        if v is None or v == "":
            return ""
        if isinstance(v, (int, float, Decimal)):
            return f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return v

    @app.template_filter("celda")
    def f_celda(v):
        if v is None:
            return ""
        if isinstance(v, datetime):
            return v.strftime("%Y-%m-%d %H:%M")
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, Decimal):
            return f_num(v, 2)
        return v

    @app.route("/")
    @login_requerido
    def inicio():
        conteos = {}
        tablas_panel = [("libro", "Libros"), ("autor", "Autores"),
                        ("pelicula", "Películas"), ("genero_pelicula", "Géneros")]
        if tiene_permiso("escribir"):
            tablas_panel = [("empleado", "Empleados"), ("detalle_nomina", "Liquidaciones")] + tablas_panel
        for tabla, nombre in tablas_panel:
            conteos[nombre] = db.escalar(f"SELECT COUNT(*) FROM `{tabla}`")

        cargas_rec = []
        if tiene_permiso("escribir"):
            cargas_rec = db.consultar(
                "SELECT c.id_carga, c.nombre_archivo, c.tipo_archivo, c.fecha_hora, c.estado, "
                "c.registros_cargados, c.registros_leidos, u.username FROM carga_archivo c "
                "JOIN usuario u ON u.id_usuario = c.id_usuario ORDER BY c.id_carga DESC LIMIT 5")

        eventos = []
        if tiene_permiso("admin"):
            eventos = db.consultar(
                "SELECT a.fecha_hora, a.accion, a.tabla_afectada, a.ip, u.username FROM auditoria a "
                "LEFT JOIN usuario u ON u.id_usuario = a.id_usuario ORDER BY a.id_auditoria DESC LIMIT 8")
        return render_template("inicio.html", conteos=conteos, cargas=cargas_rec, eventos=eventos)  
    
    @app.route("/salud")
    def salud():
        ok = db.bd_disponible()
        return jsonify({"app": "ok", "base_datos": "ok" if ok else "sin conexión"}), (200 if ok else 503)

    def error(codigo, titulo, detalle):
        return render_template("error.html", codigo=codigo, titulo=titulo, detalle=detalle), codigo

    @app.errorhandler(400)
    def e400(e):
        return error(400, "Solicitud inválida", getattr(e, "description", ""))

    @app.errorhandler(403)
    def e403(e):
        return error(403, "Acceso denegado", "Tu rol no tiene permiso para esta acción.")

    @app.errorhandler(404)
    def e404(e):
        return error(404, "No encontrado", "La página o el registro no existe.")

    @app.errorhandler(413)
    def e413(e):
        mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        return error(413, "Archivo demasiado grande", f"El tamaño máximo es {mb} MB.")

    @app.errorhandler(OperationalError)
    def e_bd(e):
        app.logger.error("Error de conexión a MySQL: %s", e)
        g.usuario = None
        return error(503, "Base de datos no disponible",
                     "No hay conexión con MySQL. Verifica que esté encendido el servicio y que exista la base "
                     f"`{app.config['DB_NAME']}`.")

    @app.errorhandler(500)
    def e500(e):
        return error(500, "Error interno", "Ocurrió un error inesperado. Revisa la consola del servidor.")

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)