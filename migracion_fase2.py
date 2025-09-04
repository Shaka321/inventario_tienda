import sqlite3

db = 'inventario.db'
conn = sqlite3.connect(db)
c = conn.cursor()

def run(sql):
    try:
        c.execute(sql)
    except Exception as e:
        print('WARN:', e)

run("""CREATE TABLE IF NOT EXISTS proveedores(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre TEXT NOT NULL,
  telefono TEXT, email TEXT)""")

run("""CREATE TABLE IF NOT EXISTS compras(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fecha TEXT NOT NULL,
  proveedor_id INTEGER,
  total REAL,
  FOREIGN KEY(proveedor_id) REFERENCES proveedores(id))""")

run("""CREATE TABLE IF NOT EXISTS compra_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  compra_id INTEGER NOT NULL,
  producto_id INTEGER NOT NULL,
  cantidad INTEGER NOT NULL,
  costo_unit REAL NOT NULL,
  subtotal REAL NOT NULL,
  FOREIGN KEY(compra_id) REFERENCES compras(id),
  FOREIGN KEY(producto_id) REFERENCES productos(id))""")

run("CREATE INDEX IF NOT EXISTS idx_compra_items_compra ON compra_items(compra_id)")
run("CREATE INDEX IF NOT EXISTS idx_compra_items_producto ON compra_items(producto_id)")

run("""CREATE TABLE IF NOT EXISTS ventas_enc(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fecha TEXT NOT NULL,
  total REAL NOT NULL)""")

run("""CREATE TABLE IF NOT EXISTS venta_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  venta_id INTEGER NOT NULL,
  producto_id INTEGER NOT NULL,
  modo TEXT,
  cantidad INTEGER NOT NULL,
  unidades INTEGER NOT NULL,
  precio_unit REAL NOT NULL,
  subtotal REAL NOT NULL,
  FOREIGN KEY(venta_id) REFERENCES ventas_enc(id),
  FOREIGN KEY(producto_id) REFERENCES productos(id))""")

run("CREATE INDEX IF NOT EXISTS idx_venta_items_venta ON venta_items(venta_id)")
run("CREATE INDEX IF NOT EXISTS idx_venta_items_producto ON venta_items(producto_id)")

conn.commit(); conn.close()
print("Migración Fase 2 OK")
