import os, sqlite3
os.makedirs("instance", exist_ok=True)
db_path = os.path.join("instance", "app.db")
con = sqlite3.connect(db_path)
c = con.cursor()

c.execute("""CREATE TABLE IF NOT EXISTS productos(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre TEXT NOT NULL,
  categoria TEXT,
  precio REAL DEFAULT 0,
  cantidad INTEGER DEFAULT 0,
  proveedor TEXT,
  codigo TEXT UNIQUE,
  fecha TEXT,
  precio_paquete REAL,
  unidades_por_paquete INTEGER
)""")

c.execute("""CREATE TABLE IF NOT EXISTS ventas(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fecha TEXT,
  producto TEXT,
  cantidad INTEGER,
  precio_unit REAL,
  total REAL
)""")

c.execute("""CREATE TABLE IF NOT EXISTS gastos(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fecha TEXT,
  motivo TEXT,
  monto REAL
)""")

c.execute("""CREATE TABLE IF NOT EXISTS reposiciones(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fecha TEXT,
  producto TEXT,
  cantidad INTEGER,
  costo_unit REAL,
  proveedor TEXT,
  ref TEXT
)""")

c.execute("""CREATE TABLE IF NOT EXISTS usuarios(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE,
  nombre TEXT,
  pass_hash TEXT
)""")

con.commit(); con.close()
print("Migración 030: tablas base listas.")
