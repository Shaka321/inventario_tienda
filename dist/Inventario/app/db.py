# app/db.py
import os
import sys
import sqlite3
from pathlib import Path

# -------------------------------
# Utilidades de rutas (PyInstaller + fuente)
# -------------------------------

def _base_dir_for_resources() -> Path:
    """
    Cuando va empacado con PyInstaller, los recursos (--add-data) se extraen
    en una carpeta temporal disponible en sys._MEIPASS.
    En modo fuente, usamos la raíz del proyecto (padre de app/).
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    # modo fuente: .../proyecto/
    return Path(__file__).resolve().parents[1]

def _resource_path(rel: str) -> Path:
    """
    Devuelve la ruta absoluta a un recurso empacado con --add-data.
    Ejemplo: _resource_path("scripts/schema.sql")
    """
    return _base_dir_for_resources() / rel

# -------------------------------
# Conexión a la DB
# -------------------------------

def _db_path_from_url(url: str) -> str:
    """
    Extrae el path de un URL tipo sqlite:///algo/app.db
    Soporta también ruta absoluta: sqlite:////abs/dir/app.db
    """
    if not url:
        return "data/app.db"
    prefix = "sqlite:///"
    if url.startswith(prefix):
        return url[len(prefix):]
    # fallback: si te pasan sólo un path
    return url

def get_db() -> sqlite3.Connection:
    """
    Retorna una conexión global (por proceso) con row_factory a dict (sqlite3.Row)
    y foreign_keys activado.
    """
    conn = getattr(get_db, "_conn", None)
    if conn is None:
        db_url = os.getenv("DATABASE_URL", "sqlite:///data/app.db")
        db_path = _db_path_from_url(db_url)
        # Asegura carpeta
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        get_db._conn = conn
    return conn

# -------------------------------
# Bootstrap de la base
# -------------------------------

def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cur.fetchone() is not None

def init_db_if_needed(app=None) -> None:
    """
    Crea la DB y ejecuta scripts/schema.sql si no existen las tablas base.
    - Busca el schema con _resource_path('scripts/schema.sql'), que sirve tanto
      empacado (PyInstaller) como en modo fuente.
    """
    conn = get_db()
    # ¿Ya existe alguna tabla clave? Usa 'usuarios' como marcador.
    if _table_exists(conn, "usuarios"):
        return

    # Carga el schema
    schema_file = _resource_path("scripts/schema.sql")
    if not schema_file.exists():
        # Fallback defensivo por si no se empacó el schema: crea sólo usuarios
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            nombre TEXT NOT NULL,
            pass_hash TEXT NOT NULL
        );
        """)
        conn.commit()
        return

    sql = schema_file.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()
