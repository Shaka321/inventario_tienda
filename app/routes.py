# app/routes.py
from datetime import date, datetime, timedelta
from io import StringIO
import csv

from flask import Blueprint, render_template, request, redirect, url_for, flash, Response
from flask_login import login_user, logout_user, current_user, login_required
from werkzeug.security import check_password_hash

from .db import get_db
from .user import User  # <--- *** CAMBIO CLAVE: importar desde user.py ***

bp = Blueprint("main", __name__)

# ---------- HOME (protegida: pide login primero) ----------
@bp.route("/")
@login_required
def home():
    """Dashboard principal: requiere iniciar sesión."""
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
    # Si ya está autenticado, directo al dashboard
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))

    if request.method == "POST":
        # Acepta 'email' o 'username' (tu formulario usa name="username")
        user_input = (request.form.get("email") or request.form.get("username") or "").strip().lower()
        password = request.form.get("password", "")

        db = get_db()
        # Permite iniciar con email O con nombre (case-insensitive).
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
            # Respeta ?next= si venía desde una página protegida
            next_url = request.args.get("next") or url_for("main.home")
            return redirect(next_url)

        flash("Credenciales inválidas", "error")

    # GET: muestra el formulario
    return render_template("login.html")

@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.login"))

# ---------- INVENTARIO ----------
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

    # Filtro de búsqueda simple por nombre/categoría/código
    base_sql = """
      SELECT id, nombre, categoria, precio, cantidad, proveedor, fecha, codigo
      FROM productos
    """
    where = []
    params = []
    if q:
        where.append("(LOWER(nombre) LIKE ? OR LOWER(categoria) LIKE ? OR LOWER(codigo) LIKE ?)")
        like = f"%{q.lower()}%"
        params += [like, like, like]
    if where:
        base_sql += " WHERE " + " AND ".join(where)
    base_sql += " ORDER BY nombre"

    productos = db.execute(base_sql, params).fetchall()

    # Cálculo bajo stock
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
    """
    Endpoint dummy para que el formulario de 'index.html' no falle.
    Solo redirige guardando el umbral en la query (?umbral=...).
    """
    try:
        umbral = int(request.form.get("umbral", 5))
    except ValueError:
        umbral = 5
    # Conserva parámetros de búsqueda si venían
    q = request.args.get("q")
    solo_bajo = request.args.get("solo_bajo")
    return redirect(url_for("main.inventario", umbral=umbral, q=q, solo_bajo=solo_bajo))

# ---------- FINANZAS ----------
@bp.route("/fin")
@login_required
def fin_panel():
    """
    Panel de finanzas con rango seleccionable y datos listos para Chart.js.
    Siempre envía variables con valores por defecto para evitar Undefined.
    """
    db = get_db()

    # ---- Leer filtros de rango ----
    r = (request.args.get("r") or "hoy").strip()
    desde_arg = (request.args.get("desde") or "").strip()
    hasta_arg = (request.args.get("hasta") or "").strip()

    hoy = date.today()
    rango_label = "Hoy"
    # Construir desde/hasta (YYYY-MM-DD). Inclusivo.
    if r == "hoy":
        desde = hoy.isoformat()
        hasta = hoy.isoformat()
        rango_label = "Hoy"
    elif r == "semana":
        d1 = hoy - timedelta(days=6)  # últimos 7 días incl. hoy
        desde = d1.isoformat()
        hasta = hoy.isoformat()
        rango_label = "Últimos 7 días"
    elif r == "mes":
        d1 = hoy.replace(day=1)
        if d1.month == 12:
            dm = date(d1.year + 1, 1, 1) - timedelta(days=1)
        else:
            dm = date(d1.year, d1.month + 1, 1) - timedelta(days=1)
        desde = d1.isoformat()
        hasta = dm.isoformat()
        rango_label = "Mes actual"
    else:  # personalizado
        try:
            d1 = datetime.strptime(desde_arg, "%Y-%m-%d").date()
        except Exception:
            d1 = hoy
        try:
            d2 = datetime.strptime(hasta_arg, "%Y-%m-%d").date()
        except Exception:
            d2 = hoy
        if d2 < d1:
            d2 = d1
        desde = d1.isoformat()
        hasta = d2.isoformat()
        rango_label = "Personalizado"

    # ---- Totales del rango ----
    tv_row = db.execute(
        "SELECT COALESCE(SUM(total),0) AS s FROM ventas WHERE fecha BETWEEN ? AND ?",
        (desde, hasta),
    ).fetchone()
    tg_row = db.execute(
        "SELECT COALESCE(SUM(monto),0) AS s FROM gastos WHERE fecha BETWEEN ? AND ?",
        (desde, hasta),
    ).fetchone()

    total_ventas = float(tv_row["s"] if tv_row and tv_row["s"] is not None else 0.0)
    total_gastos = float(tg_row["s"] if tg_row and tg_row["s"] is not None else 0.0)
    ganancia_neta = total_ventas - total_gastos

    # ---- Ventas por día (labels/values) ----
    ventas_labels = []
    ventas_values = []
    rows_vd = db.execute(
        """
        SELECT fecha, COALESCE(SUM(total),0) AS s
        FROM ventas
        WHERE fecha BETWEEN ? AND ?
        GROUP BY fecha
        ORDER BY fecha
        """,
        (desde, hasta),
    ).fetchall()
    for rvd in rows_vd:
        ventas_labels.append(str(rvd["fecha"]))
        ventas_values.append(float(rvd["s"] or 0))

    # ---- Top 5 productos (labels/values) ----
    top_labels = []
    top_values = []
    rows_top = db.execute(
        """
        SELECT producto, COALESCE(SUM(cantidad),0) AS cant
        FROM ventas
        WHERE fecha BETWEEN ? AND ?
        GROUP BY producto
        ORDER BY cant DESC
        LIMIT 5
        """,
        (desde, hasta),
    ).fetchall()
    for rt in rows_top:
        top_labels.append(str(rt["producto"]))
        try:
            top_values.append(float(rt["cant"] or 0))
        except Exception:
            top_values.append(0.0)

    # ---- Render con valores por defecto garantizados ----
    return render_template(
        "fin_panel.html",
        # filtros y etiquetas
        r=r,
        desde=desde,
        hasta=hasta,
        rango_label=rango_label,
        # tarjetas resumen
        total_ventas=round(total_ventas, 2),
        total_gastos=round(total_gastos, 2),
        ganancia_neta=round(ganancia_neta, 2),
        # datasets para gráficos
        ventas_labels=ventas_labels or [],
        ventas_values=ventas_values or [],
        top_labels=top_labels or [],
        top_values=top_values or [],
    )

# ---------- LISTAS / FORMULARIOS FINANZAS ----------
@bp.route("/fin/ventas", methods=["GET"], endpoint="fin_ventas")
@login_required
def fin_ventas():
    """
    Lista simple de ventas (para tu botón 'Registrar venta' puedes enlazar aquí
    o a un formulario si ya lo tienes como fin_venta_form.html).
    """
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
    rows = db.execute(
        "SELECT fecha, motivo, monto FROM gastos ORDER BY fecha DESC"
    ).fetchall()
    return render_template(
        "fin_gastos_lista.html",
        gastos=rows,
        r=request.args.get("r", "hoy"),
        desde=request.args.get("desde", ""),
        hasta=request.args.get("hasta", ""),
        rango_label="Hoy",
    )

# ---------- REPORTES ----------
@bp.route("/reportes/reposiciones")
@login_required
def reportes_reposiciones():
    return render_template(
        "reportes_reposiciones.html",
        rows=[],
        productos=[],
        r=request.args.get("r", "hoy"),
        desde=request.args.get("desde", ""),
        hasta=request.args.get("hasta", ""),
        producto_id=request.args.get("producto_id", ""),
        origen=request.args.get("origen", ""),
        rango_label="Hoy",
    )

# ---------- ADMIN ----------
@bp.route("/admin")
@login_required
def admin():
    """
    Evita crash de admin.html: pásale 'total' y 'page_size'.
    Aquí solo mostramos un tablero básico; adapta a tu lógica real.
    """
    db = get_db()
    total_row = db.execute("SELECT COUNT(*) AS c FROM productos").fetchone()
    total = int(total_row["c"] if total_row and total_row["c"] is not None else 0)
    page_size = 20
    page = int(request.args.get("page", 1))
    return render_template("admin.html", total=total, page_size=page_size, page=page)

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
        where.append("fecha >= ?")
        params.append(desde)
    if hasta:
        where.append("fecha <= ?")
        params.append(hasta)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY fecha DESC"

    rows = db.execute(sql, params).fetchall()

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(["fecha", "producto", "cantidad", "precio_unit", "total"])
    for r in rows:
        cw.writerow([r["fecha"], r["producto"], r["cantidad"], r["precio_unit"], r["total"]])

    return Response(
        si.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=ventas.csv"},
    )

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
        where.append("fecha >= ?")
        params.append(desde)
    if hasta:
        where.append("fecha <= ?")
        params.append(hasta)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY fecha DESC"

    rows = db.execute(sql, params).fetchall()

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(["fecha", "motivo", "monto"])
    for r in rows:
        cw.writerow([r["fecha"], r["motivo"], r["monto"]])

    return Response(
        si.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=gastos.csv"},
    )

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
        where.append("fecha >= ?")
        params.append(desde)
    if hasta:
        where.append("fecha <= ?")
        params.append(hasta)
    if producto_id:
        where.append("producto = ?")
        params.append(producto_id)
    if origen:
        where.append("ref = ?")
        params.append(origen)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY fecha DESC"

    rows = db.execute(sql, params).fetchall()

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(["fecha", "producto", "cantidad", "costo_unit", "proveedor", "ref"])
    for r in rows:
        cw.writerow([r["fecha"], r["producto"], r["cantidad"], r["costo_unit"], r["proveedor"], r["ref"]])

    return Response(
        si.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=reposiciones.csv"},
    )
