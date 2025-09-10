-- =========================
-- Unidades de medida (catálogo mínimo)
-- =========================
CREATE TABLE IF NOT EXISTS uom (
  id INTEGER PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,      -- 'UN','ML','L','G','KG'
  desc TEXT
);
INSERT OR IGNORE INTO uom (code, desc) VALUES
 ('UN','Unidad'),
 ('ML','Mililitro'),
 ('L','Litro'),
 ('G','Gramo'),
 ('KG','Kilogramo');

-- =========================
-- Catálogos base (vacíos por ahora)
-- =========================
CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS brands (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL
);

-- =========================
-- Productos (SPU) y SKUs (variantes)
-- =========================
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  category_id INTEGER REFERENCES categories(id),
  notes TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_products_name ON products(name);

CREATE TABLE IF NOT EXISTS skus (
  id INTEGER PRIMARY KEY,
  product_id INTEGER NOT NULL REFERENCES products(id),
  brand_id INTEGER REFERENCES brands(id),
  -- columnas opcionales de compatibilidad con tu UI actual
  color_scent TEXT,
  audience TEXT,
  gender TEXT,
  size_value REAL,
  size_uom_id INTEGER REFERENCES uom(id),
  size_text TEXT,
  purpose TEXT,
  is_active INTEGER NOT NULL DEFAULT 1,
  barcode TEXT UNIQUE
);

-- =========================
-- Empaques y composiciones
-- =========================
CREATE TABLE IF NOT EXISTS packaging (
  id INTEGER PRIMARY KEY,
  sku_id INTEGER NOT NULL REFERENCES skus(id),
  level TEXT NOT NULL,                 -- 'UNIT'|'PACK'|'CASE'|'BUNDLE'
  label TEXT,
  units_per_parent INTEGER,
  is_sellable INTEGER NOT NULL DEFAULT 1,
  is_purchasable INTEGER NOT NULL DEFAULT 1,
  min_sell_multiple INTEGER DEFAULT 1,
  exception_type TEXT                  -- 'zacanas'|'combo'|NULL
);
CREATE INDEX IF NOT EXISTS idx_packaging_sku ON packaging(sku_id);

CREATE TABLE IF NOT EXISTS packaging_composition (
  id INTEGER PRIMARY KEY,
  parent_packaging_id INTEGER NOT NULL REFERENCES packaging(id),
  child_sku_id INTEGER NOT NULL REFERENCES skus(id),
  qty_units INTEGER NOT NULL
);

-- =========================
-- Compras/Ventas y Movimientos
-- =========================
CREATE TABLE IF NOT EXISTS purchases (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL DEFAULT (DATETIME('now','localtime')),
  supplier TEXT
);
CREATE TABLE IF NOT EXISTS purchase_lines (
  id INTEGER PRIMARY KEY,
  purchase_id INTEGER NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
  sku_id INTEGER NOT NULL REFERENCES skus(id),
  qty_units INTEGER NOT NULL,
  unit_cost REAL NOT NULL,
  packaging_level TEXT,
  qty_packs REAL
);

CREATE TABLE IF NOT EXISTS sales (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL DEFAULT (DATETIME('now','localtime')),
  customer TEXT
);
CREATE TABLE IF NOT EXISTS sale_lines (
  id INTEGER PRIMARY KEY,
  sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
  sku_id INTEGER NOT NULL REFERENCES skus(id),
  qty_units INTEGER NOT NULL,
  unit_price REAL NOT NULL,
  packaging_level TEXT,
  qty_packs REAL
  -- columnas COGS las agrega migrate_030.py si faltan
);

CREATE TABLE IF NOT EXISTS inv_movements (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL DEFAULT (DATETIME('now','localtime')),
  type TEXT NOT NULL,          -- 'PURCHASE'|'SALE'|'ADJUST'|'TRANSFER'
  ref TEXT,
  note TEXT
);
CREATE TABLE IF NOT EXISTS inv_movement_lines (
  id INTEGER PRIMARY KEY,
  movement_id INTEGER NOT NULL REFERENCES inv_movements(id) ON DELETE CASCADE,
  sku_id INTEGER NOT NULL REFERENCES skus(id),
  qty_units INTEGER NOT NULL,             -- SIEMPRE en UN base
  packaging_level TEXT,
  qty_packs REAL,
  unit_price REAL,
  currency TEXT DEFAULT 'BOB'
);
