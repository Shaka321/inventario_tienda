#!/usr/bin/env python3
import sqlite3, sys

DB = "data/app.db"

def table_exists(cn, name):
    return cn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",
        (name,)
    ).fetchone() is not None

def col_exists(cn, table, column):
    rows = cn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)

with sqlite3.connect(DB) as cn:
    cn.execute("PRAGMA foreign_keys=ON;")

    # === A) columnas COGS en sale_lines (si existe la tabla)
    if table_exists(cn, "sale_lines"):
        if not col_exists(cn, "sale_lines", "cogs_unit"):
            cn.execute("ALTER TABLE sale_lines ADD COLUMN cogs_unit REAL;")
        if not col_exists(cn, "sale_lines", "cogs_total"):
            cn.execute("ALTER TABLE sale_lines ADD COLUMN cogs_total REAL;")

    # === B) tablas auxiliares (costos y umbrales)
    cn.executescript("""
    CREATE TABLE IF NOT EXISTS sku_cost (
      sku_id INTEGER PRIMARY KEY REFERENCES skus(id) ON DELETE CASCADE,
      avg_cost REAL NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL DEFAULT (DATETIME('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS sku_threshold (
      sku_id INTEGER PRIMARY KEY REFERENCES skus(id) ON DELETE CASCADE,
      min_units INTEGER NOT NULL DEFAULT 0
    );
    """)

    # === C) crea v_stock_on_hand si no existe (necesaria para valorización)
    if not table_exists(cn, "v_stock_on_hand"):
        if table_exists(cn, "inv_movement_lines") and table_exists(cn, "inv_movements"):
            cn.executescript("""
            CREATE VIEW IF NOT EXISTS v_stock_on_hand AS
            SELECT
              l.sku_id,
              SUM(CASE m.type
                    WHEN 'PURCHASE' THEN l.qty_units
                    WHEN 'ADJUST'   THEN l.qty_units
                    WHEN 'TRANSFER' THEN l.qty_units
                    WHEN 'SALE'     THEN -l.qty_units
                  END) AS on_hand_units
            FROM inv_movement_lines l
            JOIN inv_movements m ON m.id = l.movement_id
            GROUP BY l.sku_id;
            """)
        else:
            print("WARN: No se encontraron tablas de movimientos para crear v_stock_on_hand.")

    # === D) Vistas de finanzas (no fallan si faltan datos)
    cn.executescript("""
    CREATE VIEW IF NOT EXISTS v_sales_fin AS
    SELECT
      s.ts,
      l.sku_id,
      l.qty_units,
      l.unit_price,
      (l.qty_units * l.unit_price) AS revenue,
      l.cogs_unit,
      l.cogs_total
    FROM sales s
    JOIN sale_lines l ON l.sale_id = s.id;

    CREATE VIEW IF NOT EXISTS v_sales_daily AS
    SELECT DATE(ts) AS day,
           SUM(revenue) AS revenue,
           SUM(cogs_total) AS cogs,
           SUM(revenue) - SUM(cogs_total) AS margin
    FROM v_sales_fin
    GROUP BY DATE(ts)
    ORDER BY day;

    CREATE VIEW IF NOT EXISTS v_sales_weekly AS
    SELECT STRFTIME('%Y-W%W', ts) AS year_week,
           SUM(revenue) AS revenue,
           SUM(cogs_total) AS cogs,
           SUM(revenue) - SUM(cogs_total) AS margin
    FROM v_sales_fin
    GROUP BY STRFTIME('%Y-W%W', ts)
    ORDER BY year_week;

    CREATE VIEW IF NOT EXISTS v_sales_monthly AS
    SELECT STRFTIME('%Y-%m', ts) AS year_month,
           SUM(revenue) AS revenue,
           SUM(cogs_total) AS cogs,
           SUM(revenue) - SUM(cogs_total) AS margin
    FROM v_sales_fin
    GROUP BY STRFTIME('%Y-%m', ts)
    ORDER BY year_month;
    """)

    # Estas dos requieren v_stock_on_hand; si no existe, las crea igual pero ya la intentamos crear arriba
    cn.executescript("""
    CREATE VIEW IF NOT EXISTS v_top_products AS
    SELECT
      sk.id AS sku_id,
      p.name AS product_name,
      IFNULL(b.name,'') AS brand,
      SUM(l.qty_units) AS units_sold,
      SUM(l.qty_units * l.unit_price) AS revenue
    FROM sale_lines l
    JOIN skus sk ON sk.id = l.sku_id
    LEFT JOIN products p ON p.id = sk.product_id
    LEFT JOIN brands b ON b.id = sk.brand_id
    GROUP BY sk.id, p.name, b.name
    ORDER BY revenue DESC;

    CREATE VIEW IF NOT EXISTS v_inventory_valuation AS
    SELECT
      soh.sku_id,
      soh.on_hand_units,
      sc.avg_cost,
      (soh.on_hand_units * IFNULL(sc.avg_cost,0)) AS inventory_value
    FROM v_stock_on_hand soh
    LEFT JOIN sku_cost sc ON sc.sku_id = soh.sku_id;

    CREATE VIEW IF NOT EXISTS v_low_stock AS
    SELECT
      soh.sku_id,
      soh.on_hand_units,
      COALESCE(st.min_units, 10) AS min_units
    FROM v_stock_on_hand soh
    LEFT JOIN sku_threshold st ON st.sku_id = soh.sku_id
    WHERE soh.on_hand_units <= COALESCE(st.min_units, 10);
    """)

print("Migration 030 applied safely.")
