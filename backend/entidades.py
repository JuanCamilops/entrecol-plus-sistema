"""
Metadatos de las entidades de los MER. El CRUD genérico (crud.py) lee esta
configuración para construir listados, filtros, formularios y validaciones.
"""
import calendar
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional


@dataclass
class Campo:
    nombre: str
    etiqueta: str
    tipo: str = "text"          # text | email | int | decimal | date | bool | fk | m2m
    requerido: bool = True
    max_len: Optional[int] = None
    minimo: Optional[float] = None
    maximo: Optional[float] = None
    auto: bool = False
    en_lista: bool = True
    ayuda: str = ""
    ref: Optional[tuple] = None
    m2m: Optional[tuple] = None


@dataclass
class Entidad:
    clave: str
    tabla: str
    titulo: str
    singular: str
    modulo: str
    pk: list
    campos: list
    busqueda: list = field(default_factory=list)
    orden: str = ""
    validar: Optional[Callable] = None
    permiso_leer: str = "leer"
    permiso_escribir: str = "escribir"

    def campo(self, nombre):
        return next((c for c in self.campos if c.nombre == nombre), None)

    @property
    def columnas(self):
        return [c for c in self.campos if c.tipo != "m2m"]

    @property
    def pk_auto(self):
        return len(self.pk) == 1 and self.campo(self.pk[0]).auto


# ---------------- Validaciones específicas ----------------
def _validar_novedad(v):
    errores = []
    tipo = (v.get("tipo_novedad") or "").strip().upper()
    if tipo not in ("INCAPACIDAD", "VACACIONES"):
        errores.append("Tipo de novedad debe ser INCAPACIDAD o VACACIONES.")
    else:
        v["tipo_novedad"] = tipo
    ini, fin = v.get("fecha_inicio"), v.get("fecha_fin")
    if ini and fin and fin < ini:
        errores.append("La fecha fin no puede ser anterior a la fecha inicio.")
    return errores


def _validar_periodo(v):
    anio, mes = v.get("anio"), v.get("mes")
    if anio and mes and 1 <= mes <= 12:
        if not v.get("fecha_inicio"):
            v["fecha_inicio"] = date(anio, mes, 1)
        if not v.get("fecha_fin"):
            v["fecha_fin"] = date(anio, mes, calendar.monthrange(anio, mes)[1])
    if v.get("fecha_inicio") and v.get("fecha_fin") and v["fecha_fin"] < v["fecha_inicio"]:
        return ["La fecha fin no puede ser anterior a la fecha inicio."]
    return []


def _validar_empleado(v):
    if v.get("fecha_ingreso") and v["fecha_ingreso"] > date.today():
        return ["La fecha de ingreso no puede ser futura."]
    return []


def _validar_libro(v):
    errores = []
    for col, largos in (("isbn", (10,)), ("isbn13", (13,))):
        val = v.get(col)
        if val:
            val = val.replace("-", "").upper()
            v[col] = val
            if len(val) not in largos or not (val[:-1].isdigit() and (val[-1].isdigit() or
                                                                      (col == "isbn" and val[-1] == "X"))):
                errores.append(f"{col.upper()} debe tener {largos[0]} dígitos.")
    return errores


def _cat(clave, tabla, titulo, singular, modulo, pk, col="nombre", etiqueta="Nombre", largo=100, permiso_leer="leer"):
    """Atajo para catálogos simples (id + nombre)."""
    return Entidad(clave, tabla, titulo, singular, modulo, [pk],
                   [Campo(pk, "ID", "int", auto=True),
                    Campo(col, etiqueta, max_len=largo)],
                   busqueda=[col], orden=col, permiso_leer=permiso_leer)


MODULOS = ["Nómina", "Libros", "Películas", "Seguridad"]

_lista = [
# ---------------- NÓMINA ----------------
    Entidad("empleado", "empleado", "Empleados", "Empleado", "Nómina", ["empleado_id"], [
        Campo("empleado_id", "Código", max_len=20),
        Campo("nombre_completo", "Nombre completo", max_len=150),
        Campo("fecha_ingreso", "Fecha de ingreso", "date"),
        Campo("sueldo_base", "Sueldo base", "decimal", minimo=0),
        Campo("departamento_id", "Departamento", "fk", ref=("departamento", "departamento_id", "nombre", "int")),
        Campo("cargo_id", "Cargo", "fk", ref=("cargo", "cargo_id", "nombre", "int")),
        Campo("eps_id", "EPS", "fk", ref=("eps", "eps_id", "nombre", "int")),
        Campo("fondo_pension_id", "Fondo de pensión", "fk", ref=("fondo_pension", "fondo_pension_id", "nombre", "int")),
        Campo("arl_id", "ARL", "fk", ref=("arl", "arl_id", "nombre", "int")),
    ], busqueda=["empleado_id", "nombre_completo"], orden="nombre_completo",
       validar=_validar_empleado, permiso_leer="escribir"),

    Entidad("detalle_nomina", "detalle_nomina", "Liquidaciones", "Liquidación", "Nómina", ["detalle_nomina_id"], [
        Campo("detalle_nomina_id", "ID", "int", auto=True),
        Campo("periodo_id", "Periodo", "fk",
              ref=("periodo_nomina", "periodo_id", "CONCAT({a}.anio, '-', LPAD({a}.mes, 2, '0'))", "int")),
        Campo("empleado_id", "Empleado", "fk", ref=("empleado", "empleado_id", "nombre_completo", "str")),
        Campo("dias_trabajados", "Días trabajados", "int", minimo=0, maximo=30),
        Campo("dias_incapacidad", "Días incapacidad", "decimal", minimo=0),
        Campo("dias_vacaciones", "Días vacaciones", "decimal", minimo=0),
        Campo("bonificacion", "Bonificación", "decimal", minimo=0),
        Campo("auxilio_transporte", "Auxilio de transporte", "decimal", minimo=0),
    ], busqueda=["empleado_id"], orden="periodo_id", permiso_leer="escribir"),

    Entidad("novedad_nomina", "novedad_nomina", "Novedades (Incap. / Vac.)", "Novedad", "Nómina", ["novedad_id"], [
        Campo("novedad_id", "ID", "int", auto=True),
        Campo("detalle_nomina_id", "Liquidación (Empleado - Periodo)", "fk",
              ref=("detalle_nomina", "detalle_nomina_id",
                   "CONCAT({a}.empleado_id, ' | Periodo #', {a}.periodo_id)", "int")),
        Campo("tipo_novedad", "Tipo novedad", max_len=20, ayuda="INCAPACIDAD o VACACIONES"),
        Campo("fecha_inicio", "Fecha inicio", "date"),
        Campo("fecha_fin", "Fecha fin", "date"),
        Campo("observacion", "Observación", requerido=False, max_len=255),
    ], busqueda=["tipo_novedad", "observacion"], orden="fecha_inicio",
       validar=_validar_novedad, permiso_leer="escribir"),

    Entidad("periodo_nomina", "periodo_nomina", "Periodos", "Periodo", "Nómina", ["periodo_id"], [
        Campo("periodo_id", "ID", "int", auto=True),
        Campo("anio", "Año", "int", minimo=1900, maximo=2100),
        Campo("mes", "Mes", "int", minimo=1, maximo=12),
        Campo("fecha_inicio", "Fecha inicio", "date", requerido=False, ayuda="Vacío = día 1 del mes"),
        Campo("fecha_fin", "Fecha fin", "date", requerido=False, ayuda="Vacío = último día del mes"),
    ], orden="anio", validar=_validar_periodo, permiso_leer="escribir"),

    _cat("departamento", "departamento", "Departamentos", "Departamento", "Nómina", "departamento_id", permiso_leer="escribir"),
    _cat("cargo", "cargo", "Cargos", "Cargo", "Nómina", "cargo_id", permiso_leer="escribir"),
    _cat("eps", "eps", "EPS", "EPS", "Nómina", "eps_id", permiso_leer="escribir"),
    _cat("fondo_pension", "fondo_pension", "Fondos de pensión", "Fondo de pensión", "Nómina", "fondo_pension_id", permiso_leer="escribir"),
    _cat("arl", "arl", "ARL", "ARL", "Nómina", "arl_id", permiso_leer="escribir"),

    # ---------------- LIBROS ----------------
    Entidad("libro", "libro", "Libros", "Libro", "Libros", ["libro_id"], [
        Campo("libro_id", "ID libro", "int", minimo=1),
        Campo("titulo", "Título", max_len=500),
        Campo("autores", "Autores", "m2m",
              m2m=("libro_autor", "libro_id", "autor_id", "autor", "autor_id", "nombre", "texto"),
              ayuda="Separa varios autores con /  (los que no existan se crean)"),
        Campo("isbn", "ISBN", requerido=False, max_len=13, en_lista=False),
        Campo("isbn13", "ISBN-13", requerido=False, max_len=13, en_lista=False),
        Campo("numero_paginas", "Páginas", "int", requerido=False, minimo=0),
        Campo("promedio_rating", "Rating", "decimal", requerido=False, minimo=0, maximo=5),
        Campo("cantidad_ratings", "N.º ratings", "int", requerido=False, minimo=0),
        Campo("cantidad_resenas", "N.º reseñas", "int", requerido=False, minimo=0, en_lista=False),
        Campo("fecha_publicacion", "Publicación", "date", requerido=False),
        Campo("editorial_id", "Editorial", "fk", ref=("editorial", "editorial_id", "nombre", "int")),
        Campo("idioma_id", "Idioma", "fk", ref=("idioma", "idioma_id", "codigo", "int")),
    ], busqueda=["titulo", "isbn", "isbn13"], orden="titulo", validar=_validar_libro),

    _cat("autor", "autor", "Autores", "Autor", "Libros", "autor_id", largo=200),
    _cat("editorial", "editorial", "Editoriales", "Editorial", "Libros", "editorial_id", largo=200),
    _cat("idioma", "idioma", "Idiomas", "Idioma", "Libros", "idioma_id", col="codigo",
         etiqueta="Código (ej. eng, spa)", largo=10),

    # ---------------- PELÍCULAS ----------------
    Entidad("pelicula", "pelicula", "Películas", "Película", "Películas", ["pelicula_id"], [
        Campo("pelicula_id", "ID película", "int", minimo=1),
        Campo("titulo", "Título", max_len=300),
        Campo("anio_estreno", "Año estreno", "int", requerido=False, minimo=1880, maximo=2100),
        Campo("generos", "Géneros", "m2m",
              m2m=("pelicula_genero", "pelicula_id", "genero_id", "genero_pelicula", "genero_id", "nombre", "checks")),
    ], busqueda=["titulo"], orden="titulo"),

    _cat("genero_pelicula", "genero_pelicula", "Géneros", "Género", "Películas", "genero_id", largo=60),

    # ---------------- SEGURIDAD (solo ADMIN) ----------------
    Entidad("rol", "rol", "Roles", "Rol", "Seguridad", ["id_rol"], [
        Campo("id_rol", "ID", "int", auto=True),
        Campo("nombre", "Nombre", max_len=30),
        Campo("descripcion", "Descripción", requerido=False, max_len=200),
    ], busqueda=["nombre"], orden="id_rol", permiso_leer="admin", permiso_escribir="admin"),
]

ENTIDADES = {e.clave: e for e in _lista}