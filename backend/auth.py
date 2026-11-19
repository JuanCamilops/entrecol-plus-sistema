"""
Autenticación: login con captcha, bloqueo por intentos fallidos, logout,
registro de usuarios y cambio de contraseña.
"""
from flask import (Blueprint, current_app, flash, g, make_response, redirect,
                   render_template, request, session, url_for)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

import auditoria
import captcha
import db
from seguridad import (cifrar_password, errores_password, errores_usuario, login_requerido,
                       url_segura, verificar_password)

bp = Blueprint("auth", __name__)
_HASH_FICTICIO = None  # para igualar tiempos cuando el usuario no existe


def _hash_ficticio():
    global _HASH_FICTICIO
    if _HASH_FICTICIO is None:
        _HASH_FICTICIO = cifrar_password("usuario-inexistente")
    return _HASH_FICTICIO


@bp.route("/captcha.png")
def captcha_img():
    resp = make_response(captcha.generar_imagen())
    resp.headers["Content-Type"] = "image/png"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.get("usuario"):
        return redirect(url_for("inicio"))
    if request.method == "GET":
        return render_template("auth/login.html", captcha_modo=captcha.modo())

    username = request.form.get("username", "").strip()
    clave = request.form.get("password", "")
    destino = request.args.get("next", "")
    max_int = current_app.config["MAX_INTENTOS_FALLIDOS"]

    def fallo(msg, categoria="danger"):
        flash(msg, categoria)
        return render_template("auth/login.html", captcha_modo=captcha.modo(),
                               username=username), 401

    if not username or not clave:
        return fallo("Escribe usuario y contraseña.")

    # Factor 2: captcha (se valida ANTES de revisar credenciales)
    if not captcha.validar(request.form):
        auditoria.registrar("LOGIN_CAPTCHA_FALLIDO", "usuario", {"username": username})
        return fallo("El código captcha es incorrecto o venció. Inténtalo de nuevo.")

    u = db.consultar_uno(
        "SELECT id_usuario, username, password_hash, activo, intentos_fallidos "
        "FROM usuario WHERE username = :u", {"u": username})

    if not u:
        verificar_password(_hash_ficticio(), clave)  # mismo tiempo de respuesta
        auditoria.registrar("LOGIN_FALLIDO", "usuario", {"username": username,
                                                          "motivo": "usuario no existe"})
        return fallo("Usuario o contraseña incorrectos.")

    if not u["activo"]:
        auditoria.registrar("LOGIN_BLOQUEADO", "usuario", {"username": username},
                            id_usuario=u["id_usuario"])
        return fallo("La cuenta está bloqueada o inactiva. Contacta al administrador.")

    # Factor 1: contraseña
    if not verificar_password(u["password_hash"], clave):
        with db.transaccion() as conn:
            conn.execute(text("UPDATE usuario SET intentos_fallidos = intentos_fallidos + 1 "
                              "WHERE id_usuario = :id"), {"id": u["id_usuario"]})
            intentos = conn.execute(text("SELECT intentos_fallidos FROM usuario "
                                         "WHERE id_usuario = :id"), {"id": u["id_usuario"]}).scalar()
            if intentos >= max_int:
                conn.execute(text("UPDATE usuario SET activo = 0 WHERE id_usuario = :id"),
                             {"id": u["id_usuario"]})
            auditoria.registrar("LOGIN_FALLIDO", "usuario",
                                {"username": username, "intentos": intentos},
                                id_usuario=u["id_usuario"], conn=conn)
            if intentos >= max_int:
                auditoria.registrar("BLOQUEO_CUENTA", "usuario",
                                    {"username": username, "intentos": intentos},
                                    id_usuario=u["id_usuario"], conn=conn)
        if intentos >= max_int:
            return fallo(f"Cuenta bloqueada por {max_int} intentos fallidos. "
                         "Un administrador debe desbloquearla.")
        return fallo(f"Usuario o contraseña incorrectos. Te quedan {max_int - intentos} intento(s).")

    # Éxito: reiniciar intentos y crear sesión nueva (evita fijación de sesión)
    db.ejecutar("UPDATE usuario SET intentos_fallidos = 0 WHERE id_usuario = :id",
                {"id": u["id_usuario"]})
    session.clear()
    session.permanent = True
    session["id_usuario"] = u["id_usuario"]
    auditoria.registrar("LOGIN_OK", "usuario", {"username": username},
                        id_usuario=u["id_usuario"])
    flash(f"Bienvenido, {u['username']}.", "success")
    return redirect(destino if url_segura(destino) else url_for("inicio"))


@bp.route("/logout", methods=["POST"])
def logout():
    if g.get("usuario"):
        auditoria.registrar("LOGOUT", "usuario")
    session.clear()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/registro", methods=["GET", "POST"])
def registro():
    if g.get("usuario"):
        return redirect(url_for("inicio"))
    datos = {"username": "", "correo": ""}
    if request.method == "POST":
        datos = {"username": request.form.get("username", "").strip(),
                 "correo": request.form.get("correo", "").strip().lower()}
        clave = request.form.get("password", "")
        clave2 = request.form.get("password2", "")
        errores = errores_usuario(datos["username"], datos["correo"])
        reglas = errores_password(clave, datos["username"])
        if reglas:
            errores.append("La contraseña necesita: " + ", ".join(reglas) + ".")
        if clave != clave2:
            errores.append("Las contraseñas no coinciden.")
        if not captcha.validar(request.form):
            errores.append("El código captcha es incorrecto o venció.")
        if not errores:
            try:
                with db.transaccion() as conn:
                    id_rol = conn.execute(text("SELECT id_rol FROM rol WHERE nombre = :n"),
                                          {"n": current_app.config["ROL_REGISTRO"]}).scalar()
                    res = conn.execute(text(
                        "INSERT INTO usuario (username, password_hash, correo, id_rol) "
                        "VALUES (:u, :h, :c, :r)"),
                        {"u": datos["username"], "h": cifrar_password(clave),
                         "c": datos["correo"], "r": id_rol})
                    auditoria.registrar("REGISTRO", "usuario", {"username": datos["username"]},
                                        id_usuario=res.lastrowid, conn=conn)
                flash("Cuenta creada. Ya puedes iniciar sesión.", "success")
                return redirect(url_for("auth.login"))
            except IntegrityError:
                errores.append("El usuario o el correo ya están registrados.")
        for e in errores:
            flash(e, "danger")
    return render_template("auth/registro.html", datos=datos, captcha_modo=captcha.modo())


@bp.route("/cambiar-password", methods=["GET", "POST"])
@login_requerido
def cambiar_password():
    if request.method == "POST":
        actual = request.form.get("actual", "")
        nueva = request.form.get("nueva", "")
        nueva2 = request.form.get("nueva2", "")
        h = db.escalar("SELECT password_hash FROM usuario WHERE id_usuario = :id",
                       {"id": g.usuario["id_usuario"]})
        errores = []
        if not verificar_password(h, actual):
            errores.append("La contraseña actual no es correcta.")
        reglas = errores_password(nueva, g.usuario["username"])
        if reglas:
            errores.append("La nueva contraseña necesita: " + ", ".join(reglas) + ".")
        if nueva != nueva2:
            errores.append("Las contraseñas nuevas no coinciden.")
        if nueva and nueva == actual:
            errores.append("La nueva contraseña debe ser distinta a la actual.")
        if not errores:
            with db.transaccion() as conn:
                conn.execute(text("UPDATE usuario SET password_hash = :h WHERE id_usuario = :id"),
                             {"h": cifrar_password(nueva), "id": g.usuario["id_usuario"]})
                auditoria.registrar("CAMBIO_PASSWORD", "usuario", conn=conn)
            flash("Contraseña actualizada.", "success")
            return redirect(url_for("inicio"))
        for e in errores:
            flash(e, "danger")
    return render_template("auth/cambiar_password.html")
