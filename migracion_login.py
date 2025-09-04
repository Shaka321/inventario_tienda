# migracion_login.py
import sqlite3, datetime
from werkzeug.security import generate_password_hash

DB = 'inventario.db'

conn = sqlite3.connect(DB)
c = conn.cursor()

# Tabla de usuarios
c.execute("""
CREATE TABLE IF NOT EXISTS usuarios (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  rol TEXT NOT NULL DEFAULT 'admin',
  activo INTEGER NOT NULL DEFAULT 1,
  creado_en TEXT NOT NULL
)
""")

# Crear admin si no existe
c.execute("SELECT COUNT(*) FROM usuarios WHERE username = 'admin'")
existe = c.fetchone()[0]

if existe == 0:
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    pw_hash = generate_password_hash("admin123")  # <-- puedes cambiar la clave aquí
    c.execute("""INSERT INTO usuarios (username, password_hash, rol, activo, creado_en)
                 VALUES (?, ?, 'admin', 1, ?)""", ('admin', pw_hash, now))
    print("✅ Usuario creado: admin / admin123 (cámbialo pronto)")

conn.commit(); conn.close()
print("Migración de login OK.")
