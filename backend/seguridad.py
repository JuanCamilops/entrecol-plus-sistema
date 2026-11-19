"""
Utilidades de seguridad:
- Cifrado (hash) y verificación de contraseñas (PBKDF2-SHA256, 600.000 iteraciones, con sal).
- Política de contraseñas y validación de datos de usuario.
- Decoradores login_requerido / permiso_requerido (control de acceso por rol).
- Protección CSRF para todos los formularios POST.
- Cabeceras HTTP de seguridad.
"""
import re
import secrets
from functools import wraps

from flask import abort, current_app, flash, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import db

RE_USERNAME = re.compile(r"^[A-Za-z0-9_.-]{4,50}$")
RE_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


# ---------------- Contraseñas ----------------
def cifrar_password(clave):
    return generate_password_hash(clave, method=current_app.config["HASH_METODO"])


def verificar_password(hash_guardado, clave):
    return check_password_hash(hash_guardado, clave)


def errores_password(clave, username=""):
    """Devuelve la lista de reglas que la contraseña NO cumple."""
    errores = []
    if len(clave) < 8:
        errores.append("mínimo 8 caracteres")
    if not re.search(r"[A-Z]", clave):
        errores.append("una mayúscula")
    if not re.search(r"[a-z]", clave):
        errores.append("una minúscula")
    if not re.search(r"\d", clave):
        errores.append("un número")
    if not re.search(r"[^A-Za-z0-9]", clave):
        errores.append("un carácter especial")
    if username and username.lower() in clave.lower():
        errores.append("no debe contener el nombre de usuario")
    return errores


def errores_usuario(username, correo):
    errores = []
    if not RE_USERNAME.match(username or ""):
        errores.append("El usuario debe tener 4-50 caracteres (letras, números, . _ -).")
    if not RE_CORREO.match(correo or ""):
        errores.append("El correo no es válido.")
    return errores


# ---------------- Sesión y permisos ----------------
def cargar_usuario_actual():
    """Se ejecuta antes de cada petición: deja el usuario en g.usuario."""
    g.usuario = None
    uid = session.get("id_usuario")
    if uid is None:
        return
    try:
        u = db.consultar_uno(
            "SELECT u.id_usuario, u.username, u.correo, u.activo, r.nombre AS rol "
            "FROM usuario u JOIN rol r ON r.id_rol = u.id_rol WHERE u.id_usuario = :id",
            {"id": uid})
    except Exception:
        return
    # Si lo desactivaron o lo borraron mientras tenía sesión, se cierra
    if not u or not u["activo"]:
        session.clear()
        return
    u["permisos"] = current_app.config["PERMISOS"].get(u["rol"], set())
    g.usuario = u


def tiene_permiso(permiso):
    return bool(g.get("usuario")) and permiso in g.usuario["permisos"]


def login_requerido(f):
    @wraps(f)
    def envoltura(*args, **kwargs):
        if not g.get("usuario"):
            flash("Inicia sesión para continuar.", "warning")
            return redirect(url_for("auth.login", next=request.full_path))
        return f(*args, **kwargs)
    return envoltura


def permiso_requerido(permiso):
    def decorador(f):
        @wraps(f)
        @login_requerido
        def envoltura(*args, **kwargs):
            if not tiene_permiso(permiso):
                abort(403)
            return f(*args, **kwargs)
        return envoltura
    return decorador


def url_segura(destino):
    """Evita redirecciones abiertas: solo rutas internas."""
    return bool(destino) and destino.startswith("/") and not destino.startswith("//")


# ---------------- CSRF ----------------
def token_csrf():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def validar_csrf():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        enviado = request.form.get("_csrf") or request.headers.get("X-CSRF-Token", "")
        esperado = session.get("_csrf", "")
        if not esperado or not secrets.compare_digest(enviado, esperado):
            abort(400, description="Token CSRF inválido. Recarga la página e inténtalo de nuevo.")


def cabeceras_seguridad(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if g.get("usuario"):
        resp.headers["Cache-Control"] = "no-store"  # no cachear páginas con datos
    return resp
