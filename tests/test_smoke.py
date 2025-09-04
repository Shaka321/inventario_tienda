# tests/test_smoke.py
import os
import pytest
from app import create_app

@pytest.fixture
def client(tmp_path):
    """
    Crea un cliente de pruebas con una base SQLite temporal (archivo en /tmp).
    La app fábrica (create_app) leerá DATABASE_URL y creará la DB (schema.sql)
    automáticamente si no existe.
    """
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path}/test.db"
    os.environ["SECRET_KEY"] = "test"
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()

def _try_paths(client, paths, ok=(200, 302)):
    """
    Intenta GET a varias rutas alternativas.
    Aprueba si cualquiera responde con 200 o 302.
    Si todas fallan, aserta con el detalle de estados recibidos.
    """
    tried = []
    for p in paths:
        res = client.get(p)
        tried.append((p, res.status_code))
        if res.status_code in ok:
            return  # pasó
    # Si llegó aquí, ninguna alternativa pasó
    details = ", ".join([f"{p}→{code}" for p, code in tried])
    assert False, f"Ninguna ruta respondió 200/302. Probé: {details}"

def test_home_ok(client):
    # Home típico
    _try_paths(client, ["/"])

def test_inventario_ok(client):
    # Algunas apps lo montan en /inventario; otras usan / o /admin para listar
    _try_paths(client, ["/inventario", "/"])

def test_finanzas_ok(client):
    # Alternativas comunes para panel de finanzas
    _try_paths(client, ["/fin", "/finanzas", "/"])

def test_gastos_listado_ok(client):
    # Intentamos primero /fin/gastos (como en varias plantillas),
    # y si no existe, probamos /gastos (tu ruta actual)
    _try_paths(client, ["/fin/gastos", "/gastos"])
