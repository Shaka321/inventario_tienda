#!/usr/bin/env python3
import sqlite3

DB = "data/app.db"

def col_exists(cn, table, column):
    return any(r[1] == column for r in cn.execute(f"PRAGMA table_info({table})"))

with sqlite3.connect(DB) as cn:
    cn.execute("PRAGMA foreign_keys=ON;")

    # Agregar columnas si no existen
    if not col_exists(cn, "productos", "tamanio_valor"):
        cn.execute("ALTER TABLE productos ADD COLUMN tamanio_valor REAL;")
    if not col_exists(cn, "productos", "tamanio_uom"):
        cn.execute("ALTER TABLE productos ADD COLUMN tamanio_uom TEXT;")
    if not col_exists(cn, "productos", "variante"):
        cn.execute("ALTER TABLE productos ADD COLUMN variante TEXT;")

    cn.commit()
print("OK: columnas tamanio_valor, tamanio_uom y variante listas.")
