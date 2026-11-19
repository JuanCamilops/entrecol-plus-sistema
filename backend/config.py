"""
Configuración central. Todo se puede sobrescribir con variables de entorno
o con un archivo .env en la carpeta del proyecto (ver .env.example).
"""
import os
import secrets
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

try:  # .env opcional
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass


def _bool(nombre, defecto=False):
    return os.getenv(nombre, str(defecto)).strip().lower() in ("1", "true", "si", "sí", "yes")


class Config:
    # --- Base de datos (por defecto: XAMPP, root sin contraseña) ---
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_NAME = os.getenv("DB_NAME", "proyecto_bd")
    DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))

    # --- Flask / sesión ---
    # En producción define SECRET_KEY fija; si no, se genera una por arranque
    SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=int(os.getenv("SESION_MINUTOS", "30")))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)  # True si usas HTTPS

    # --- Seguridad de login ---
    MAX_INTENTOS_FALLIDOS = int(os.getenv("MAX_INTENTOS_FALLIDOS", "3"))
    HASH_METODO = "pbkdf2:sha256:600000"  # werkzeug; funciona igual en Windows/Linux

    # Captcha: "local" (imagen generada con Pillow, funciona sin internet)
    #          "recaptcha" (Google reCAPTCHA v2, requiere claves e internet)
    CAPTCHA_MODO = os.getenv("CAPTCHA_MODO", "local")
    CAPTCHA_LONGITUD = 5
    CAPTCHA_VIGENCIA_SEG = 300
    RECAPTCHA_SITE_KEY = os.getenv("RECAPTCHA_SITE_KEY", "")
    RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY", "")

    # --- Cargas de archivos ---
    UPLOAD_FOLDER = BASE_DIR / "uploads"
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_MB_ARCHIVO", "20")) * 1024 * 1024
    EXTENSIONES_PERMITIDAS = {"csv", "xlsx"}

    # --- Permisos por rol ---
    PERMISOS = {
        "ADMIN": {"leer", "escribir", "cargar", "admin"},
        "OPERADOR": {"leer", "escribir", "cargar"},
        "CONSULTA": {"leer"},
    }
    ROL_REGISTRO = "CONSULTA"  # rol de quien se registra por su cuenta
