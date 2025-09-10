import sqlite3
from datetime import datetime

DB_PATH = "data/app.db"

def db_conn():
    cn = sqlite3.connect(DB_PATH)
    cn.row_factory = sqlite3.Row
    cn.execute("PRAGMA foreign_keys = ON;")
    return cn

# ---------- Stock y costo promedio ----------
def get_on_hand_units(db, sku_id: int) -> int:
    row = db.execute("""
    SELECT COALESCE(SUM(CASE m.type
      WHEN 'PURCHASE' THEN l.qty_units
      WHEN 'ADJUST'   THEN l.qty_units
      WHEN 'TRANSFER' THEN l.qty_units
      WHEN 'SALE'     THEN -l.qty_units
    END),0) AS on_hand
    FROM inv_movement_lines l
    JOIN inv_movements m ON m.id = l.movement_id
    WHERE l.sku_id=?
    """, (sku_id,)).fetchone()
    return int(row["on_hand"] or 0)

def get_avg_cost(db, sku_id: int) -> float:
    row = db.execute("SELECT avg_cost FROM sku_cost WHERE sku_id=?", (sku_id,)).fetchone()
    return float(row["avg_cost"]) if row else 0.0

def set_avg_cost(db, sku_id: int, avg_cost: float):
    if db.execute("SELECT 1 FROM sku_cost WHERE sku_id=?", (sku_id,)).fetchone():
        db.execute("UPDATE sku_cost SET avg_cost=?, updated_at=(DATETIME('now','localtime')) WHERE sku_id=?",
                   (avg_cost, sku_id))
    else:
        db.execute("INSERT INTO sku_cost (sku_id, avg_cost) VALUES (?,?)", (sku_id, avg_cost))

def update_avg_cost_on_purchase(db, sku_id: int, qty_units: int, unit_cost: float):
    """Recalcula costo promedio ponderado después de una compra."""
    if qty_units <= 0: return
    stock_before = get_on_hand_units(db, sku_id)
    avg_before   = get_avg_cost(db, sku_id)
    total_before = max(stock_before, 0) * avg_before
    total_new    = total_before + (qty_units * unit_cost)
    qty_total    = max(stock_before + qty_units, 1)
    new_avg      = total_new / qty_total
    set_avg_cost(db, sku_id, new_avg)

# ---------- Movimientos y documentos ----------
def record_purchase(db, *, ts_iso: str, supplier: str|None, lines: list[dict], note: str|None=None):
    """
    lines: [
      { 'sku_id': int, 'qty_units': int, 'unit_cost': float, 'packaging_level': 'UNIT|PACK|CASE|BUNDLE', 'qty_packs': float|None }
    ]
    """
    db.execute("INSERT INTO purchases (ts, supplier) VALUES (?,?)", (ts_iso, supplier))
    purchase_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

    for ln in lines:
        db.execute("""
            INSERT INTO purchase_lines (purchase_id, sku_id, qty_units, unit_cost, packaging_level, qty_packs)
            VALUES (?,?,?,?,?,?)
        """, (purchase_id, ln["sku_id"], ln["qty_units"], ln["unit_cost"], ln.get("packaging_level"), ln.get("qty_packs")))

    db.execute("INSERT INTO inv_movements (ts, type, ref, note) VALUES (?, 'PURCHASE', 'app', ?)", (ts_iso, note))
    mov_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

    for ln in lines:
        db.execute("""
            INSERT INTO inv_movement_lines (movement_id, sku_id, qty_units, packaging_level, qty_packs, unit_price)
            VALUES (?,?,?,?,?,?)
        """, (mov_id, ln["sku_id"], ln["qty_units"], ln.get("packaging_level"), ln.get("qty_packs"), ln["unit_cost"]))
        update_avg_cost_on_purchase(db, ln["sku_id"], ln["qty_units"], ln["unit_cost"])

def record_sale(db, *, ts_iso: str, customer: str|None, lines: list[dict]):
    """
    lines: [
      { 'sku_id': int, 'qty_units': int, 'price_per_un': float, 'packaging_level': 'UNIT|PACK|CASE|BUNDLE', 'qty_packs': float|None }
    ]
    """
    # Validar stock suficiente
    for ln in lines:
        onh = get_on_hand_units(db, ln["sku_id"])
        if ln["qty_units"] > onh:
            raise ValueError(f"Stock insuficiente para SKU {ln['sku_id']}: tienes {onh}, quieres {ln['qty_units']}.")

    db.execute("INSERT INTO sales (ts, customer) VALUES (?,?)", (ts_iso, customer))
    sale_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

    # Movimiento
    db.execute("INSERT INTO inv_movements (ts, type, ref) VALUES (?, 'SALE', 'app')", (ts_iso,))
    mov_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

    for ln in lines:
        cogs_unit = get_avg_cost(db, ln["sku_id"])
        cogs_total = cogs_unit * ln["qty_units"]

        db.execute("""
            INSERT INTO sale_lines (sale_id, sku_id, qty_units, unit_price, packaging_level, qty_packs, cogs_unit, cogs_total)
            VALUES (?,?,?,?,?,?,?,?)
        """, (sale_id, ln["sku_id"], ln["qty_units"], ln["price_per_un"], ln.get("packaging_level"), ln.get("qty_packs"), cogs_unit, cogs_total))

        db.execute("""
            INSERT INTO inv_movement_lines (movement_id, sku_id, qty_units, packaging_level, qty_packs, unit_price)
            VALUES (?,?,?,?,?,?)
        """, (mov_id, ln["sku_id"], -ln["qty_units"], ln.get("packaging_level"), ln.get("qty_packs"), ln["price_per_un"]))
