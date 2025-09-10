#!/usr/bin/env python3
import sqlite3, os

DB = "data/app.db"

def col_exists(cn, table, col):
    return any(r[1] == col for r in cn.execute(f"PRAGMA table_info({table})").fetchall())

with sqlite3.connect(DB) as cn:
    cn.execute("PRAGMA foreign_keys=ON;")
    # tamaño (ml)
    if not col_exists(cn, "productos", "tamano_ml"):
        cn.execute("ALTER TABLE productos ADD COLUMN tamano_ml REAL;")
    # variante (sabor/color)
    if not col_exists(cn, "productos", "variante"):
        cn.execute("ALTER TABLE productos ADD COLUMN variante TEXT;")
    # índices útiles (opcionales)
    cn.executescript("""
    CREATE INDEX IF NOT EXISTS idx_productos_variante ON productos(variante);
    CREATE INDEX IF NOT EXISTS idx_productos_tamano   ON productos(tamano_ml);
    """)
print("OK: migrate_040_variantes aplicada.")
