# scripts/seed.py
import sqlite3
from werkzeug.security import generate_password_hash

DB_PATH = "data/app.db"

def seed():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Admin (si no existe)
    cur.execute("SELECT id FROM usuarios WHERE email=?", ("admin@example.com",))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO usuarios (email, nombre, pass_hash) VALUES (?,?,?)",
            ("admin@example.com", "Admin", generate_password_hash("admin123")),
        )

    # Producto de ejemplo
    cur.execute("""
    INSERT OR REPLACE INTO productos (id,nombre,categoria,precio,cantidad,proveedor,codigo,fecha)
    VALUES (1,'Detergente Ariel','Limpieza',12.5,40,'Proveedor SA','PROD0001',DATE('now'))
    """)

    # Movimientos demo
    cur.execute("INSERT INTO gastos (fecha,motivo,monto) VALUES (DATE('now'),'Luz',120.50)")
    cur.execute("INSERT INTO ventas (fecha,producto,cantidad,precio_unit,total) VALUES (DATE('now'),'Detergente Ariel',2,15.0,30.0)")
    cur.execute("INSERT INTO reposiciones (fecha,producto,cantidad,costo_unit,proveedor,ref) VALUES (DATE('now'),'Detergente Ariel',20,10.0,'Proveedor SA','manual')")

    conn.commit()
    conn.close()
    print("🌱 Seed ok.")

if __name__ == "__main__":
    seed()
