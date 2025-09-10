import os, sqlite3
os.makedirs("instance", exist_ok=True)
db_path = os.path.join("instance", "app.db")
con = sqlite3.connect(db_path)
c = con.cursor()

def has_col(table, col):
    cur = c.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())

# columnas usadas por reposiciones vinculadas a gasto
for col, ddl in [
    ("total_compra", "ALTER TABLE reposiciones ADD COLUMN total_compra REAL"),
    ("gasto_rowid",  "ALTER TABLE reposiciones ADD COLUMN gasto_rowid INTEGER"),
]:
    try:
        if not has_col("reposiciones", col):
            c.execute(ddl)
    except sqlite3.OperationalError:
        pass

con.commit(); con.close()
print("Migración 040 variantes: columnas en reposiciones añadidas si faltaban.")
