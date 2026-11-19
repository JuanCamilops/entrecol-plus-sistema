"""
Carga de archivos desde la aplicación: un usuario autenticado sube un CSV/XLSX
con la misma estructura de los archivos iniciales y se procesa con ingesta.py.
"""
import uuid
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request,
                   send_file, url_for)
from werkzeug.utils import secure_filename

import auditoria
import db
import ingesta
from config import BASE_DIR
from seguridad import permiso_requerido, tiene_permiso

bp = Blueprint("cargas", __name__, url_prefix="/cargas")


def _extension_valida(nombre):
    return "." in nombre and nombre.rsplit(".", 1)[1].lower() in current_app.config["EXTENSIONES_PERMITIDAS"]


@bp.route("/", methods=["GET", "POST"])
@permiso_requerido("cargar")
def subir():
    resultado = None
    if request.method == "POST":
        tipo = request.form.get("tipo", "")
        archivo = request.files.get("archivo")
        if tipo not in ingesta.TIPOS_CARGA:
            flash("Selecciona el tipo de archivo a cargar.", "danger")
        elif not archivo or not archivo.filename:
            flash("Selecciona un archivo.", "danger")
        elif not _extension_valida(archivo.filename):
            flash("Solo se permiten archivos .csv o .xlsx", "danger")
        else:
            nombre = secure_filename(archivo.filename) or "archivo"
            carpeta = Path(current_app.config["UPLOAD_FOLDER"])
            carpeta.mkdir(parents=True, exist_ok=True)
            destino = carpeta / f"{uuid.uuid4().hex}_{nombre}"
            archivo.save(destino)
            resultado = ingesta.procesar_carga(destino, archivo.filename, tipo,
                                               g.usuario["id_usuario"], ip=auditoria.ip_cliente())
            # se conserva el archivo original con el id de la carga (trazabilidad)
            destino.replace(carpeta / f"carga_{resultado['id_carga']}_{nombre}")
            cat = {"COMPLETADA": "success", "PARCIAL": "warning", "SIN_CAMBIOS": "info"}.get(
                resultado["estado"], "danger")
            flash(f"{resultado['estado']}: {resultado['mensaje']}", cat)
    return render_template("cargas/subir.html", tipos=ingesta.TIPOS_CARGA, resultado=resultado,
                           tipo_sel=request.form.get("tipo") or request.args.get("tipo", ""))


@bp.route("/historial")
@permiso_requerido("cargar")
def historial():
    solo_mias = not tiene_permiso("admin")
    filas = db.consultar(
        "SELECT c.*, u.username FROM carga_archivo c JOIN usuario u ON u.id_usuario = c.id_usuario "
        "WHERE (:todas = 1 OR c.id_usuario = :u) ORDER BY c.id_carga DESC LIMIT 300",
        {"todas": 0 if solo_mias else 1, "u": g.usuario["id_usuario"]})
    rech_dir = Path(current_app.config["UPLOAD_FOLDER"]) / "rechazos"
    for f in filas:
        f["tiene_rechazos"] = (rech_dir / f"rechazos_{f['id_carga']}.csv").exists()
    return render_template("cargas/historial.html", filas=filas, tipos=ingesta.TIPOS_CARGA)


@bp.route("/<int:id_carga>/rechazos.csv")
@permiso_requerido("cargar")
def rechazos(id_carga):
    carga = db.consultar_uno("SELECT id_usuario FROM carga_archivo WHERE id_carga = :id", {"id": id_carga})
    if not carga or (carga["id_usuario"] != g.usuario["id_usuario"] and not tiene_permiso("admin")):
        abort(404)
    ruta = Path(current_app.config["UPLOAD_FOLDER"]) / "rechazos" / f"rechazos_{id_carga}.csv"
    if not ruta.exists():
        abort(404)
    return send_file(ruta, as_attachment=True, download_name=f"rechazos_carga_{id_carga}.csv")


@bp.route("/plantilla/<tipo>.csv")
@permiso_requerido("cargar")
def plantilla(tipo):
    t = ingesta.TIPOS_CARGA.get(tipo) or abort(404)
    return send_file(BASE_DIR / "datos_ejemplo" / t["ejemplo"], as_attachment=True,
                     download_name=f"plantilla_{tipo}.csv")
