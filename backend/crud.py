"""
CRUD genérico (Crear, Leer, Actualizar, Eliminar) + consultas dinámicas
para todas las entidades definidas en entidades.py.

Listado:  búsqueda libre, filtros por llave foránea / N:M, rangos numéricos y de fechas,
          ordenamiento por cualquier columna, paginación y exportación a CSV.
Escritura: validación por tipo de dato, reglas de negocio, transacciones y auditoría.
"""
import csv
import io
import math
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, Response, abort, flash, jsonify, redirect, render_template,
                   request, url_for)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

import auditoria
import db
from entidades import ENTIDADES, MODULOS
from seguridad import RE_CORREO, login_requerido, tiene_permiso

bp = Blueprint("crud", __name__, url_prefix="/datos")

LIMITE_SELECT = 300      # más opciones que esto -> campo con autocompletar
LIMITE_EXPORTAR = 100000
TAMANOS_PAGINA = (10, 25, 50, 100)


# ======================= utilidades =======================
def _entidad(clave, permiso="leer"):
    e = ENTIDADES.get(clave)
    if not e:
        abort(404)
    if not tiene_permiso(e.permiso_leer if permiso == "leer" else e.permiso_escribir):
        abort(403)
    return e


def expr_display(ref, alias):
    disp = ref[2]
    return disp.format(a=alias) if "{a}" in disp else f"{alias}.`{disp}`"


def mensaje_integridad(ex):
    num = getattr(getattr(ex, "orig", None), "errno", None)
    return {
        1062: "Ya existe un registro con ese valor (llave primaria o campo único repetido).",
        1451: "No se puede eliminar o modificar: hay otros registros que dependen de este.",
        1452: "Uno de los valores relacionados (llave foránea) no existe.",
        1048: "Falta un valor obligatorio.",
        3819: "Un valor no cumple las reglas de la tabla (restricción CHECK).",
        4025: "Un valor no cumple las reglas de la tabla (restricción CHECK).",
        1406: "Un texto es demasiado largo para el campo.",
        1264: "Un número está fuera del rango permitido.",
    }.get(num, "La base de datos rechazó la operación por una regla de integridad.")


def _decimal(crudo):
    s = crudo.replace(" ", "").replace("$", "")
    if "," in s and "." in s:      # 1.200.000,50 -> 1200000.50 | 1,200,000.50 -> 1200000.50
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif s.count(".") > 1:         # 2.500.000 -> 2500000 (puntos de miles)
        s = s.replace(".", "")
    elif s.count(",") > 1:         # 2,500,000 -> 2500000
        s = s.replace(",", "")
    elif "," in s:                 # 1200,5 -> 1200.5
        s = s.replace(",", ".")
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError("debe ser un número")
    if not d.is_finite():
        raise ValueError("debe ser un número")
    return d


def convertir(c, crudo):
    """Convierte y valida el texto recibido según el tipo del campo."""
    if c.tipo in ("text", "email"):
        if c.max_len and len(crudo) > c.max_len:
            raise ValueError(f"máximo {c.max_len} caracteres")
        if c.tipo == "email" and not RE_CORREO.match(crudo):
            raise ValueError("correo no válido")
        return crudo
    if c.tipo == "int":
        try:
            v = int(crudo)
        except ValueError:
            raise ValueError("debe ser un número entero")
    elif c.tipo == "decimal":
        v = _decimal(crudo)
    elif c.tipo == "date":
        try:
            v = date.fromisoformat(crudo)
        except ValueError:
            raise ValueError("fecha no válida (AAAA-MM-DD)")
    elif c.tipo == "fk":
        return resolver_fk(c, crudo)
    else:
        return crudo
    if c.minimo is not None and v < c.minimo:
        raise ValueError(f"debe ser mayor o igual a {c.minimo:g}")
    if c.maximo is not None and v > c.maximo:
        raise ValueError(f"debe ser menor o igual a {c.maximo:g}")
    return v


def resolver_fk(c, crudo):
    """Acepta el id, 'id | texto' (autocompletar) o el texto exacto a mostrar."""
    tabla, pk, _, tipo = c.ref
    cand = crudo.split(" | ", 1)[0].strip()
    val = cand
    if tipo == "int":
        val = int(cand) if cand.lstrip("-").isdigit() else None
    if val is not None and db.escalar(f"SELECT 1 FROM `{tabla}` WHERE `{pk}` = :v", {"v": val}):
        return val
    filas = db.consultar(f"SELECT a.`{pk}` AS id FROM `{tabla}` a WHERE {expr_display(c.ref, 'a')} = :t LIMIT 2",
                         {"t": crudo.strip()})
    if len(filas) == 1:
        return filas[0]["id"]
    raise ValueError("la opción indicada no existe" if not filas else "hay varias coincidencias, usa el ID")


def opciones_fk(c):
    tabla, pk, _, _ = c.ref
    if db.escalar(f"SELECT COUNT(*) FROM `{tabla}`") > LIMITE_SELECT:
        return None
    return db.consultar(f"SELECT a.`{pk}` AS id, {expr_display(c.ref, 'a')} AS txt "
                        f"FROM `{tabla}` a ORDER BY txt")


def opciones_m2m(c):
    _, _, _, tref, pkref, disp, _ = c.m2m
    return db.consultar(f"SELECT `{pkref}` AS id, `{disp}` AS txt FROM `{tref}` ORDER BY txt")


def pk_desde(e, fuente):
    """Lee los valores de la llave primaria (simple o compuesta) desde args/form."""
    pk = {}
    for nombre in e.pk:
        c = e.campo(nombre)
        crudo = (fuente.get(nombre) or "").strip()
        if not crudo:
            abort(400, description=f"Falta la llave {nombre}")
        tipo = c.ref[3] if c.tipo == "fk" else c.tipo
        try:
            pk[nombre] = int(crudo) if tipo == "int" else crudo
        except ValueError:
            abort(400, description=f"Llave {nombre} inválida")
    return pk


def _where_pk(e, prefijo="t."):
    return " AND ".join(f"{prefijo}`{k}` = :pk_{k}" for k in e.pk)


def _params_pk(pk):
    return {f"pk_{k}": v for k, v in pk.items()}


# ======================= consulta dinámica (listado) =======================
def armar_consulta(e, args):
    """Arma SELECT/FROM/WHERE/ORDER a partir de los filtros. Devuelve (sql_base, select, params, orden)."""
    select = [f"t.`{c.nombre}`" for c in e.columnas]
    joins, fk_expr = [], {}
    for i, c in enumerate(e.columnas):
        if c.tipo == "fk":
            a = f"r{i}"
            joins.append(f"LEFT JOIN `{c.ref[0]}` {a} ON {a}.`{c.ref[1]}` = t.`{c.nombre}`")
            fk_expr[c.nombre] = expr_display(c.ref, a)
            select.append(f"{fk_expr[c.nombre]} AS `{c.nombre}__txt`")
    for c in e.campos:
        if c.tipo == "m2m":
            puente, propia, colref, tref, pkref, disp, _ = c.m2m
            select.append(
                f"(SELECT GROUP_CONCAT(x.`{disp}` ORDER BY x.`{disp}` SEPARATOR ' / ') "
                f"FROM `{puente}` p JOIN `{tref}` x ON x.`{pkref}` = p.`{colref}` "
                f"WHERE p.`{propia}` = t.`{e.pk[0]}`) AS `{c.nombre}`")

    where, params = [], {}
    q = (args.get("q") or "").strip()
    if q:
        partes = [f"t.`{b}` LIKE :q" for b in e.busqueda] + [f"{x} LIKE :q" for x in fk_expr.values()]
        for c in e.campos:
            if c.tipo == "m2m":
                puente, propia, colref, tref, pkref, disp, _ = c.m2m
                partes.append(f"EXISTS (SELECT 1 FROM `{puente}` p JOIN `{tref}` x ON x.`{pkref}` = p.`{colref}` "
                              f"WHERE p.`{propia}` = t.`{e.pk[0]}` AND x.`{disp}` LIKE :q)")
        if partes:
            where.append("(" + " OR ".join(partes) + ")")
            params["q"] = f"%{q}%"

    for c in e.campos:
        v = (args.get(f"f_{c.nombre}") or "").strip()
        if v and c.tipo == "fk":
            where.append(f"t.`{c.nombre}` = :f_{c.nombre}")
            params[f"f_{c.nombre}"] = int(v) if c.ref[3] == "int" and v.isdigit() else v
        elif v and c.tipo == "m2m" and v.isdigit():
            puente, propia, colref, *_ = c.m2m
            where.append(f"EXISTS (SELECT 1 FROM `{puente}` p WHERE p.`{propia}` = t.`{e.pk[0]}` "
                         f"AND p.`{colref}` = :f_{c.nombre})")
            params[f"f_{c.nombre}"] = int(v)
        if c.tipo in ("int", "decimal", "date"):
            for sufijo, op in (("min", ">="), ("max", "<=")):
                crudo = (args.get(f"{c.nombre}_{sufijo}") or "").strip()
                if not crudo:
                    continue
                try:
                    if c.tipo == "int":
                        val = int(crudo)
                    elif c.tipo == "decimal":
                        val = _decimal(crudo)
                    else:
                        val = date.fromisoformat(crudo)
                except ValueError:
                    continue
                where.append(f"t.`{c.nombre}` {op} :{c.nombre}_{sufijo}")
                params[f"{c.nombre}_{sufijo}"] = val

    ordenables = {c.nombre: f"t.`{c.nombre}`" for c in e.columnas}
    ordenables.update({k: f"`{k}__txt`" for k in fk_expr})
    orden = args.get("orden") if args.get("orden") in ordenables else (e.orden or e.pk[0])
    direccion = "DESC" if args.get("dir") == "desc" else "ASC"
    base = f"FROM `{e.tabla}` t " + " ".join(joins) + (" WHERE " + " AND ".join(where) if where else "")
    order_by = f" ORDER BY {ordenables[orden]} {direccion}, " + ", ".join(f"t.`{k}`" for k in e.pk)
    return base, ", ".join(select), params, order_by, orden, direccion.lower()


@bp.route("/<clave>/")
@login_requerido
def listar(clave):
    e = _entidad(clave)
    base, select, params, order_by, orden, direccion = armar_consulta(e, request.args)

    if request.args.get("exportar") == "csv":
        filas = db.consultar(f"SELECT {select} {base} {order_by} LIMIT {LIMITE_EXPORTAR}", params)
        auditoria.registrar("EXPORTAR", e.tabla, {"filas": len(filas), "filtros": request.args.to_dict()})
        return _csv(e, filas)

    try:
        por_pagina = int(request.args.get("por_pagina", 25))
    except ValueError:
        por_pagina = 25
    por_pagina = por_pagina if por_pagina in TAMANOS_PAGINA else 25
    total = db.escalar(f"SELECT COUNT(*) {base}", params)
    paginas = max(1, math.ceil(total / por_pagina))
    try:
        pagina = min(max(1, int(request.args.get("pagina", 1))), paginas)
    except ValueError:
        pagina = 1
    filas = db.consultar(f"SELECT {select} {base} {order_by} LIMIT :lim OFFSET :off",
                         {**params, "lim": por_pagina, "off": (pagina - 1) * por_pagina})

    filtros_fk = {c.nombre: opciones_fk(c) for c in e.campos if c.tipo == "fk"}
    filtros_m2m = {c.nombre: opciones_m2m(c) for c in e.campos if c.tipo == "m2m" and c.m2m[6] == "checks"}
    return render_template("crud/lista.html", e=e, filas=filas, total=total, pagina=pagina,
                           paginas=paginas, por_pagina=por_pagina, tamanos=TAMANOS_PAGINA,
                           orden=orden, direccion=direccion, filtros_fk=filtros_fk,
                           filtros_m2m=filtros_m2m, args=request.args,
                           puede_escribir=tiene_permiso(e.permiso_escribir))


def _csv(e, filas):
    buf = io.StringIO()
    w = csv.writer(buf)
    visibles = [c for c in e.campos]
    w.writerow([c.etiqueta for c in visibles])
    for f in filas:
        w.writerow([f.get(f"{c.nombre}__txt", f.get(c.nombre)) if c.tipo == "fk" else f.get(c.nombre)
                    for c in visibles])
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={e.tabla}.csv"})


@bp.route("/api/opciones/<clave>/<campo>")
@login_requerido
def api_opciones(clave, campo):
    """Autocompletar para llaves foráneas con muchas opciones (p. ej. empleados, editoriales)."""
    e = _entidad(clave)
    c = e.campo(campo)
    if not c or c.tipo not in ("fk", "m2m"):
        abort(404)
    if c.tipo == "fk":
        tabla, pk = c.ref[0], c.ref[1]
        expr = expr_display(c.ref, "a")
    else:
        tabla, pk, disp = c.m2m[3], c.m2m[4], c.m2m[5]
        expr = f"a.`{disp}`"
    q = (request.args.get("q") or "").strip()
    filas = db.consultar(f"SELECT a.`{pk}` AS id, {expr} AS txt FROM `{tabla}` a "
                         f"WHERE {expr} LIKE :q OR CAST(a.`{pk}` AS CHAR) LIKE :q ORDER BY txt LIMIT 20",
                         {"q": f"%{q}%"})
    return jsonify([{"valor": f"{f['id']} | {f['txt']}", "texto": f["txt"]} for f in filas])


# ======================= crear / editar / eliminar =======================
def leer_formulario(e, form, creando):
    valores, m2m, errores = {}, {}, []
    for c in e.campos:
        if c.auto or (not creando and c.nombre in e.pk):
            continue
        if c.tipo == "m2m":
            modo = c.m2m[6]
            if modo == "texto":
                vistos, nombres = set(), []
                for n in (form.get(c.nombre) or "").split("/"):
                    n = " ".join(n.split())
                    if n and n.lower() not in vistos:
                        vistos.add(n.lower())
                        nombres.append(n)
                m2m[c.nombre] = nombres
            else:
                m2m[c.nombre] = sorted({int(x) for x in form.getlist(c.nombre) if x.isdigit()})
            if c.requerido and not m2m[c.nombre]:
                errores.append(f"{c.etiqueta}: selecciona al menos uno.")
            continue
        if c.tipo == "bool":
            valores[c.nombre] = 1 if form.get(c.nombre) else 0
            continue
        crudo = (form.get(c.nombre) or "").strip()
        if not crudo:
            if c.requerido:
                errores.append(f"{c.etiqueta} es obligatorio.")
            valores[c.nombre] = None
            continue
        try:
            valores[c.nombre] = convertir(c, crudo)
        except ValueError as ex:
            errores.append(f"{c.etiqueta}: {ex}.")
    if not errores and e.validar:
        errores.extend(e.validar(valores))
    return valores, m2m, errores


def _ids_m2m(conn, c, entrada):
    """Convierte la entrada N:M en ids. En modo texto crea los nombres que no existan."""
    _, _, _, tref, pkref, disp, modo = c.m2m
    ids = []
    if modo == "texto":
        for nombre in entrada:
            i = conn.execute(text(f"SELECT `{pkref}` FROM `{tref}` WHERE `{disp}` = :n"), {"n": nombre}).scalar()
            if i is None:
                i = conn.execute(text(f"INSERT INTO `{tref}` (`{disp}`) VALUES (:n)"), {"n": nombre}).lastrowid
            ids.append(i)
    else:
        for i in entrada:
            if conn.execute(text(f"SELECT 1 FROM `{tref}` WHERE `{pkref}` = :i"), {"i": i}).first():
                ids.append(i)
    return sorted(set(ids))


def _guardar_m2m(conn, e, id_propio, m2m):
    for nombre, entrada in m2m.items():
        c = e.campo(nombre)
        puente, propia, colref, *_ = c.m2m
        conn.execute(text(f"DELETE FROM `{puente}` WHERE `{propia}` = :p"), {"p": id_propio})
        ids = _ids_m2m(conn, c, entrada)
        if ids:
            if puente == "libro_autor":
                conn.execute(
                    text(f"INSERT INTO `{puente}` (`{propia}`, `{colref}`, `orden_autoria`) VALUES (:p, :r, :o)"),
                    [{"p": id_propio, "r": i, "o": idx} for idx, i in enumerate(ids, start=1)],
                )
            else:
                conn.execute(
                    text(f"INSERT INTO `{puente}` (`{propia}`, `{colref}`) VALUES (:p, :r)"),
                    [{"p": id_propio, "r": i} for i in ids],
                )


def _valores_m2m_actuales(e, id_propio):
    actuales = {}
    for c in e.campos:
        if c.tipo == "m2m":
            puente, propia, colref, tref, pkref, disp, modo = c.m2m
            filas = db.consultar(f"SELECT x.`{pkref}` AS id, x.`{disp}` AS txt FROM `{puente}` p "
                                 f"JOIN `{tref}` x ON x.`{pkref}` = p.`{colref}` WHERE p.`{propia}` = :p "
                                 f"ORDER BY txt", {"p": id_propio})
            actuales[c.nombre] = (" / ".join(f["txt"] for f in filas) if modo == "texto"
                                  else [f["id"] for f in filas])
    return actuales


def _contexto_form(e, registro, creando):
    fk = {c.nombre: opciones_fk(c) for c in e.campos if c.tipo == "fk"}
    m2m = {c.nombre: opciones_m2m(c) for c in e.campos if c.tipo == "m2m" and c.m2m[6] == "checks"}
    # texto a mostrar en campos con autocompletar
    fk_txt = {}
    for c in e.campos:
        if c.tipo == "fk" and fk[c.nombre] is None and registro.get(c.nombre) not in (None, ""):
            v = registro[c.nombre]
            t = db.escalar(f"SELECT {expr_display(c.ref, 'a')} FROM `{c.ref[0]}` a WHERE a.`{c.ref[1]}` = :v",
                           {"v": v})
            fk_txt[c.nombre] = f"{v} | {t}" if t is not None else str(v)
    return dict(e=e, registro=registro, creando=creando, opciones_fk=fk, opciones_m2m=m2m, fk_txt=fk_txt)


@bp.route("/<clave>/nuevo", methods=["GET", "POST"])
@login_requerido
def crear(clave):
    e = _entidad(clave, "escribir")
    registro = {}
    if request.method == "POST":
        valores, m2m, errores = leer_formulario(e, request.form, creando=True)
        registro = {**request.form.to_dict(), **valores}
        for c in e.campos:
            if c.tipo == "m2m":
                registro[c.nombre] = (" / ".join(m2m.get(c.nombre, [])) if c.m2m[6] == "texto"
                                      else m2m.get(c.nombre, []))
        if not errores:
            cols = list(valores)
            try:
                with db.transaccion() as conn:
                    res = conn.execute(text(
                        f"INSERT INTO `{e.tabla}` ({', '.join(f'`{k}`' for k in cols)}) "
                        f"VALUES ({', '.join(f':{k}' for k in cols)})"), valores)
                    pk = {e.pk[0]: res.lastrowid} if e.pk_auto else {k: valores[k] for k in e.pk}
                    if m2m:
                        _guardar_m2m(conn, e, pk[e.pk[0]], m2m)
                    auditoria.registrar("INSERT", e.tabla, {"pk": pk, "valores": {**valores, **m2m}}, conn=conn)
                flash(f"{e.singular} creado correctamente.", "success")
                return redirect(url_for("crud.listar", clave=clave))
            except IntegrityError as ex:
                errores.append(mensaje_integridad(ex))
            except DBAPIError as ex:
                errores.append(mensaje_integridad(ex))
        for m in errores:
            flash(m, "danger")
    return render_template("crud/form.html", **_contexto_form(e, registro, True))


@bp.route("/<clave>/editar", methods=["GET", "POST"])
@login_requerido
def editar(clave):
    e = _entidad(clave, "escribir")
    pk = pk_desde(e, request.values)
    actual = db.consultar_uno(f"SELECT * FROM `{e.tabla}` t WHERE {_where_pk(e)}", _params_pk(pk))
    if not actual:
        abort(404)
    m2m_antes = _valores_m2m_actuales(e, pk[e.pk[0]])
    registro = {**actual, **m2m_antes}

    if request.method == "POST":
        valores, m2m, errores = leer_formulario(e, request.form, creando=False)
        registro = {**actual, **request.form.to_dict(), **valores}
        for c in e.campos:
            if c.tipo == "m2m":
                registro[c.nombre] = (" / ".join(m2m.get(c.nombre, [])) if c.m2m[6] == "texto"
                                      else m2m.get(c.nombre, []))
        if not errores:
            cambios = {k: [actual.get(k), v] for k, v in valores.items() if actual.get(k) != v}
            for k, v in m2m.items():
                antes = m2m_antes.get(k)
                nuevo = " / ".join(v) if e.campo(k).m2m[6] == "texto" else v
                if antes != nuevo:
                    cambios[k] = [antes, nuevo]
            try:
                with db.transaccion() as conn:
                    if valores:
                        conn.execute(text(
                            f"UPDATE `{e.tabla}` t SET {', '.join(f't.`{k}` = :{k}' for k in valores)} "
                            f"WHERE {_where_pk(e)}"), {**valores, **_params_pk(pk)})
                    if m2m:
                        _guardar_m2m(conn, e, pk[e.pk[0]], m2m)
                    if cambios:
                        auditoria.registrar("UPDATE", e.tabla, {"pk": pk, "cambios": cambios}, conn=conn)
                flash(f"{e.singular} actualizado." if cambios else "No hubo cambios.", "success")
                return redirect(url_for("crud.listar", clave=clave))
            except (IntegrityError, DBAPIError) as ex:
                errores.append(mensaje_integridad(ex))
        for m in errores:
            flash(m, "danger")
    ctx = _contexto_form(e, registro, False)
    ctx["pk"] = pk
    return render_template("crud/form.html", **ctx)


@bp.route("/<clave>/eliminar", methods=["POST"])
@login_requerido
def eliminar(clave):
    e = _entidad(clave, "escribir")
    pk = pk_desde(e, request.form)
    try:
        with db.transaccion() as conn:
            anterior = conn.execute(text(f"SELECT * FROM `{e.tabla}` t WHERE {_where_pk(e)} FOR UPDATE"),
                                    _params_pk(pk)).mappings().first()
            if not anterior:
                abort(404)
            conn.execute(text(f"DELETE t FROM `{e.tabla}` t WHERE {_where_pk(e)}"), _params_pk(pk))
            auditoria.registrar("DELETE", e.tabla, {"pk": pk, "registro": dict(anterior)}, conn=conn)
        flash(f"{e.singular} eliminado.", "success")
    except IntegrityError as ex:
        flash(mensaje_integridad(ex), "danger")
    return redirect(request.form.get("volver") if (request.form.get("volver") or "").startswith("/datos/")
                    else url_for("crud.listar", clave=clave))


def menu_entidades():
    """Entidades visibles para el usuario, agrupadas por módulo (para el menú)."""
    menu = {}
    for m in MODULOS:
        items = [e for e in ENTIDADES.values() if e.modulo == m and tiene_permiso(e.permiso_leer)]
        if items:
            menu[m] = items
    return menu
