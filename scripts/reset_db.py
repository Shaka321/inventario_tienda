import os, sqlite3

DB_PATH = "data/app.db"
SCHEMA = "scripts/schema.sql"

def reset():
    # 1) Borrar DB si existe
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    # 2) Asegurar carpeta data/
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    # 3) Crear nueva DB vacía y aplicar schema.sql
    conn = sqlite3.connect(DB_PATH)
    with open(SCHEMA, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
    print("✅ Base de datos reiniciada (sin datos).")

if __name__ == "__main__":
    reset()
