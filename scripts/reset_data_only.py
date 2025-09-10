#!/usr/bin/env python3
import sqlite3

DB = "data/app.db"

# Tablas de datos que vamos a limpiar (NO tocamos usuarios ni configuración)
TABLES = ["ventas", "gastos", "reposiciones", "productos"]

with sqlite3.connect(DB) as cn:
    cn.execute("PRAGMA foreign_keys = ON;")
    cn.isolation_level = None
    cn.execute("BEGIN;")

    # Borramos primero tablas que dependen de productos
    for t in ["ventas", "gastos", "reposiciones", "productos"]:
        exists = cn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (t,)
        ).fetchone()
        if exists:
            count = cn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            cn.execute(f"DELETE FROM {t}")
            print(f"✅ Eliminados {count} registros de {t}")
        else:
            print(f"ℹ️  Tabla {t} no existe, se omite.")

    # Reiniciar autoincrement si existe sqlite_sequence
    seq_exists = cn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'"
    ).fetchone()
    if seq_exists:
        for t in TABLES:
            cn.execute("DELETE FROM sqlite_sequence WHERE name=?", (t,))
        print("🔁 Reiniciados contadores AUTOINCREMENT para tablas de datos.")

    cn.execute("COMMIT;")
    cn.execute("VACUUM;")
    print("🎉 Limpieza completada.")
