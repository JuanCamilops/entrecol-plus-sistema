"""
Pruebas de integración contra una base MySQL de pruebas (proyecto_bd_test).
Ejecutar desde la carpeta del proyecto, con MySQL encendido:
    pip install pytest
    python -m pytest -q tests
"""
import io
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
os.environ["DB_NAME"] = "proyecto_bd_test"
os.environ["SECRET_KEY"] = "pruebas"
sys.path.insert(0, str(RAIZ))

import captcha  # noqa: E402
from app import create_app  # noqa: E402


@pytest.fixture(scope="session")
def app():
    subprocess.run([sys.executable, "init_db.py", "--reset", "--datos-ejemplo"], cwd=RAIZ, check=True,
                   env={**os.environ}, capture_output=True)
    a = create_app()
    a.config["TESTING"] = True
    return a


def _csrf(html):
    return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)


def _respuesta_captcha(cliente):
    cliente.get("/captcha.png")
    with cliente.session_transaction() as s:
        return captcha._almacen[s["captcha_token"]][0]


def login(cliente, usuario="admin", clave="Admin123*", captcha_ok=True):
    token = _csrf(cliente.get("/login").get_data(as_text=True))
    resp = _respuesta_captcha(cliente) if captcha_ok else "XXXXX"
    return cliente.post("/login", data={"_csrf": token, "username": usuario, "password": clave,
                                        "captcha": resp.lower()}, follow_redirects=True)


def token(cliente, url="/"):
    return _csrf(cliente.get(url).get_data(as_text=True))


def test_requiere_login(app):
    c = app.test_client()
    assert c.get("/datos/empleado/").status_code == 302


def test_login_y_captcha(app):
    c = app.test_client()
    assert "captcha es incorrecto" in login(c, captcha_ok=False).get_data(as_text=True)
    r = login(c)
    assert "Panel principal" in r.get_data(as_text=True)


def test_captcha_un_solo_uso(app):
    c = app.test_client()
    t = _csrf(c.get("/login").get_data(as_text=True))
    resp = _respuesta_captcha(c)
    datos = {"_csrf": t, "username": "admin", "password": "mala", "captcha": resp}
    c.post("/login", data=datos)
    assert "captcha es incorrecto" in c.post("/login", data=datos).get_data(as_text=True)


def test_csrf_obligatorio(app):
    c = app.test_client()
    assert c.post("/login", data={"username": "admin", "password": "x"}).status_code == 400


def test_registro_bloqueo_y_desbloqueo(app):
    c = app.test_client()
    t = _csrf(c.get("/registro").get_data(as_text=True))
    r = c.post("/registro", data={"_csrf": t, "username": "debil", "correo": "d@x.com", "password": "123",
                                  "password2": "123", "captcha": _respuesta_captcha(c)})
    assert "La contraseña necesita" in r.get_data(as_text=True)
    t = _csrf(c.get("/registro").get_data(as_text=True))
    r = c.post("/registro", data={"_csrf": t, "username": "lector", "correo": "lector@x.com",
                                  "password": "Clave#2026x", "password2": "Clave#2026x",
                                  "captcha": _respuesta_captcha(c)}, follow_redirects=True)
    assert "Cuenta creada" in r.get_data(as_text=True)
    for _ in range(2):
        assert "Te quedan" in login(c, "lector", "mala").get_data(as_text=True)
    assert "Cuenta bloqueada" in login(c, "lector", "mala").get_data(as_text=True)
    assert "bloqueada o inactiva" in login(c, "lector", "Clave#2026x").get_data(as_text=True)
    a = app.test_client()
    login(a)
    import db
    uid = db.escalar("SELECT id_usuario FROM usuario WHERE username = 'lector'")
    a.post(f"/admin/usuarios/{uid}/desbloquear", data={"_csrf": token(a)})
    assert "Panel principal" in login(c, "lector", "Clave#2026x").get_data(as_text=True)
    # rol CONSULTA: puede leer, no escribir ni cargar
    assert c.get("/datos/empleado/").status_code == 200
    assert c.get("/datos/empleado/nuevo").status_code == 403
    assert c.get("/cargas/").status_code == 403
    assert c.get("/admin/usuarios").status_code == 403


def test_crud_empleado(app):
    c = app.test_client()
    login(c)
    t = token(c, "/datos/empleado/nuevo")
    datos = {"_csrf": t, "codigo": "T900", "nombre_completo": "Prueba Unitaria", "fecha_ingreso": "2024-05-01",
             "sueldo": "2.500.000", "id_dependencia": "1", "id_cargo": "1", "id_eps": "1", "id_pension": "1",
             "id_arl": "1"}
    r = c.post("/datos/empleado/nuevo", data=datos, follow_redirects=True)
    assert "Empleado creado" in r.get_data(as_text=True)
    r = c.post("/datos/empleado/nuevo", data=datos, follow_redirects=True)
    assert "Ya existe un registro" in r.get_data(as_text=True)
    r = c.get("/datos/empleado/?q=Prueba+Unitaria")
    assert "T900" in r.get_data(as_text=True)
    r = c.post("/datos/empleado/editar?codigo=T900", data={**datos, "sueldo": "abc"}, follow_redirects=True)
    assert "debe ser un número" in r.get_data(as_text=True)
    r = c.post("/datos/empleado/editar?codigo=T900", data={**datos, "sueldo": "3000000"}, follow_redirects=True)
    assert "Empleado actualizado" in r.get_data(as_text=True)
    import db
    assert db.escalar("SELECT sueldo FROM empleado WHERE codigo='T900'") == 3000000
    r = c.post("/datos/empleado/eliminar", data={"_csrf": t, "codigo": "T900"}, follow_redirects=True)
    assert "Empleado eliminado" in r.get_data(as_text=True)
    # un empleado con liquidaciones no se puede borrar (integridad referencial)
    r = c.post("/datos/empleado/eliminar", data={"_csrf": t, "codigo": "E001"}, follow_redirects=True)
    assert "hay otros registros que dependen" in r.get_data(as_text=True)
    assert db.escalar("SELECT COUNT(*) FROM auditoria WHERE tabla_afectada='empleado' AND accion "
                      "IN ('INSERT','UPDATE','DELETE')") >= 3


def test_crud_libro_m2m_y_pk_compuesta(app):
    c = app.test_client()
    login(c)
    t = token(c, "/datos/libro/nuevo")
    r = c.post("/datos/libro/nuevo", data={"_csrf": t, "id_libro": "777", "titulo": "Libro de prueba",
                                           "autores": "Autor Nuevo / Lucía Herrera", "isbn": "0439785960",
                                           "id_editorial": "1", "id_idioma": "1"}, follow_redirects=True)
    assert "Libro creado" in r.get_data(as_text=True)
    import db
    assert db.escalar("SELECT COUNT(*) FROM libro_autor WHERE id_libro = 777") == 2
    r = c.get("/datos/libro/editar?id_libro=777")
    assert "Autor Nuevo / Lucía Herrera" in r.get_data(as_text=True)
    # llave primaria compuesta (codigo, id_periodo)
    r = c.post("/datos/liquidacion/editar?codigo=E001&id_periodo=1",
               data={"_csrf": t, "codigo": "E001", "id_periodo": "1", "dias_trabajados": "31",
                     "bonificacion": "0", "transporte": "0"}, follow_redirects=True)
    assert "menor o igual a 30" in r.get_data(as_text=True)
    r = c.get("/datos/liquidacion/?f_id_periodo=2&orden=codigo__txt&dir=desc&exportar=csv")
    assert r.status_code == 200 and r.data.decode("utf-8-sig").count("\n") == 41


def test_consultas(app):
    c = app.test_client()
    login(c)
    for clave in ("nomina_periodo", "nomina_dependencia", "afiliaciones", "novedades", "top_libros",
                  "autores", "libros_editorial", "peliculas", "generos_decada"):
        r = c.get(f"/consultas/{clave}")
        assert r.status_code == 200, clave
    r = c.get("/consultas/nomina_periodo?ejecutar=1&periodo=1")
    assert "E001" in r.get_data(as_text=True)
    r = c.get("/consultas/top_libros?ejecutar=1&min_ratings=0&limite=5&autor=Herrera&exportar=csv")
    assert r.status_code == 200 and "Herrera" in r.data.decode("utf-8-sig")


def test_carga_archivo(app):
    c = app.test_client()
    login(c)
    t = token(c, "/cargas/")
    csv = ("movieId,title,genres\n"
           "1,Toy Story (1995),Adventure|Animation|Children|Comedy|Fantasy\n"
           "1,Toy Story (1995),Adventure\n"
           "2,Sin genero (2000),(no genres listed)\n"
           "abc,Malo,Drama\n"
           "900001,Repetida,Drama\n")
    r = c.post("/cargas/", data={"_csrf": t, "tipo": "peliculas",
                                 "archivo": (io.BytesIO(csv.encode()), "nuevas.csv")},
               content_type="multipart/form-data")
    html = r.get_data(as_text=True)
    assert "PARCIAL" in html and "repetido en el archivo" in html and "ya existe" in html
    import db
    assert db.consultar_uno("SELECT titulo, anio FROM pelicula WHERE id_pelicula = 1") == \
        {"titulo": "Toy Story", "anio": 1995}
    # archivo con columnas incorrectas -> ERROR y nada guardado
    r = c.post("/cargas/", data={"_csrf": t, "tipo": "libros",
                                 "archivo": (io.BytesIO(b"a,b\n1,2\n"), "malo.csv")},
               content_type="multipart/form-data")
    assert "Faltan columnas obligatorias" in r.get_data(as_text=True)
    assert c.get("/cargas/historial").status_code == 200
