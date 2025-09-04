import sqlite3
from werkzeug.security import generate_password_hash

DB_PATH = "data/app.db"

EMAIL = "admin@example.com"
NOMBRE = "Admin"
PASSWORD = "admin123"  # la que vas a usar para entrar

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Asegura tabla usuarios (por si el schema aún no se aplicó)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT UNIQUE NOT NULL,
      nombre TEXT,
      pass_hash TEXT,
      creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # ¿Existe?
    cur.execute("SELECT id FROM usuarios WHERE email=?", (EMAIL,))
    row = cur.fetchone()

    if row:
        # Actualiza el hash
        cur.execute("UPDATE usuarios SET pass_hash=?, nombre=? WHERE email=?",
                    (generate_password_hash(PASSWORD), NOMBRE, EMAIL))
        print("🔁 Admin actualizado.")
    else:
        # Inserta nuevo
        cur.execute("INSERT INTO usuarios (email, nombre, pass_hash) VALUES (?,?,?)",
                    (EMAIL, NOMBRE, generate_password_hash(PASSWORD)))
        print("✅ Admin creado.")

    conn.commit()
    conn.close()
    print("Listo. Usuario:", EMAIL, "| Password:", PASSWORD)

if __name__ == "__main__":
    main()
