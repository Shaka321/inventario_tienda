PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS usuarios (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  nombre TEXT,
  pass_hash TEXT,
  creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS productos (
  id INTEGER PRIMARY KEY,
  nombre TEXT NOT NULL,
  categoria TEXT,
  precio REAL DEFAULT 0,
  cantidad INTEGER DEFAULT 0,
  proveedor TEXT,
  codigo TEXT UNIQUE,
  fecha TEXT
);

CREATE TABLE IF NOT EXISTS ventas (
  fecha TEXT,
  producto TEXT,
  cantidad INTEGER,
  precio_unit REAL,
  total REAL
);

CREATE TABLE IF NOT EXISTS gastos (
  fecha TEXT,
  motivo TEXT,
  monto REAL
);

CREATE TABLE IF NOT EXISTS reposiciones (
  fecha TEXT,
  producto TEXT,
  cantidad INTEGER,
  costo_unit REAL,
  proveedor TEXT,
  ref TEXT
);
