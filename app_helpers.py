import json, re
import sqlite3
from datetime import datetime

DB_PATH = "data/app.db"

def db_conn():
    cn = sqlite3.connect(DB_PATH)
    cn.row_factory = sqlite3.Row
    cn.execute("PRAGMA foreign_keys = ON;")
    return cn

# ---------- Packaging / Unidades ----------
def to_units(db, sku_id: int, packaging_level: str, qty_packs: float) -> int:
    """Convierte cantidad de empaques a UN base usando packaging.units_per_parent. Si no hay registro, asume 1."""
    row = db.execute("""
        SELECT units_per_parent
        FROM packaging
        WHERE sku_id=? AND level=?
        ORDER BY
          CASE WHEN units_per_parent IS NULL THEN 1 ELSE 0 END,
          units_per_parent DESC, id DESC
        LIMIT 1
    """, (sku_id, packaging_level)).fetchone()
    upp = row["units_per_parent"] if row and row["units_per_parent"] else 1
    return int(round(qty_packs * upp))

def expand_mixed_components(db, parent_packaging_id: int, qty_packs: float):
    """Devuelve lista [(child_sku_id, qty_units_expandida), ...] para BUNDLE/mixto."""
    out = []
    cur = db.execute("""
        SELECT child_sku_id, qty_units
        FROM packaging_composition
        WHERE parent_packaging_id=?
    """, (parent_packaging_id,))
    for r in cur.fetchall():
        out.append((r["child_sku_id"], int(round(qty_packs * r["qty_units"]))))
    return out

# ---------- Atributos dinámicos ----------
def ensure_attribute(db, code: str, label: str, type_: str,
                     unit_constraint: str=None, enum_options=None, is_indexed: int=0) -> int:
    row = db.execute("SELECT id FROM attribute_def WHERE code=?", (code,)).fetchone()
    if row:
        return row["id"]
    enum_json = json.dumps(enum_options) if (enum_options is not None) else None
    db.execute("""
        INSERT INTO attribute_def (code, label, type, unit_constraint, enum_options, is_indexed)
        VALUES (?,?,?,?,?,?)
    """, (code, label, type_, unit_constraint, enum_json, int(is_indexed)))
    db.commit()
    return db.execute("SELECT id FROM attribute_def WHERE code=?", (code,)).fetchone()["id"]

def upsert_sku_attr(db, sku_id: int, code: str, value, unit_code: str=None):
    """Crea/actualiza valor de atributo del SKU. Detecta el tipo desde attribute_def."""
    a = db.execute("SELECT * FROM attribute_def WHERE code=?", (code,)).fetchone()
    if not a:
        raise ValueError(f"Atributo desconocido: {code}")
    unit_id = None
    if unit_code:
        u = db.execute("SELECT id FROM uom WHERE code=?", (unit_code,)).fetchone()
        if not u:
            raise ValueError(f"UOM desconocida: {unit_code}")
        unit_id = u["id"]

    val_num, val_text = None, None
    t = a["type"]
    if t == "number":
        try:
            val_num = float(value)
        except:
            raise ValueError(f"'{code}' debe ser numérico.")
    elif t in ("text","enum"):
        val_text = str(value).strip() if value is not None else None
        if t == "enum" and a["enum_options"]:
            import json as _json
            opts = set(_json.loads(a["enum_options"]))
            if val_text not in opts:
                raise ValueError(f"'{code}' debe ser uno de: {', '.join(opts)}.")
    elif t == "boolean":
        val_text = "1" if (str(value).lower() in ("1","true","sí","si","yes","on")) else "0"
    elif t == "date":
        val_text = str(value)
    else:
        raise ValueError(f"Tipo de atributo no soportado: {t}")

    attr_id = a["id"]
    ex = db.execute("SELECT id FROM sku_attr_value WHERE sku_id=? AND attr_id=?", (sku_id, attr_id)).fetchone()
    if ex:
        db.execute("""
            UPDATE sku_attr_value
            SET value_num=?, value_text=?, unit_id=?
            WHERE id=?
        """, (val_num, val_text, unit_id, ex["id"]))
    else:
        db.execute("""
            INSERT INTO sku_attr_value (sku_id, attr_id, value_num, value_text, unit_id)
            VALUES (?,?,?,?,?)
        """, (sku_id, attr_id, val_num, val_text, unit_id))
    db.commit()

def get_sku_attrs(db, sku_id: int) -> dict:
    out = {}
    cur = db.execute("""
        SELECT ad.code, ad.type, sav.value_num, sav.value_text, u.code AS unit_code
        FROM sku_attr_value sav
        JOIN attribute_def ad ON ad.id=sav.attr_id
        LEFT JOIN uom u ON u.id=sav.unit_id
        WHERE sav.sku_id=?
    """, (sku_id,))
    for r in cur.fetchall():
        if r["type"] == "number":
            out[r["code"]] = {"num": r["value_num"], "unit": r["unit_code"]}
        else:
            out[r["code"]] = r["value_text"]
    return out

# ---------- Tags ----------
def add_tag_if_missing(db, name: str) -> int:
    row = db.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
    if row:
        return row["id"]
    db.execute("INSERT INTO tags (name) VALUES (?)", (name,))
    db.commit()
    return db.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()["id"]

def set_sku_tags(db, sku_id: int, tag_names: list[str]):
    # reemplaza completamente los tags del SKU por la lista dada
    db.execute("DELETE FROM sku_tags WHERE sku_id=?", (sku_id,))
    for name in tag_names:
        t_id = add_tag_if_missing(db, name.strip())
        db.execute("INSERT OR IGNORE INTO sku_tags (sku_id, tag_id) VALUES (?,?)", (sku_id, t_id))
    db.commit()

# ---------- Validaciones genéricas ----------
def validate_packaging_rules(db, sku_id: int):
    # PACK/CASE requieren UNIT vendible salvo que sea SKU solo-BUNDLE
    rows = db.execute("SELECT level, is_sellable FROM packaging WHERE sku_id=?", (sku_id,)).fetchall()
    levels = {r["level"] for r in rows}
    has_unit = any((r["level"]=="UNIT" and r["is_sellable"]) for r in rows)
    need_unit = any(r["level"] in ("PACK","CASE") for r in rows)
    only_bundle = (levels == {"BUNDLE"}) or (levels == {"BUNDLE","UNIT"} and not has_unit)
    if need_unit and not has_unit and not only_bundle:
        raise ValueError("Si defines PACK o CASE, debes tener UNIT vendible (salvo SKU solo-BUNDLE).")

def validate_attribute_rules(db, sku_id: int):
    # Reglas opcionales por tag/categoría/siempre
    sku = db.execute("""
        SELECT sk.id, p.category_id
        FROM skus sk JOIN products p ON p.id=sk.product_id
        WHERE sk.id=?
    """, (sku_id,)).fetchone()
    if not sku:
        return
    cat_id = sku["category_id"]
    tag_ids = [r["tag_id"] for r in db.execute("SELECT tag_id FROM sku_tags WHERE sku_id=?", (sku_id,)).fetchall()]
    vals = get_sku_attrs(db, sku_id)
    rules = db.execute("SELECT * FROM attribute_rule").fetchall()

    for r in rules:
        applies = (r["applies_to"] == "always") or \
                  (r["applies_to"] == "category" and r["target_id"] == cat_id) or \
                  (r["applies_to"] == "tag"      and r["target_id"] in tag_ids)
        if not applies:
            continue

        ad = db.execute("SELECT * FROM attribute_def WHERE id=?", (r["attr_id"],)).fetchone()
        code, t = ad["code"], ad["type"]
        present = code in vals

        if r["required"] and not present:
            raise ValueError(f"Atributo requerido faltante: {ad['label']} ({code}).")

        if present:
            if t == "number":
                v = vals[code]["num"]
                if r["min_num"] is not None and v is not None and v < r["min_num"]:
                    raise ValueError(f"{ad['label']} debe ser ≥ {r['min_num']}.")
                if r["max_num"] is not None and v is not None and v > r["max_num"]:
                    raise ValueError(f"{ad['label']} debe ser ≤ {r['max_num']}.")
            elif t in ("text","enum") and r["regex"]:
                vt = vals[code]
                import re as _re
                if vt and not _re.fullmatch(r["regex"], vt):
                    raise ValueError(f"{ad['label']} no cumple el formato requerido.")
