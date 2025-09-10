import os, sqlite3
os.makedirs("instance", exist_ok=True)
db_path = os.path.join("instance", "app.db")
con = sqlite3.connect(db_path)
c = con.cursor()

def has_col(table, col):
    cur = c.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())

# columnas nuevas en productos
for col, ddl in [
    ("tamanio_valor", "ALTER TABLE productos ADD COLUMN tamanio_valor REAL"),
    ("tamanio_uom",   "ALTER TABLE productos ADD COLUMN tamanio_uom TEXT"),
    ("variante",      "ALTER TABLE productos ADD COLUMN variante TEXT"),
]:
    try:
        if not has_col("productos", col):
            c.execute(ddl)
    except sqlite3.OperationalError:
        pass

con.commit(); con.close()
print("Migración 040 size/variant: columnas añadidas si faltaban.")
