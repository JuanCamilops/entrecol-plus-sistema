"""
Crea la base de datos, las tablas de los 4 módulos y el usuario administrador.

Uso:
    python init_db.py                       # crea todo (no borra datos existentes)
    python init_db.py --reset               # BORRA las tablas y las vuelve a crear
    python init_db.py --admin admin --clave "Admin123*" --correo admin@proyecto.com
"""
import argparse
import re
import sys

from sqlalchemy import create_engine, text
from werkzeug.security import generate_password_hash

from config import BASE_DIR, Config
from db import crear_url, init_engine

TABLAS_EN_ORDEN_DE_BORRADO = [
    "pelicula_genero", "genero_pelicula", "pelicula",
    "libro_autor", "libro", "autor", "editorial", "idioma",
    "novedad_nomina", "detalle_nomina", "periodo_nomina", "empleado",
    "departamento", "cargo", "eps", "fondo_pension", "arl",
    "carga_archivo", "auditoria", "usuario", "rol",
]


def sentencias_sql(ruta):
    """Separa el script SQL por ';' eliminando comentarios de línea."""
    script = ruta.read_text(encoding="utf-8")
    script = re.sub(r"^\s*--.*$", "", script, flags=re.MULTILINE)
    return [s.strip() for s in script.split(";") if s.strip()]


def main():
    p = argparse.ArgumentParser(description="Inicializa la base de datos del proyecto")
    p.add_argument("--reset", action="store_true", help="borra y recrea las tablas")
    p.add_argument("--admin", default="admin")
    p.add_argument("--clave", default="Admin123*")
    p.add_argument("--correo", default="admin@proyecto.com")
    a = p.parse_args()

    cfg = Config
    servidor = create_engine(crear_url(cfg, con_base=False))
    try:
        with servidor.begin() as conn:
            conn.execute(text(
                f"CREATE DATABASE IF NOT EXISTS `{cfg.DB_NAME}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"))
    except Exception as e:
        sys.exit(f"❌ No se pudo conectar a MySQL en {cfg.DB_HOST}:{cfg.DB_PORT}.\n   Detalle: {e}")
    servidor.dispose()

    engine = init_engine(cfg)
    with engine.begin() as conn:
        if a.reset:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for t in TABLAS_EN_ORDEN_DE_BORRADO:
                conn.execute(text(f"DROP TABLE IF EXISTS `{t}`"))
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
            print("🗑️  Tablas eliminadas.")
        for s in sentencias_sql(BASE_DIR / "sql" / "schema.sql"):
            conn.execute(text(s))
    print(f"✅ Esquema verificado en la base `{cfg.DB_NAME}`.")

    with engine.begin() as conn:
        existe = conn.execute(text("SELECT 1 FROM usuario WHERE username = :u"),
                              {"u": a.admin}).first()
        if existe:
            print(f"ℹ️  El usuario '{a.admin}' ya existe (no se modificó).")
        else:
            id_rol = conn.execute(text("SELECT id_rol FROM rol WHERE nombre = 'ADMIN'")).scalar()
            conn.execute(text(
                "INSERT INTO usuario (username, password_hash, correo, id_rol) "
                "VALUES (:u, :h, :c, :r)"),
                {"u": a.admin, "h": generate_password_hash(a.clave, method=cfg.HASH_METODO),
                 "c": a.correo, "r": id_rol})
            print(f"✅ Administrador creado → usuario: {a.admin} | contraseña: {a.clave}")


if __name__ == "__main__":
    main()