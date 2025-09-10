# app/routes.py
from datetime import date, datetime, timedelta
from io import StringIO
import csv
import sqlite3
from sqlite3 import IntegrityError
import random

from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, abort
from flask_login import login_user, logout_user, current_user, login_required
from werkzeug.security import check_password_hash

from .db import get_db
from .user import User

bp = Blueprint("main", __name__)

# ---------- Helpers ----------
def _table_columns(db, table_name: str):
    rows = db.execute(f"PRAGMA table_info({table_name})").fetchall()
    cols = []
    for r in rows:
        try:
            cols.append(r["name"])
        except Exception:
            cols.append(r[1])
    return cols

def _row_keys(row):
    try:
        return set(row.keys())
    except Exception:
        return set()

def _row_get(row, col, default=None):
    try:
        return row[col] if col in _row_keys(row) else default
    except Exception:
        return default

def _safe_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default

def _safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

def _gen_codigo_unico(db):
    while True:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        r3 = random.randint(100, 999)
        codigo = f"P{ts}-{r3}"
        row = db.execute("SELECT 1 FROM productos WHERE codigo = ?", (codigo,)).fetchone()
        if not row:
            return codigo

# --- Helpers para reposiciones vinculadas a un gasto ---
def _ensure_reposiciones_extra_cols(db):
    """Añade columnas opcionales si no existen: total_compra (REAL), gasto_rowid (INTEGER)."""
    cols = _table_columns(db, "reposiciones")
    try:
        if "total_compra" not in cols:
            db.execute("ALTER TABLE reposiciones ADD COLUMN total_compra REAL")
        if "gasto_rowid" not in cols:
            db.execute("ALTER TABLE reposiciones ADD COLUMN gasto_rowid INTEGER")
        db.commit()
    except sqlite3.OperationalError:
        pass  # si ya existen/no se puede alterar, continuar

def _sum_asignado_a_gasto(db, gasto_rid: int) -> float:
    _ensure_reposiciones_extra_cols(db)
    row = db.execute(
        "SELECT COALESCE(SUM(total_compra),0) AS s FROM reposiciones WHERE gasto_rowid=?",
        (gasto_rid,)
    ).fetchone()
    return float(row["s"] or 0.0)

# ---------- HOME ----------
@bp.route("/")
@login_required
def home():
    db = get_db()
    tv_row = db.execute("SELECT COALESCE(SUM(total),0) AS s FROM ventas").fetchone()
    tg_row = db.execute("SELECT COALESCE(SUM(monto),0) AS s FROM gastos").fetchone()
    total_ventas = float(tv_row["s"] if tv_row and tv_row["s"] is not None else 0)
    total_gastos = float(tg_row["s"] if tg_row and tg_row["s"] is not None else 0)
    ganancia_neta = total_ventas - total_gastos

    ventas_rows = db.execute("SELECT fecha FROM ventas LIMIT 1000").fetchall()
    gastos_rows = db.execute("SELECT fecha FROM gastos LIMIT 1000").fetchall()

    hoy = date.today().isoformat()
    return render_template(
        "inicio.html",
        total_ventas=round(total_ventas, 2),
        total_gastos=round(total_gastos, 2),
        ganancia_neta=round(ganancia_neta, 2),
        ventas=ventas_rows,
        gastos=gastos_rows,
        rango_label="Hoy",
        desde=hoy,
        hasta=hoy,
    )

# ---------- AUTH ----------
@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))

    if request.method == "POST":
        user_input = (request.form.get("email") or request.form.get("username") or "").strip().lower()
        password = request.form.get("password", "")

        db = get_db()
        row = db.execute(
            """
            SELECT id, email, nombre, pass_hash
            FROM usuarios
            WHERE lower(email)=? OR lower(nombre)=?
            """,
            (user_input, user_input),
        ).fetchone()

        if row and check_password_hash(row["pass_hash"], password):
            user = User(row["id"], row["email"], row["nombre"])
            login_user(user)
            next_url = request.args.get("next") or url_for("main.home")
            return redirect(next_url)

        flash("Credenciales inválidas", "error")

    return render_template("login.html")

@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.login"))

# ---------- INVENTARIO: listado ----------
@bp.route("/inventario")
@login_required
def inventario():
    db = get_db()

    q = (request.args.get("q") or "").strip()
    try:
        umbral = int(request.args.get("umbral", 5))
    except ValueError:
        umbral = 5
    solo_bajo = 1 if request.args.get("solo_bajo") else 0

    # Traemos también tamaño/variante (opcionales)
    base_sql = """
      SELECT
        id,
        nombre,
        categoria,
        precio,
        cantidad,
        proveedor,
        codigo,
        fecha,
        COALESCE(tamanio_valor, NULL) AS tamanio_valor,
        COALESCE(tamanio_uom, '')     AS tamanio_uom,
        COALESCE(variante, '')        AS variante
      FROM productos
    """
    where = []
    params = []
    if q:
        where.append("(LOWER(nombre) LIKE ? OR LOWER(categoria) LIKE ? OR LOWER(codigo) LIKE ? OR LOWER(variante) LIKE ?)")
        like = f"%{q.lower()}%"
        params += [like, like, like, like]
    if where:
        base_sql += " WHERE " + " AND ".join(where)
    base_sql += " ORDER BY nombre"

    productos = db.execute(base_sql, params).fetchall()

    def cant(row):
        try:
            return int(row["cantidad"] or 0)
        except Exception:
            return 0

    low_items = [p for p in productos if cant(p) <= umbral]
    low_count = len(low_items)

    if solo_bajo:
        productos = low_items

    return render_template(
        "index.html",
        productos=productos,
        low_items=low_items,
        low_count=low_count,
        umbral=umbral,
        q=q,
        solo_bajo=solo_bajo,
    )

@bp.route("/actualizar-umbral", methods=["POST"])
@login_required
def actualizar_umbral():
    try:
        umbral = int(request.form.get("umbral", 5))
    except ValueError:
        umbral = 5
    q = request.args.get("q")
    solo_bajo = request.args.get("solo_bajo")
    return redirect(url_for("main.inventario", umbral=umbral, q=q, solo_bajo=solo_bajo))

# ---------- INVENTARIO: crear ----------
@bp.route("/agregar", methods=["POST"])
@login_required
def agregar():
    db = get_db()
    cols = _table_columns(db, "productos")

    nombre    = (request.form.get("nombre") or "").strip()
    categoria = (request.form.get("categoria") or "").strip()
    # Nuevos campos (opcionales)
    tamanio_valor = request.form.get("tamanio_valor", "").strip()
    tamanio_uom   = (request.form.get("tamanio_uom") or "").strip().upper()
    variante      = (request.form.get("variante") or "").strip()

    precio   = _safe_float(request.form.get("precio"), 0.0)
    cantidad = _safe_int(request.form.get("cantidad"), 0)
    proveedor= (request.form.get("proveedor") or "").strip()
    codigo_in= (request.form.get("codigo") or "").strip()
    fecha    = (request.form.get("fecha") or date.today().isoformat())

    if not nombre:
        flash("El nombre es obligatorio", "error")
        return redirect(url_for("main.inventario"))

    # Resolver 'codigo' evitando ''
    codigo = None
    if "codigo" in cols:
        if codigo_in == "":
            codigo = _gen_codigo_unico(db)
        else:
            dup = db.execute("SELECT 1 FROM productos WHERE codigo = ?", (codigo_in,)).fetchone()
            if dup:
                flash("El código ya existe. Usa otro o déjalo vacío para auto-generar.", "error")
                return redirect(url_for("main.inventario"))
            codigo = codigo_in

    payload = {
        "nombre": nombre,
        "categoria": categoria,
        "precio": precio,
        "cantidad": cantidad,
        "proveedor": proveedor,
        "fecha": fecha,
    }
    if "codigo" in cols:
        payload["codigo"] = codigo

    # opcionales legacy
    opt_precio_paquete = request.form.get("precio_paquete")
    opt_unid_paquete   = request.form.get("unidades_por_paquete")

    insert_cols = []
    insert_vals = []
    for k, v in payload.items():
        if k in cols:
            insert_cols.append(k)
            insert_vals.append(v)

    # NUEVOS: tamaño + uom + variante (solo si existen en esquema)
    if "tamanio_valor" in cols and tamanio_valor not in ("", None):
        insert_cols.append("tamanio_valor")
        insert_vals.append(_safe_float(tamanio_valor, 0.0))
    if "tamanio_uom" in cols and tamanio_uom not in ("", None):
        insert_cols.append("tamanio_uom")
        insert_vals.append(tamanio_uom)
    if "variante" in cols and variante not in ("", None):
        insert_cols.append("variante")
        insert_vals.append(variante)

    # opcionales legacy (si existen en esquema)
    if "precio_paquete" in cols and opt_precio_paquete not in (None, ""):
        insert_cols.append("precio_paquete")
        insert_vals.append(_safe_float(opt_precio_paquete, 0.0))
    if "unidades_por_paquete" in cols and opt_unid_paquete not in (None, ""):
        insert_cols.append("unidades_por_paquete")
        insert_vals.append(_safe_int(opt_unid_paquete, 0))

    if not insert_cols:
        flash("No se pudo determinar columnas para insertar en productos.", "error")
        return redirect(url_for("main.inventario"))

    placeholders = ", ".join(["?"] * len(insert_cols))
    sql = f"INSERT INTO productos ({', '.join(insert_cols)}) VALUES ({placeholders})"

    try:
        db.execute(sql, insert_vals)
        db.commit()
        flash("✅ Producto agregado correctamente", "success")
    except sqlite3.IntegrityError as e:
        db.rollback()
        if "codigo" in (cols or []) and "UNIQUE constraint failed" in str(e) and codigo_in == "":
            try:
                nuevo_codigo = _gen_codigo_unico(db)
                idx = insert_cols.index("codigo")
                insert_vals[idx] = nuevo_codigo
                db.execute(sql, insert_vals)
                db.commit()
                flash(f"✅ Producto agregado (código auto: {nuevo_codigo})", "success")
            except Exception as e2:
                db.rollback()
                flash(f"Error al autogenerar código: {e2}", "error")
        else:
            flash(f"Error de integridad al guardar: {e}", "error")
    except sqlite3.Error as e:
        db.rollback()
        flash(f"Error al guardar en BD: {e}", "error")

    return redirect(url_for("main.inventario"))

# ---------- INVENTARIO: editar/eliminar ----------
@bp.route("/producto/<int:pid>/editar", methods=["GET", "POST"])
@login_required
def editar_producto(pid):
    db = get_db()
    if request.method == "GET":
        row = db.execute("SELECT * FROM productos WHERE id=?", (pid,)).fetchone()
        if not row:
            abort(404)
        return render_template("editar_producto.html", p=row)

    cols = _table_columns(db, "productos")

    # Validación 'codigo' único si lo modifica
    codigo_form = request.form.get("codigo", None)
    if ("codigo" in cols) and (codigo_form is not None):
        codigo_norm = codigo_form.strip()
        if codigo_norm != "":
            dup = db.execute(
                "SELECT id FROM productos WHERE codigo=? AND id<>?",
                (codigo_norm, pid),
            ).fetchone()
            if dup:
                flash("El código indicado ya existe en otro producto.", "error")
                return redirect(url_for("main.editar_producto", pid=pid))

    # Campos editables
    fields = {
        "nombre": request.form.get("nombre", "").strip(),
        "categoria": request.form.get("categoria", "").strip(),

        # NUEVOS
        "tamanio_valor": request.form.get("tamanio_valor", ""),
        "tamanio_uom": (request.form.get("tamanio_uom") or "").strip().upper(),
        "variante": request.form.get("variante", "").strip(),

        "precio": request.form.get("precio", ""),
        "cantidad": request.form.get("cantidad", ""),
        "proveedor": request.form.get("proveedor", "").strip(),
        "codigo": request.form.get("codigo", None),
        "fecha": request.form.get("fecha", "").strip(),
        "precio_paquete": request.form.get("precio_paquete", ""),
        "unidades_por_paquete": request.form.get("unidades_por_paquete", ""),
    }

    set_parts = []
    values = []
    for k, v in fields.items():
        if k not in cols:
            continue

        if k == "codigo":
            if v is None:
                continue
            v = v.strip()
            values.append(v if v != "" else None)
            set_parts.append("codigo=?")
            continue

        if v == "":
            continue

        if k in ("precio", "precio_paquete", "tamanio_valor"):
            values.append(_safe_float(v, 0.0))
        elif k in ("cantidad", "unidades_por_paquete"):
            values.append(_safe_int(v, 0))
        else:
            values.append(v)
        set_parts.append(f"{k}=?")

    if not set_parts:
        flash("No hay cambios para guardar.", "info")
        return redirect(url_for("main.inventario"))

    sql = f"UPDATE productos SET {', '.join(set_parts)} WHERE id=?"
    values.append(pid)
    try:
        db.execute(sql, values)
        db.commit()
        flash("Producto actualizado", "success")
    except sqlite3.Error as e:
        flash(f"Error al actualizar: {e}", "error")

    return redirect(url_for("main.inventario"))

@bp.route("/producto/<int:pid>/eliminar", methods=["POST"])
@login_required
def eliminar_producto(pid):
    db = get_db()
    try:
        db.execute("DELETE FROM productos WHERE id=?", (pid,))
        db.commit()
        flash("Producto eliminado", "success")
    except sqlite3.Error as e:
        flash(f"Error al eliminar: {e}", "error")
    return redirect(url_for("main.inventario"))

# ---------- FINANZAS: Formulario de VENTA ----------
@bp.route("/fin/venta/nueva", methods=["GET"])
@login_required
def fin_venta_form():
    db = get_db()
    rows = db.execute("SELECT * FROM productos ORDER BY nombre").fetchall()
    productos = []
    for r in rows:
        nombre = _row_get(r, "nombre", "")
        precio_unit = _safe_float(_row_get(r, "precio", 0.0), 0.0)
        stock = _safe_int(_row_get(r, "cantidad", 0), 0)
        precio_pack = _safe_float(_row_get(r, "precio_paquete", 0.0), 0.0)
        unid_pack = _safe_int(_row_get(r, "unidades_por_paquete", 1), 1)
        productos.append((nombre, precio_unit, stock, precio_pack, unid_pack))
    return render_template("fin_venta_form.html", productos=productos)

@bp.route("/registrar_venta", methods=["POST"])
@login_required
def registrar_venta():
    db = get_db()
    producto = (request.form.get("producto") or "").strip()
    modo = (request.form.get("modo") or "unidad").strip()  # "unidad" | "paquete"
    cantidad = request.form.get("cantidad", "0").strip()
    precio_unit = request.form.get("precio_unit", "0").strip()
    total = request.form.get("total", "0").strip()

    try:
        cantidad = int(cantidad)
        precio_unit = float(precio_unit)
        total = float(total)
    except Exception:
        flash("Datos numéricos inválidos.", "error")
        return redirect(url_for("main.fin_venta_form"))

    if not producto or cantidad <= 0 or precio_unit < 0 or total < 0:
        flash("Completa correctamente el formulario de venta.", "error")
        return redirect(url_for("main.fin_venta_form"))

    prod = db.execute("SELECT * FROM productos WHERE nombre = ?", (producto,)).fetchone()
    if not prod:
        flash("Producto no encontrado.", "error")
        return redirect(url_for("main.fin_venta_form"))

    stock_actual = _safe_int(_row_get(prod, "cantidad", 0), 0)
    unidades_por_paquete = _safe_int(_row_get(prod, "unidades_por_paquete", 1), 1)
    if unidades_por_paquete <= 0:
        unidades_por_paquete = 1

    unidades = cantidad if modo == "unidad" else (cantidad * unidades_por_paquete)

    if unidades <= 0:
        flash("Configuración de paquete inválida para este producto.", "error")
        return redirect(url_for("main.fin_venta_form"))
    if unidades > stock_actual:
        flash(f"Stock insuficiente. Stock actual: {stock_actual} unidades.", "error")
        return redirect(url_for("main.fin_venta_form"))

    try:
        db.execute("""
            INSERT INTO ventas (fecha, producto, cantidad, precio_unit, total)
            VALUES (DATE('now','localtime'), ?, ?, ?, ?)
        """, (producto, cantidad, precio_unit, total))
        db.execute("""
            UPDATE productos
            SET cantidad = cantidad - ?
            WHERE nombre = ?
        """, (unidades, producto))
        db.commit()
        flash("Venta registrada correctamente.", "success")
    except IntegrityError as e:
        db.rollback()
        flash(f"Error de integridad: {e}", "error")
    except Exception as e:
        db.rollback()
        flash(f"Error al registrar la venta: {e}", "error")

    return redirect(url_for("main.fin_ventas"))

# ---------- FINANZAS: Panel ----------
@bp.route("/fin")
@login_required
def fin_panel():
    db = get_db()

    r = (request.args.get("r") or "todo").strip()
    desde_arg = (request.args.get("desde") or "").strip()
    hasta_arg = (request.args.get("hasta") or "").strip()

    hoy = date.today()
    desde, hasta, rango_label = None, None, "Todo"
    if r == "hoy":
        desde = hoy.isoformat(); hasta = hoy.isoformat(); rango_label = "Hoy"
    elif r == "semana":
        d1 = hoy - timedelta(days=6); desde = d1.isoformat(); hasta = hoy.isoformat(); rango_label = "Últimos 7 días"
    elif r == "mes":
        d1 = hoy.replace(day=1)
        dm = (date(d1.year + 1, 1, 1) - timedelta(days=1)) if d1.month == 12 else (date(d1.year, d1.month + 1, 1) - timedelta(days=1))
        desde = d1.isoformat(); hasta = dm.isoformat(); rango_label = "Mes actual"
    elif r == "personalizado":
        try: d1 = datetime.strptime(desde_arg, "%Y-%m-%d").date()
        except Exception: d1 = hoy
        try: d2 = datetime.strptime(hasta_arg, "%Y-%m-%d").date()
        except Exception: d2 = hoy
        if d2 < d1: d2 = d1
        desde = d1.isoformat(); hasta = d2.isoformat(); rango_label = "Personalizado"
    else:
        r = "todo"; rango_label = "Todo"

    # Totales
    if r == "todo":
        tv_row = db.execute("SELECT COALESCE(SUM(total),0) AS s FROM ventas").fetchone()
        tg_row = db.execute("SELECT COALESCE(SUM(monto),0) AS s FROM gastos").fetchone()
    else:
        tv_row = db.execute("SELECT COALESCE(SUM(total),0) AS s FROM ventas WHERE fecha BETWEEN ? AND ?", (desde, hasta)).fetchone()
        tg_row = db.execute("SELECT COALESCE(SUM(monto),0) AS s FROM gastos WHERE fecha BETWEEN ? AND ?", (desde, hasta)).fetchone()

    total_ventas = float(tv_row["s"] if tv_row and tv_row["s"] is not None else 0.0)
    total_gastos = float(tg_row["s"] if tg_row and tg_row["s"] is not None else 0.0)
    ganancia_neta = total_ventas - total_gastos

    # Serie por día
    if r == "todo":
        rows_vd = db.execute("""
            SELECT fecha, COALESCE(SUM(total),0) AS s
            FROM ventas
            GROUP BY fecha
            ORDER BY fecha
        """).fetchall()
    else:
        rows_vd = db.execute("""
            SELECT fecha, COALESCE(SUM(total),0) AS s
            FROM ventas
            WHERE fecha BETWEEN ? AND ?
            GROUP BY fecha
            ORDER BY fecha
        """, (desde, hasta)).fetchall()
    ventas_labels = [str(row["fecha"]) for row in rows_vd]
    ventas_values = [float(row["s"] or 0) for row in rows_vd]

    # ---------- TOP productos (Nombre + Tamaño + Variante + [#ID]) ----------
    prod_cols = _table_columns(db, "productos")
    has_size = ("tamanio_valor" in prod_cols and "tamanio_uom" in prod_cols)
    has_var  = ("variante" in prod_cols)

    size_part = (
        "CASE WHEN p.id IS NOT NULL "
        "AND p.tamanio_valor IS NOT NULL AND p.tamanio_valor<>0 "
        "AND p.tamanio_uom IS NOT NULL AND p.tamanio_uom<>'' "
        "THEN ' '||CAST(p.tamanio_valor AS TEXT)||' '||p.tamanio_uom ELSE '' END"
        if has_size else "''"
    )
    var_part = (
        "CASE WHEN p.id IS NOT NULL "
        "AND p.variante IS NOT NULL AND p.variante<>'' "
        "THEN ' ('||p.variante||')' ELSE '' END"
        if has_var else "''"
    )
    id_part = "CASE WHEN p.id IS NOT NULL THEN ' [#'||CAST(p.id AS TEXT)||']' ELSE '' END"

    label_sql = (
        f"CASE WHEN p.id IS NOT NULL THEN "
        f"  p.nombre || {size_part} || {var_part} || {id_part} "
        f"ELSE v.producto || ' [sin ID]' END"
    )

    where = "" if r == "todo" else "WHERE v.fecha BETWEEN ? AND ?"
    params = () if r == "todo" else (desde, hasta)
    rows_top = db.execute(f"""
        SELECT
          {label_sql} AS label,
          COALESCE(SUM(v.cantidad),0) AS cant
        FROM ventas v
        LEFT JOIN productos p ON LOWER(TRIM(p.nombre)) = LOWER(TRIM(v.producto))
        {where}
        GROUP BY label
        ORDER BY cant DESC
        LIMIT 5
    """, params).fetchall()

    top_labels = [str(rt["label"]) for rt in rows_top]
    top_values = [float(rt["cant"] or 0) for rt in rows_top]

    # Salida
    desde_out = desde or hoy.isoformat()
    hasta_out = hasta or hoy.isoformat()
    return render_template(
        "fin_panel.html",
        r=r,
        desde=desde_out,
        hasta=hasta_out,
        rango_label=rango_label,
        total_ventas=round(total_ventas, 2),
        total_gastos=round(total_gastos, 2),
        ganancia_neta=round(ganancia_neta, 2),
        ventas_labels=ventas_labels or [],
        ventas_values=ventas_values or [],
        top_labels=top_labels or [],
        top_values=top_values or [],
    )

# ---------- LISTAS / FORMULARIOS FINANZAS ----------
@bp.route("/fin/ventas", methods=["GET"], endpoint="fin_ventas")
@login_required
def fin_ventas():
    db = get_db()
    rows = db.execute(
        "SELECT fecha, producto, cantidad, precio_unit, total FROM ventas ORDER BY fecha DESC"
    ).fetchall()
    return render_template(
        "fin_ventas_lista.html",
        ventas=rows,
        r=request.args.get("r", "hoy"),
        desde=request.args.get("desde", ""),
        hasta=request.args.get("hasta", ""),
        rango_label="Hoy",
    )

@bp.route("/fin/gastos", methods=["GET"], endpoint="fin_gastos")
@login_required
def fin_gastos():
    db = get_db()
    # 🔁 Trae rowid para links (conciliación / CSV)
    rows = db.execute(
        "SELECT rowid, fecha, motivo, monto FROM gastos ORDER BY fecha DESC"
    ).fetchall()
    return render_template(
        "fin_gastos_lista.html",
        gastos=rows,
        r=request.args.get("r", "hoy"),
        desde=request.args.get("desde", ""),
        hasta=request.args.get("hasta", ""),
        rango_label="Hoy",
    )

# ---------- REPORTES REPOSICIONES ----------
@bp.route("/reportes/reposiciones")
@login_required
def reportes_reposiciones():
    """
    Lista las reposiciones con filtros y muestra productos para el selector.
    El template itera:  {% for f, nombre, codigo, cat, cant, costo, ref in rows %}
    """
    db = get_db()

    r = (request.args.get("r") or "todo").strip()
    desde_arg = (request.args.get("desde") or "").strip()
    hasta_arg = (request.args.get("hasta") or "").strip()
    producto_id = (request.args.get("producto_id") or "").strip()
    origen = (request.args.get("origen") or "").strip()

    hoy = date.today()
    desde, hasta, rango_label = None, None, "Todo"
    if r == "hoy":
        desde = hoy.isoformat(); hasta = hoy.isoformat(); rango_label = "Hoy"
    elif r == "semana":
        d1 = hoy - timedelta(days=6)
        desde = d1.isoformat(); hasta = hoy.isoformat(); rango_label = "Últimos 7 días"
    elif r == "mes":
        d1 = hoy.replace(day=1)
        dm = (date(d1.year + 1, 1, 1) - timedelta(days=1)) if d1.month == 12 else (date(d1.year, d1.month + 1, 1) - timedelta(days=1))
        desde = d1.isoformat(); hasta = dm.isoformat(); rango_label = "Mes actual"
    elif r == "personalizado":
        try: d1 = datetime.strptime(desde_arg, "%Y-%m-%d").date()
        except Exception: d1 = hoy
        try: d2 = datetime.strptime(hasta_arg, "%Y-%m-%d").date()
        except Exception: d2 = hoy
        if d2 < d1: d2 = d1
        desde = d1.isoformat(); hasta = d2.isoformat(); rango_label = "Personalizado"
    else:
        r = "todo"; rango_label = "Todo"

    base_sql = """
        SELECT
            r.fecha                 AS f,
            r.producto              AS nombre,
            COALESCE(p.codigo,'')   AS codigo,
            COALESCE(p.categoria,'')AS cat,
            r.cantidad              AS cant,
            r.costo_unit            AS costo,
            r.ref                   AS ref
        FROM reposiciones r
        LEFT JOIN productos p ON p.nombre = r.producto
    """
    where, params = [], []
    if r != "todo":
        where.append("r.fecha BETWEEN ? AND ?"); params += [desde, hasta]
    if producto_id:
        where.append("r.producto = ?"); params.append(producto_id)
    if origen:
        where.append("r.ref = ?"); params.append(origen)
    if where:
        base_sql += " WHERE " + " AND ".join(where)
    base_sql += " ORDER BY r.fecha DESC"

    rows = db.execute(base_sql, params).fetchall()

    prod_rows = db.execute("SELECT DISTINCT nombre FROM productos ORDER BY nombre").fetchall()
    if prod_rows:
        productos = [(r["nombre"], r["nombre"]) for r in prod_rows]
    else:
        alt_rows = db.execute("SELECT DISTINCT producto AS nombre FROM reposiciones ORDER BY producto").fetchall()
        productos = [(r["nombre"], r["nombre"]) for r in alt_rows]

    desde_out = desde or hoy.isoformat()
    hasta_out = hasta or hoy.isoformat()

    return render_template(
        "reportes_reposiciones.html",
        rows=rows,
        productos=productos,
        r=r,
        desde=desde_out,
        hasta=hasta_out,
        producto_id=producto_id,
        origen=origen,
        rango_label=rango_label,
    )

# ---------- ADMIN ----------
@bp.route("/admin")
@login_required
def admin():
    db = get_db()
    all_tables = [
        r["name"]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    tablas = sorted(all_tables, key=lambda x: (x != "productos", x))

    tabla = request.args.get("tabla") or (tablas[0] if tablas else "")
    if tabla not in tablas:
        tabla = tablas[0] if tablas else ""

    page_size = _safe_int(request.args.get("page_size"), 20)
    page = max(1, _safe_int(request.args.get("page"), 1))
    offset = (page - 1) * page_size

    cols = _table_columns(db, tabla) if tabla else []
    total = 0
    rows = []
    if tabla:
        total_row = db.execute(f"SELECT COUNT(*) AS c FROM {tabla}").fetchone()
        total = int(total_row["c"] if total_row and total_row["c"] is not None else 0)
        rows = db.execute(
            f"SELECT * FROM {tabla} LIMIT ? OFFSET ?", (page_size, offset)
        ).fetchall()

    return render_template(
        "admin.html",
        tablas=tablas,
        tabla=tabla,
        cols=cols,
        rows=rows,
        total=total,
        page_size=page_size,
        page=page,
        base_url=url_for("main.admin"),
    )

# ---------- EXPORTS CSV ----------
@bp.route("/export/ventas.csv", methods=["GET"], endpoint="export_ventas_filtrado")
@login_required
def export_ventas_filtrado():
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    db = get_db()
    sql = "SELECT fecha, producto, cantidad, precio_unit, total FROM ventas"
    params = []
    where = []
    if desde:
        where.append("fecha >= ?"); params.append(desde)
    if hasta:
        where.append("fecha <= ?"); params.append(hasta)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY fecha DESC"
    rows = db.execute(sql, params).fetchall()

    si = StringIO(); cw = csv.writer(si)
    cw.writerow(["fecha", "producto", "cantidad", "precio_unit", "total"])
    for r in rows:
        cw.writerow([r["fecha"], r["producto"], r["cantidad"], r["precio_unit"], r["total"]])

    return Response(si.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=ventas.csv"})

@bp.route("/export/gastos.csv", methods=["GET"], endpoint="export_gastos_filtrado")
@login_required
def export_gastos_filtrado():
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    db = get_db()
    sql = "SELECT fecha, motivo, monto FROM gastos"
    params = []
    where = []
    if desde:
        where.append("fecha >= ?"); params.append(desde)
    if hasta:
        where.append("fecha <= ?"); params.append(hasta)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY fecha DESC"
    rows = db.execute(sql, params).fetchall()

    si = StringIO(); cw = csv.writer(si)
    cw.writerow(["fecha", "motivo", "monto"])
    for r in rows:
        cw.writerow([r["fecha"], r["motivo"], r["monto"]])

    return Response(si.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=gastos.csv"})

@bp.route("/export/reposiciones.csv", methods=["GET"], endpoint="export_reposiciones_filtrado")
@login_required
def export_reposiciones_filtrado():
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    producto_id = request.args.get("producto_id")
    origen = request.args.get("origen")

    db = get_db()
    sql = "SELECT fecha, producto, cantidad, costo_unit, proveedor, ref FROM reposiciones"
    params = []
    where = []
    if desde:
        where.append("fecha >= ?"); params.append(desde)
    if hasta:
        where.append("fecha <= ?"); params.append(hasta)
    if producto_id:
        where.append("producto = ?"); params.append(producto_id)
    if origen:
        where.append("ref = ?"); params.append(origen)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY fecha DESC"
    rows = db.execute(sql, params).fetchall()

    si = StringIO(); cw = csv.writer(si)
    cw.writerow(["fecha", "producto", "cantidad", "costo_unit", "proveedor", "ref"])
    for r in rows:
        cw.writerow([r["fecha"], r["producto"], r["cantidad"], r["costo_unit"], r["proveedor"], r["ref"]])

    return Response(si.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=reposiciones.csv"})

@bp.route("/export/productos.csv", methods=["GET"], endpoint="export_productos_csv")
@login_required
def export_productos_csv():
    db = get_db()
    cols = _table_columns(db, "productos")
    if not cols:
        return Response("No existe la tabla productos", status=404)

    q = (request.args.get("q") or "").strip().lower()
    sql = f"SELECT {', '.join(cols)} FROM productos"
    params = []
    if q:
        likes = []
        for c in ("nombre", "categoria", "codigo"):
            if c in cols:
                likes.append(f"LOWER({c}) LIKE ?")
                params.append(f"%{q}%")
        if likes:
            sql += " WHERE " + " OR ".join(likes)
    sql += " ORDER BY " + ("nombre" if "nombre" in cols else cols[0])

    rows = db.execute(sql, params).fetchall()

    si = StringIO(); cw = csv.writer(si)
    cw.writerow(cols)
    for r in rows:
        cw.writerow([r[c] for c in cols])

    return Response(si.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=productos.csv"})

# ---------- FINANZAS: Formulario y registro de GASTO ----------
@bp.route("/fin/gasto/nuevo", methods=["GET"])
@login_required
def fin_gasto_form():
    return render_template("fin_gasto_form.html")

@bp.route("/registrar_gasto", methods=["POST"])
@login_required
def registrar_gasto():
    db = get_db()
    motivo = (request.form.get("motivo") or "").strip()
    monto_s = (request.form.get("monto") or "0").strip()
    redir_repo = 1 if request.form.get("redir_repo") else 0  # checkbox opcional

    try:
        monto = float(monto_s)
    except Exception:
        flash("Monto inválido.", "error")
        return redirect(url_for("main.fin_gasto_form"))

    if not motivo or monto <= 0:
        flash("Complete motivo y monto (>0).", "error")
        return redirect(url_for("main.fin_gasto_form"))

    try:
        cur = db.execute(
            "INSERT INTO gastos (fecha, motivo, monto) VALUES (DATE('now','localtime'), ?, ?)",
            (motivo, monto),
        )
        db.commit()
        rid = cur.lastrowid
        flash("Gasto registrado correctamente.", "success")

        es_compra = ("compra" in motivo.lower()) or ("mayorista" in motivo.lower()) or redir_repo
        if rid and es_compra:
            return redirect(url_for("main.fin_reposicion_form", gasto=rid))

    except Exception as e:
        db.rollback()
        flash(f"Error al registrar gasto: {e}", "error")
        return redirect(url_for("main.fin_gasto_form"))

    return redirect(url_for("main.fin_gastos"))

# ---------- FINANZAS: Formulario y registro de REPOSICIÓN ----------
@bp.route("/fin/reposicion/nueva", methods=["GET"])
@login_required
def fin_reposicion_form():
    db = get_db()
    _ensure_reposiciones_extra_cols(db)

    # Lista de productos con etiqueta enriquecida (nombre + tamaño + variante)
    rows = db.execute("""
        SELECT
            nombre,
            COALESCE(proveedor,'') AS proveedor,
            COALESCE(tamanio_valor, NULL) AS tval,
            COALESCE(tamanio_uom, '')     AS tuom,
            COALESCE(variante,'')         AS variante
        FROM productos
        ORDER BY nombre
    """).fetchall()

    productos = []
    for r in rows:
        partes = [r["nombre"]]
        if r["tval"] is not None:
            try:
                # muestra 40 ML / 1 L / 80 G, etc.
                numtxt = f"{float(r['tval']):g}"
            except Exception:
                numtxt = str(r["tval"])
            if r["tuom"]:
                partes.append(f"{numtxt} {r['tuom']}")
        if r["variante"]:
            partes.append(f"({r['variante']})")
        label = " ".join(partes)
        productos.append((r["nombre"], label))  # value=nombre (tu backend trabaja por nombre)

    # ¿Vinculado a un gasto?
    gasto_param = (request.args.get("gasto") or "").strip()
    gasto = None
    asignado = 0.0
    restante = None
    if gasto_param.isdigit():
        gr = db.execute(
            "SELECT rowid AS rid, fecha, motivo, monto FROM gastos WHERE rowid=?",
            (int(gasto_param),)
        ).fetchone()
        if gr:
            gasto = gr
            asignado = _sum_asignado_a_gasto(db, gr["rid"])
            restante = float(gr["monto"] or 0.0) - asignado

    return render_template(
        "fin_reposicion_form.html",
        productos=productos,
        gasto=gasto,
        asignado=asignado,
        restante=restante,
    )

@bp.route("/registrar_reposicion", methods=["POST"])
@login_required
def registrar_reposicion():
    db = get_db()
    _ensure_reposiciones_extra_cols(db)

    producto    = (request.form.get("producto") or "").strip()
    cantidad_s  = (request.form.get("cantidad") or "0").strip()
    cu_s        = (request.form.get("costo_unit") or "").strip()     # opcional
    ct_s        = (request.form.get("costo_total") or "").strip()    # opcional
    proveedor   = (request.form.get("proveedor") or "").strip()
    ref         = (request.form.get("ref") or "compra").strip()
    gasto_rid_s = (request.form.get("gasto_rid") or "").strip()

    def _to_int(x, d=0):
        try: return int(x)
        except: return d
    def _to_float_pos(x):
        try:
            v = float(x)
            return v if v >= 0 else None
        except:
            return None

    cantidad       = _to_int(cantidad_s, 0)
    costo_unit_in  = _to_float_pos(cu_s)  # None si vacío
    costo_total_in = _to_float_pos(ct_s)  # None si vacío
    gasto_rid      = _to_int(gasto_rid_s, 0) if gasto_rid_s else 0

    if not producto:
        flash("Selecciona un producto.", "error")
        return redirect(url_for("main.fin_reposicion_form", gasto=gasto_rid) if gasto_rid else url_for("main.fin_reposicion_form"))
    if cantidad <= 0:
        flash("La cantidad debe ser > 0.", "error")
        return redirect(url_for("main.fin_reposicion_form", gasto=gasto_rid) if gasto_rid else url_for("main.fin_reposicion_form"))
    if (not costo_unit_in or costo_unit_in <= 0) and (not costo_total_in or costo_total_in <= 0):
        flash("Ingresa costo unitario o costo total (>0).", "error")
        return redirect(url_for("main.fin_reposicion_form", gasto=gasto_rid) if gasto_rid else url_for("main.fin_reposicion_form"))

    prod = db.execute("SELECT nombre FROM productos WHERE nombre=?", (producto,)).fetchone()
    if not prod:
        flash("Producto no existe.", "error")
        return redirect(url_for("main.fin_reposicion_form", gasto=gasto_rid) if gasto_rid else url_for("main.fin_reposicion_form"))

    # Calcula costo y total
    if costo_total_in and costo_total_in > 0:
        total_compra = round(costo_total_in, 2)
        costo_unit   = round(total_compra / cantidad, 4)
    else:
        costo_unit   = round(float(costo_unit_in), 4)
        total_compra = round(costo_unit * cantidad, 2)

    # 🧱 Bloqueo backend si excede el gasto vinculado
    if gasto_rid > 0:
        gr = db.execute("SELECT rowid AS rid, monto FROM gastos WHERE rowid=?", (gasto_rid,)).fetchone()
        if gr:
            asignado_actual = _sum_asignado_a_gasto(db, gasto_rid)
            restante = float(gr["monto"] or 0.0) - asignado_actual
            if total_compra - restante > 0.01:  # excede por más de 0.01 Bs
                flash(f"❌ Esta reposición ({total_compra:.2f} Bs) excede el restante del gasto ({restante:.2f} Bs). Ajusta el monto o usa otro gasto.", "error")
                return redirect(url_for("main.fin_reposicion_form", gasto=gasto_rid))

    try:
        # Inserta reposición
        cur = db.execute(
            """
            INSERT INTO reposiciones (fecha, producto, cantidad, costo_unit, proveedor, ref)
            VALUES (DATE('now','localtime'), ?, ?, ?, ?, ?)
            """,
            (producto, cantidad, costo_unit, proveedor, ref),
        )
        rid = cur.lastrowid

        # Stock +
        db.execute("UPDATE productos SET cantidad = cantidad + ? WHERE nombre = ?", (cantidad, producto))

        # Guarda total_compra y vinculación de gasto (si aplica)
        if rid:
            if gasto_rid > 0:
                db.execute(
                    "UPDATE reposiciones SET total_compra=?, gasto_rowid=? WHERE rowid=?",
                    (total_compra, gasto_rid, rid)
                )
            else:
                db.execute(
                    "UPDATE reposiciones SET total_compra=? WHERE rowid=?",
                    (total_compra, rid)
                )

        db.commit()

        # Si está vinculado a gasto, calcular progreso y decidir a dónde redirigir
        if gasto_rid > 0:
            gr = db.execute("SELECT rowid AS rid, monto FROM gastos WHERE rowid=?", (gasto_rid,)).fetchone()
            if gr:
                asignado = _sum_asignado_a_gasto(db, gasto_rid)
                meta     = float(gr["monto"] or 0.0)
                restante = round(meta - asignado, 2)
                if restante > 0.01:
                    flash(f"Reposición registrada. Asignado {asignado:.2f} / {meta:.2f} Bs. Falta {restante:.2f} Bs.", "info")
                    return redirect(url_for("main.fin_reposicion_form", gasto=gasto_rid))
                elif abs(restante) <= 0.01:
                    flash("¡Listo! El total de reposiciones ya iguala el gasto.", "success")
                    return redirect(url_for("main.reportes_reposiciones"))
                else:
                    flash(f"⚠ Te pasaste por {-restante:.2f} Bs respecto al gasto. Puedes ajustar con más líneas o editar luego.", "warning")
                    return redirect(url_for("main.fin_reposicion_form", gasto=gasto_rid))

        # Sin gasto vinculado: flujo normal
        flash(f"Reposición registrada (total {total_compra:.2f} Bs; unit {costo_unit:.4f} Bs/u).", "success")
        return redirect(url_for("main.reportes_reposiciones"))

    except Exception as e:
        db.rollback()
        flash(f"Error al registrar reposición: {e}", "error")
        return redirect(url_for("main.fin_reposicion_form", gasto=gasto_rid) if gasto_rid else url_for("main.fin_reposicion_form"))

# ---------- CONCILIACIÓN DE GASTO ----------
@bp.route("/fin/gasto/<int:rid>/conciliacion")
@login_required
def conciliacion_gasto(rid):
    db = get_db()
    gasto = db.execute("SELECT rowid AS rid, fecha, motivo, monto FROM gastos WHERE rowid=?", (rid,)).fetchone()
    if not gasto:
        abort(404)

    repos = db.execute("""
        SELECT r.rowid, r.producto, r.cantidad, r.costo_unit, r.total_compra
        FROM reposiciones r
        WHERE r.gasto_rowid=?
        ORDER BY r.rowid
    """, (rid,)).fetchall()

    asignado = sum([(r["total_compra"] or (r["cantidad"] * r["costo_unit"])) for r in repos])
    restante = gasto["monto"] - asignado

    return render_template("fin_conciliacion.html",
                           gasto=gasto, repos=repos,
                           asignado=asignado, restante=restante)

# ---------- EXPORTAR CSV DE REPOSICIONES POR GASTO ----------
@bp.route("/fin/gasto/<int:rid>/reposiciones.csv")
@login_required
def export_reposiciones_gasto(rid):
    db = get_db()
    repos = db.execute("""
        SELECT r.producto, r.cantidad, r.costo_unit, r.total_compra
        FROM reposiciones r
        WHERE r.gasto_rowid=?
        ORDER BY r.rowid
    """, (rid,)).fetchall()

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(["producto", "cantidad", "costo_unit", "costo_total"])
    for r in repos:
        costo_total = r["total_compra"] or (r["cantidad"] * r["costo_unit"])
        cw.writerow([r["producto"], r["cantidad"], f"{r['costo_unit']:.4f}", f"{costo_total:.2f}"])

    return Response(si.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=reposiciones_gasto_{rid}.csv"})

# ---------- (Opcional) silenciar favicon 404 ----------
@bp.route("/favicon.ico")
def favicon():
    return "", 204
