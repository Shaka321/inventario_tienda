-- ===== Atributos dinámicos (diccionario) =====
CREATE TABLE IF NOT EXISTS attribute_def (
  id INTEGER PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,              -- ej: 'size_value','size_uom','size_text','purpose','talla','voltaje'
  label TEXT NOT NULL,                    -- etiqueta legible
  type TEXT NOT NULL CHECK (type IN ('number','text','enum','boolean','date')),
  unit_constraint TEXT,                   -- ej: 'ML|L|G|KG|UN|V|cm|mm|Lts'
  enum_options TEXT,                      -- JSON opcional: '["adulto","niño"]'
  is_indexed INTEGER NOT NULL DEFAULT 0
);

-- ===== Valores por SKU (EAV) =====
CREATE TABLE IF NOT EXISTS sku_attr_value (
  id INTEGER PRIMARY KEY,
  sku_id INTEGER NOT NULL REFERENCES skus(id) ON DELETE CASCADE,
  attr_id INTEGER NOT NULL REFERENCES attribute_def(id) ON DELETE CASCADE,
  value_num REAL,
  value_text TEXT,
  unit_id INTEGER REFERENCES uom(id),
  UNIQUE (sku_id, attr_id)
);

CREATE INDEX IF NOT EXISTS idx_sku_attr_num ON sku_attr_value (attr_id, value_num);
CREATE INDEX IF NOT EXISTS idx_sku_attr_text ON sku_attr_value (attr_id, value_text);

-- ===== Tags libres =====
CREATE TABLE IF NOT EXISTS tags (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS sku_tags (
  sku_id INTEGER NOT NULL REFERENCES skus(id) ON DELETE CASCADE,
  tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY (sku_id, tag_id)
);

-- ===== (Opcional) Reglas por atributo =====
CREATE TABLE IF NOT EXISTS attribute_rule (
  id INTEGER PRIMARY KEY,
  applies_to TEXT NOT NULL CHECK (applies_to IN ('always','tag','category')),
  target_id INTEGER,                      -- tag_id o category_id si aplica
  attr_id INTEGER NOT NULL REFERENCES attribute_def(id) ON DELETE CASCADE,
  required INTEGER NOT NULL DEFAULT 0,    -- 1=obligatorio en ese contexto
  min_num REAL,                           -- si es number
  max_num REAL,
  regex TEXT                              -- si es text
);
