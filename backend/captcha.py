"""
Captcha (segundo factor de verificación en login y registro).

Modo "local" (por defecto): genera una imagen con texto distorsionado usando Pillow.
  La respuesta se guarda en el SERVIDOR (no en la cookie), es de un solo uso
  y vence a los 5 minutos, así no se puede leer ni reutilizar.
Modo "recaptcha": valida el token de Google reCAPTCHA v2 contra la API de Google.
"""
import io
import json
import random
import secrets
import string
import threading
import time
import urllib.parse
import urllib.request

from flask import current_app, request, session
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ALFABETO = "".join(c for c in string.ascii_uppercase + string.digits if c not in "O0I1LQ5S")

_almacen = {}  # token -> (respuesta, vence)
_lock = threading.Lock()


def _limpiar_vencidos():
    ahora = time.time()
    for k in [k for k, (_, v) in _almacen.items() if v < ahora]:
        _almacen.pop(k, None)


def _fuente(tam):
    for nombre in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(nombre, tam)
        except OSError:
            continue
    return ImageFont.load_default()


def generar_imagen():
    """Crea un captcha nuevo, lo asocia a la sesión y devuelve los bytes PNG."""
    cfg = current_app.config
    texto = "".join(random.choice(ALFABETO) for _ in range(cfg["CAPTCHA_LONGITUD"]))
    token = secrets.token_urlsafe(16)
    with _lock:
        _limpiar_vencidos()
        _almacen[token] = (texto, time.time() + cfg["CAPTCHA_VIGENCIA_SEG"])
    session["captcha_token"] = token

    ancho, alto = 200, 70
    img = Image.new("RGB", (ancho, alto), (245, 247, 250))
    dib = ImageDraw.Draw(img)
    for _ in range(6):  # líneas de ruido
        dib.line([(random.randint(0, ancho), random.randint(0, alto)) for _ in range(2)],
                 fill=tuple(random.randint(120, 200) for _ in range(3)), width=2)
    x = 12
    for ch in texto:  # cada letra rotada y desplazada
        capa = Image.new("RGBA", (44, 56), (0, 0, 0, 0))
        ImageDraw.Draw(capa).text((6, 4), ch, font=_fuente(38),
                                  fill=tuple(random.randint(20, 110) for _ in range(3)))
        capa = capa.rotate(random.uniform(-30, 30), resample=Image.BICUBIC, expand=False)
        img.paste(capa, (x, random.randint(0, 14)), capa)
        x += random.randint(32, 37)
    for _ in range(350):  # puntos de ruido
        dib.point((random.randint(0, ancho - 1), random.randint(0, alto - 1)),
                  fill=tuple(random.randint(80, 200) for _ in range(3)))
    img = img.filter(ImageFilter.SMOOTH)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _validar_local(respuesta):
    token = session.pop("captcha_token", None)  # un solo uso
    if not token:
        return False
    with _lock:
        guardado = _almacen.pop(token, None)
    if not guardado or guardado[1] < time.time():
        return False
    return secrets.compare_digest(guardado[0], (respuesta or "").strip().upper())


def _validar_recaptcha(token):
    if not token:
        return False
    datos = urllib.parse.urlencode({
        "secret": current_app.config["RECAPTCHA_SECRET_KEY"],
        "response": token,
        "remoteip": request.remote_addr or "",
    }).encode()
    try:
        with urllib.request.urlopen("https://www.google.com/recaptcha/api/siteverify",
                                    data=datos, timeout=5) as r:
            return bool(json.load(r).get("success"))
    except Exception:
        current_app.logger.exception("No se pudo validar reCAPTCHA")
        return False


def modo():
    cfg = current_app.config
    if cfg["CAPTCHA_MODO"] == "recaptcha" and cfg["RECAPTCHA_SITE_KEY"] and cfg["RECAPTCHA_SECRET_KEY"]:
        return "recaptcha"
    return "local"


def validar(form):
    if modo() == "recaptcha":
        return _validar_recaptcha(form.get("g-recaptcha-response"))
    return _validar_local(form.get("captcha"))
