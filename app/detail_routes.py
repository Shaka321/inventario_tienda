from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime
from app_helpers import db_conn, ensure_attribute, upsert_sku_attr, set_sku_tags, \
                        validate_packaging_rules, validate_attribute_rules, \
                        to_units, expand_mixed_components
from app_finance import record_purchase, record_sale

bp = Blueprint("detail", __name__)

# ========== Atributos ==========
@bp.route("/atributos", methods=["GET","POST"])
def atributos():
    db = db_conn()
    if request.method == "POST":
        try:
            code  = request.form["code"].strip()
            label = request.form["label"].strip()
            type_ = request.form["type"]
            unit_constraint = request.form.get("unit_constraint") or None
            enum_raw = request.form.get("enum_options") or None
            enum_options = [s.strip() for s in enum_raw.split(",")] if enum_raw else None
            ensure_attribute(db, code, label, type_, unit_constraint, enum_options, is_indexed=int(request.form.get("is_indexed","0")))
            flash("Atributo guardado.", "success")
        except Exception as e:
            flash(f"Error: {e}", "danger")
        return redirect(url_for("detail.atributos"))

    rows = db.execute("SELECT * FROM attribute_def ORDER BY code").fetchall()
    return render_template("atributos.html", attrs=rows)

# ========== Alta de SKU ==========
@bp.route("/sku/nuevo", methods=["GET","POST"])
def sku_nuevo():
    db = db_conn()
    if request.method == "POST":
        try:
            db.execute("BEGIN")
            product_name = request.form["product_name"].strip()
            category     = request.form.get("category") or None
            brand        = request.form.get("brand") or None
            barcode      = request.form.get("barcode") or None

            # product
            prow = db.execute("SELECT id FROM products WHERE name=?", (product_name,)).fetchone()
            if not prow:
                cat_id = None
                if category:
                    c = db.execute("SELECT id FROM categories WHERE name=?", (category,)).fetchone()
                    if not c:
                        db.execute("INSERT INTO categories(name) VALUES (?)", (category,))
                        db.commit()
                        c = db.execute("SELECT id FROM categories WHERE name=?", (category,)).fetchone()
                    cat_id = c["id"]
                db.execute("INSERT INTO products (name, category_id) VALUES (?,?)", (product_name, cat_id))
                db.commit()
                prow = db.execute("SELECT id FROM products WHERE name=?", (product_name,)).fetchone()
            product_id = prow["id"]

            # brand
            brand_id = None
            if brand:
                b = db.execute("SELECT id FROM brands WHERE name=?", (brand,)).fetchone()
                if not b:
                    db.execute("INSERT INTO brands(name) VALUES (?)", (brand,))
                    db.commit()
                    b = db.execute("SELECT id FROM brands WHERE name=?", (brand,)).fetchone()
                brand_id = b["id"]

            db.execute("""
                INSERT INTO skus (product_id, brand_id, barcode, is_active)
                VALUES (?,?,?,1)
            """, (product_id, brand_id, barcode))
            sku_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

            # atributos dinámicos
            codes  = request.form.getlist("attr_code[]")
            types  = request.form.getlist("attr_type[]")
            values = request.form.getlist("attr_value[]")
            units  = request.form.getlist("attr_unit[]")
            for i in range(len(codes)):
                code, type_, val, unit = codes[i], types[i], values[i], (units[i] or None)
                if not code or (val=="" and type_!="boolean"):
                    continue
                a = db.execute("SELECT id FROM attribute_def WHERE code=?", (code,)).fetchone()
                if not a:
                    ensure_attribute(db, code=code, label=code, type_="text")
                upsert_sku_attr(db, sku_id, code, val, unit_code=unit)

            # tags
            tags_csv = request.form.get("tags") or ""
            tags = [t.strip() for t in tags_csv.split(",") if t.strip()]
            if tags:
                set_sku_tags(db, sku_id, tags)

            # empaques
            levels = request.form.getlist("pkg_level[]")
            labels = request.form.getlist("pkg_label[]")
            units_ = request.form.getlist("pkg_units[]")
            sellab = request.form.getlist("pkg_sellable[]")
            purcha = request.form.getlist("pkg_purchasable[]")
            mults  = request.form.getlist("pkg_min_mult[]")
            excpt  = request.form.getlist("pkg_exception[]")

            for i in range(len(levels)):
                lvl = levels[i]
                db.execute("""
                  INSERT INTO packaging (sku_id, level, label, units_per_parent, is_sellable, is_purchasable, min_sell_multiple, exception_type)
                  VALUES (?,?,?,?,?,?,?,?)
                """, (sku_id,
                      lvl,
                      labels[i] or None,
                      int(units_[i]) if units_[i] else None,
                      1 if (sellab[i]=="1") else 0,
                      1 if (purcha[i]=="1") else 0,
                      int(mults[i]) if mults[i] else 1,
                      excpt[i] or None))

            validate_packaging_rules(db, sku_id)
            validate_attribute_rules(db, sku_id)

            db.execute("COMMIT")
            flash("SKU creado correctamente.", "success")
            return redirect(url_for("detail.sku_nuevo"))
        except Exception as e:
            db.execute("ROLLBACK")
            flash(f"Error guardando SKU: {e}", "danger")

    uoms = db.execute("SELECT code FROM uom ORDER BY code").fetchall()
    cats = db.execute("SELECT name FROM categories ORDER BY name").fetchall()
    brands = db.execute("SELECT name FROM brands ORDER BY name").fetchall()
    attrs = db.execute("SELECT * FROM attribute_def ORDER BY code").fetchall()
    return render_template("sku_nuevo.html", uoms=uoms, cats=cats, brands=brands, attrs=attrs)

# ========== Compras ==========
@bp.route("/compras/nueva", methods=["GET","POST"])
def compras_nueva():
    db = db_conn()
    if request.method == "POST":
        try:
            db.execute("BEGIN")
            ts_iso   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            supplier = request.form.get("supplier") or None

            sku_id  = int(request.form["sku_id"])
            lvl     = request.form["packaging_level"]  # UNIT/PACK/CASE/BUNDLE
            qty_p   = float(request.form["qty_packs"])
            cost_un = float(request.form["unit_cost"]) # costo por UN base

            is_mixed = (request.form.get("is_mixed") == "1")
            lines = []

            if is_mixed:
                child_ids = request.form.getlist("child_sku_id[]")
                child_qty = request.form.getlist("child_qty_units[]")
                for i in range(len(child_ids)):
                    csku = int(child_ids[i])
                    cun  = int(child_qty[i]) * int(qty_p)
                    lines.append({
                        "sku_id": csku, "qty_units": cun,
                        "unit_cost": cost_un, "packaging_level": lvl, "qty_packs": qty_p
                    })
            else:
                qty_units = to_units(db, sku_id, lvl, qty_p)
                lines.append({
                    "sku_id": sku_id, "qty_units": qty_units,
                    "unit_cost": cost_un, "packaging_level": lvl, "qty_packs": qty_p
                })

            record_purchase(db, ts_iso=ts_iso, supplier=supplier, lines=lines, note=("Caja mixta" if is_mixed else None))
            db.execute("COMMIT")
            flash("Compra registrada correctamente.", "success")
            return redirect(url_for("detail.compras_nueva"))
        except Exception as e:
            db.execute("ROLLBACK")
            flash(f"Error registrando compra: {e}", "danger")

    skus = db.execute("""
        SELECT sk.id,
               p.name||' - '||IFNULL(b.name,'')||' '||
               COALESCE(CASE WHEN sk.size_value IS NOT NULL THEN (sk.size_value||IFNULL(u.code,'')) END,'')||' '||
               IFNULL(sk.color_scent,'')||' '||IFNULL(sk.size_text,'') AS label
        FROM skus sk
        JOIN products p ON p.id=sk.product_id
        LEFT JOIN brands b ON b.id=sk.brand_id
        LEFT JOIN uom u ON u.id=sk.size_uom_id
        WHERE sk.is_active=1
        ORDER BY p.name, b.name
    """).fetchall()
    return render_template("compras_nueva.html", skus=skus)

# ========== Ventas ==========
@bp.route("/ventas/nueva", methods=["GET","POST"])
def ventas_nueva():
    db = db_conn()
    if request.method == "POST":
        try:
            db.execute("BEGIN")
            ts_iso   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            customer = request.form.get("customer") or None

            sku_id   = int(request.form["sku_id"])
            lvl      = request.form["packaging_level"]
            qty_p    = float(request.form["qty_packs"])
            precio_total = float(request.form["precio_total"])

            lines = []
            use_bundle = (request.form.get("use_bundle") == "1")
            bundle_packaging_id = request.form.get("bundle_packaging_id")

            if use_bundle and bundle_packaging_id:
                bundle_packaging_id = int(bundle_packaging_id)
                comps = expand_mixed_components(db, bundle_packaging_id, qty_p)
                total_units = sum(q for _, q in comps)
                precio_un = precio_total / max(total_units, 1)
                for csku, cun in comps:
                    lines.append({
                        "sku_id": csku, "qty_units": cun,
                        "price_per_un": precio_un, "packaging_level": "BUNDLE", "qty_packs": qty_p
                    })
            else:
                qty_units = to_units(db, sku_id, lvl, qty_p)
                precio_un = precio_total / max(qty_units, 1)
                lines.append({
                    "sku_id": sku_id, "qty_units": qty_units,
                    "price_per_un": precio_un, "packaging_level": lvl, "qty_packs": qty_p
                })

            record_sale(db, ts_iso=ts_iso, customer=customer, lines=lines)
            db.execute("COMMIT")
            flash("Venta registrada correctamente.", "success")
            return redirect(url_for("detail.ventas_nueva"))
        except Exception as e:
            db.execute("ROLLBACK")
            flash(f"Error registrando venta: {e}", "danger")

    skus = db.execute("""
        SELECT sk.id,
               p.name||' - '||IFNULL(b.name,'')||' '||
               COALESCE(CASE WHEN sk.size_value IS NOT NULL THEN (sk.size_value||IFNULL(u.code,'')) END,'')||' '||
               IFNULL(sk.color_scent,'')||' '||IFNULL(sk.size_text,'') AS label
        FROM skus sk
        JOIN products p ON p.id=sk.product_id
        LEFT JOIN brands b ON b.id=sk.brand_id
        LEFT JOIN uom u ON u.id=sk.size_uom_id
        WHERE sk.is_active=1
        ORDER BY p.name, b.name
    """).fetchall()

    bundles = db.execute("""
        SELECT pk.id AS packaging_id,
               sk.id AS sku_id,
               p.name||' '||IFNULL(b.name,'')||' - '||COALESCE(pk.label,'BUNDLE') AS label
        FROM packaging pk
        JOIN skus sk ON sk.id=pk.sku_id
        JOIN products p ON p.id=sk.product_id
        LEFT JOIN brands b ON b.id=sk.brand_id
        WHERE pk.level='BUNDLE'
        ORDER BY p.name, b.name, pk.label
    """).fetchall()

    return render_template("ventas_nueva.html", skus=skus, bundles=bundles)
