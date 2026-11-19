"""
Conexión robusta a MySQL/MariaDB con SQLAlchemy (pool de conexiones).

- pool_pre_ping: detecta conexiones caídas (p. ej. si reinicias XAMPP) y reconecta.
- pool_recycle: renueva conexiones antes del wait_timeout de MySQL.
- Todas las consultas usan parámetros (:nombre), nunca concatenación de strings,
  para evitar inyección SQL.
"""
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

_engine = None


def crear_url(cfg, con_base=True):
    return URL.create(
        "mysql+mysqlconnector",
        username=cfg.DB_USER,
        password=cfg.DB_PASSWORD or None,
        host=cfg.DB_HOST,
        port=cfg.DB_PORT,
        database=cfg.DB_NAME if con_base else None,
        query={"charset": "utf8mb4", "collation": "utf8mb4_unicode_ci"},
    )


def init_engine(cfg):
    global _engine
    _engine = create_engine(
        crear_url(cfg),
        pool_size=cfg.DB_POOL_SIZE,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_timeout=10,
        connect_args={"connection_timeout": 5},
        future=True,
    )
    return _engine


def get_engine():
    if _engine is None:
        raise RuntimeError("El motor de BD no está inicializado (llama init_engine).")
    return _engine


def consultar(sql, params=None):
    """SELECT -> lista de dicts."""
    with get_engine().connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), params or {}).mappings()]


def consultar_uno(sql, params=None):
    filas = consultar(sql, params)
    return filas[0] if filas else None


def escalar(sql, params=None):
    with get_engine().connect() as conn:
        return conn.execute(text(sql), params or {}).scalar()


@contextmanager
def transaccion():
    """Bloque transaccional: COMMIT si todo sale bien, ROLLBACK si hay excepción."""
    with get_engine().begin() as conn:
        yield conn


def ejecutar(sql, params=None):
    with transaccion() as conn:
        res = conn.execute(text(sql), params or {})
        return res


def bd_disponible():
    try:
        escalar("SELECT 1")
        return True
    except Exception:
        return False
