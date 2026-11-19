"""
Administración (solo rol ADMIN): gestión de usuarios y consulta de auditoría.
"""
import math

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

import auditoria
import db
from crud import mensaje_integridad
from seguridad import cifrar_password, errores_password, errores_usuario, permiso_requerido

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _roles():
    return db.consultar("SELECT id_rol, nombre FROM rol ORDER BY id_rol")


# ---------------- Usuarios ----------------
@bp.route("/usuarios")
@permiso_requerido("admin")
def usuarios():
    q = (request.args.get("q") or "").strip()
    filas = db.consultar(
        "SELECT u.id_usuario, u.username, u.correo, u.activo, u.intentos_fallidos, u.fecha_creacion, "
        "r.nombre AS rol FROM usuario u JOIN rol r ON r.id_rol = u.id_rol "
        "WHERE (:q = '' OR u.username LIKE :ql OR u.correo LIKE :ql) ORDER BY u.username",
        {"q": q, "ql": f"%{q}%"})
    return render_template("admin/usuarios.html", filas=filas, q=q)


@bp.route("/usuarios/nuevo", methods=["GET", "POST"])
@permiso_requerido("admin")
def usuario_nuevo():
    datos = {"username": "", "correo": "", "id_rol": None}
    if request.method == "POST":
        datos = {"username": request.form.get("username", "").strip(),
                 "correo": request.form.get("correo", "").strip().lower(),
                 "id_rol": request.form.get("id_rol", type=int)}
        clave = request.form.get("password", "")
        errores = errores_usuario(datos["username"], datos["correo"])
        reglas = errores_password(clave, datos["username"])
        if reglas:
            errores.append("La contraseña necesita: " + ", ".join(reglas) + ".")
        if not any(r["id_rol"] == datos["id_rol"] for r in _roles()):
            errores.append("Selecciona un rol válido.")
        if not errores:
            try:
                with db.transaccion() as conn:
                    res = conn.execute(text(
                        "INSERT INTO usuario (username, password_hash, correo, id_rol) VALUES (:u, :h, :c, :r)"),
                        {"u": datos["username"], "h": cifrar_password(clave), "c": datos["correo"],
                         "r": datos["id_rol"]})
                    auditoria.registrar("INSERT", "usuario", {"id_usuario": res.lastrowid,
                                                              "username": datos["username"],
                                                              "id_rol": datos["id_rol"]}, conn=conn)
                flash("Usuario creado.", "success")
                return redirect(url_for("admin.usuarios"))
            except IntegrityError:
                errores.append("El usuario o el correo ya existen.")
        for e in errores:
            flash(e, "danger")
    return render_template("admin/usuario_form.html", datos=datos, roles=_roles(), creando=True)


@bp.route("/usuarios/<int:id_usuario>", methods=["GET", "POST"])
@permiso_requerido("admin")
def usuario_editar(id_usuario):
    u = db.consultar_uno("SELECT id_usuario, username, correo, activo, intentos_fallidos, id_rol "
                         "FROM usuario WHERE id_usuario = :id", {"id": id_usuario})
    if not u:
        abort(404)
    if request.method == "POST":
        nuevo = {"correo": request.form.get("correo", "").strip().lower(),
                 "id_rol": request.form.get("id_rol", type=int),
                 "activo": 1 if request.form.get("activo") else 0}
        clave = request.form.get("password", "")
        errores = errores_usuario(u["username"], nuevo["correo"])
        if not any(r["id_rol"] == nuevo["id_rol"] for r in _roles()):
            errores.append("Selecciona un rol válido.")
        es_yo = id_usuario == g.usuario["id_usuario"]
        rol_admin = db.escalar("SELECT id_rol FROM rol WHERE nombre = 'ADMIN'")
        if es_yo and (not nuevo["activo"] or nuevo["id_rol"] != rol_admin):
            errores.append("No puedes desactivarte ni quitarte el rol ADMIN a ti mismo.")
        if clave:
            reglas = errores_password(clave, u["username"])
            if reglas:
                errores.append("La contraseña necesita: " + ", ".join(reglas) + ".")
        if not errores:
            cambios = {k: [u[k], v] for k, v in nuevo.items() if u[k] != v}
            sets = "correo = :correo, id_rol = :id_rol, activo = :activo"
            params = {**nuevo, "id": id_usuario}
            if nuevo["activo"] and not u["activo"]:
                sets += ", intentos_fallidos = 0"  # desbloqueo
            if clave:
                sets += ", password_hash = :h"
                params["h"] = cifrar_password(clave)
                cambios["password"] = "restablecida"
            try:
                with db.transaccion() as conn:
                    conn.execute(text(f"UPDATE usuario SET {sets} WHERE id_usuario = :id"), params)
                    if cambios:
                        auditoria.registrar("UPDATE", "usuario", {"id_usuario": id_usuario,
                                                                  "username": u["username"],
                                                                  "cambios": cambios}, conn=conn)
                flash("Usuario actualizado.", "success")
                return redirect(url_for("admin.usuarios"))
            except IntegrityError:
                errores.append("Ese correo ya está en uso.")
        for e in errores:
            flash(e, "danger")
        u.update(nuevo)
    return render_template("admin/usuario_form.html", datos=u, roles=_roles(), creando=False)


@bp.route("/usuarios/<int:id_usuario>/desbloquear", methods=["POST"])
@permiso_requerido("admin")
def usuario_desbloquear(id_usuario):
    with db.transaccion() as conn:
        n = conn.execute(text("UPDATE usuario SET activo = 1, intentos_fallidos = 0 WHERE id_usuario = :id"),
                         {"id": id_usuario}).rowcount
        if n:
            auditoria.registrar("DESBLOQUEO", "usuario", {"id_usuario": id_usuario}, conn=conn)
    flash("Usuario desbloqueado." if n else "Usuario no encontrado.", "success" if n else "warning")
    return redirect(url_for("admin.usuarios"))


@bp.route("/usuarios/<int:id_usuario>/eliminar", methods=["POST"])
@permiso_requerido("admin")
def usuario_eliminar(id_usuario):
    if id_usuario == g.usuario["id_usuario"]:
        flash("No puedes eliminar tu propio usuario.", "danger")
        return redirect(url_for("admin.usuarios"))
    try:
        with db.transaccion() as conn:
            u = conn.execute(text("SELECT username FROM usuario WHERE id_usuario = :id"),
                             {"id": id_usuario}).scalar()
            conn.execute(text("DELETE FROM usuario WHERE id_usuario = :id"), {"id": id_usuario})
            auditoria.registrar("DELETE", "usuario", {"id_usuario": id_usuario, "username": u}, conn=conn)
        flash("Usuario eliminado.", "success")
    except IntegrityError as ex:
        flash(mensaje_integridad(ex) + " El usuario tiene auditoría o cargas: desactívalo en vez de "
              "eliminarlo.", "danger")
    return redirect(url_for("admin.usuarios"))


# ---------------- Auditoría ----------------
@bp.route("/auditoria")
@permiso_requerido("admin")
def ver_auditoria():
    a = request.args
    where, p = [], {}
    if a.get("usuario"):
        where.append("u.username LIKE :usuario")
        p["usuario"] = f"%{a['usuario'].strip()}%"
    if a.get("accion"):
        where.append("a.accion = :accion")
        p["accion"] = a["accion"]
    if a.get("tabla"):
        where.append("a.tabla_afectada = :tabla")
        p["tabla"] = a["tabla"]
    if a.get("desde"):
        where.append("a.fecha_hora >= :desde")
        p["desde"] = a["desde"]
    if a.get("hasta"):
        where.append("a.fecha_hora < DATE_ADD(:hasta, INTERVAL 1 DAY)")
        p["hasta"] = a["hasta"]
    if a.get("q"):
        where.append("a.detalle LIKE :q")
        p["q"] = f"%{a['q'].strip()}%"
    base = ("FROM auditoria a LEFT JOIN usuario u ON u.id_usuario = a.id_usuario"
            + (" WHERE " + " AND ".join(where) if where else ""))
    total = db.escalar(f"SELECT COUNT(*) {base}", p)
    paginas = max(1, math.ceil(total / 50))
    pagina = min(max(1, a.get("pagina", 1, type=int) or 1), paginas)
    filas = db.consultar(f"SELECT a.*, u.username {base} ORDER BY a.id_auditoria DESC "
                         f"LIMIT 50 OFFSET :off", {**p, "off": (pagina - 1) * 50})
    acciones = [r["accion"] for r in db.consultar("SELECT DISTINCT accion FROM auditoria ORDER BY accion")]
    tablas = [r["t"] for r in db.consultar("SELECT DISTINCT tabla_afectada AS t FROM auditoria "
                                           "WHERE tabla_afectada IS NOT NULL ORDER BY t")]
    return render_template("admin/auditoria.html", filas=filas, total=total, pagina=pagina,
                           paginas=paginas, acciones=acciones, tablas=tablas, args=a)
