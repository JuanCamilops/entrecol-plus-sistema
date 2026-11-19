"""
Registro de auditoría (tabla AUDITORIA del MER de Seguridad).
Cada acción relevante queda con: usuario, acción, tabla afectada, fecha/hora, IP y detalle.
"""
import json
from datetime import date, datetime
from decimal import Decimal

from flask import current_app, g, has_request_context, request
from sqlalchemy import text

import db


def _json_default(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return str(v)


def ip_cliente():
    if not has_request_context():
        return None
    # Si hay proxy inverso, X-Forwarded-For trae la IP real (solo si confías en el proxy)
    return (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote_addr)


def registrar(accion, tabla=None, detalle=None, id_usuario=None, conn=None, ip=None):
    """
    Inserta un registro de auditoría. Si se pasa `conn`, se hace dentro de la misma
    transacción de la operación (si la operación falla, la auditoría también se revierte).
    """
    if id_usuario is None and has_request_context() and g.get("usuario"):
        id_usuario = g.usuario["id_usuario"]
    if detalle is not None and not isinstance(detalle, str):
        detalle = json.dumps(detalle, ensure_ascii=False, default=_json_default)
    params = {"u": id_usuario, "a": accion, "t": tabla, "ip": ip or ip_cliente(),
              "d": (detalle or "")[:60000]}
    sql = text("INSERT INTO auditoria (id_usuario, accion, tabla_afectada, ip, detalle) "
               "VALUES (:u, :a, :t, :ip, :d)")
    try:
        if conn is not None:
            conn.execute(sql, params)
        else:
            with db.transaccion() as c:
                c.execute(sql, params)
    except Exception:
        if conn is not None:
            raise
        # Un fallo de auditoría fuera de transacción no debe tumbar la petición
        try:
            current_app.logger.exception("No se pudo registrar auditoría")
        except RuntimeError:
            pass
