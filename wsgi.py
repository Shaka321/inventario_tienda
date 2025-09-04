import os
import sqlite3, io, csv, re
from datetime import datetime, timedelta, date
from flask import Flask, render_template, request, redirect, url_for, Response, session, flash
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

# -------------------- App & Config --------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-change-me')  # cámbiala en prod

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH  = os.path.join(BASE_DIR, 'inventario.db')

def get_conn():
    # ¡OJO! NO LLAMAR get_conn() aquí dentro. Debe ser sqlite3.connect(DB_PATH).
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

# -------------------- Login helpers --------------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login', next=request.path))
        return view(*args, **kwargs)
    return wrapped

@app.before_request
def _require_login():
    # Endpoints permitidos sin login
    open_endpoints = {'login', 'static'}
    if (request.endpoint is None) or request.endpoint.startswith('static'):
        return
    if request.endpoint in open_endpoints:
        return
    if not session.get('user_id'):
        return redirect(url_for('login', next=request.path))

@app.context_processor
def inject_user():
    return {
        'current_user': {
            'id': session.get('user_id'),
            'username': session.get('username'),
            'rol': session.get('rol')
        }
    }

# -------------------- Config & Const --------------------
ALLOWED_TABLES = {
    'productos': ['id','nombre','categoria','precio_unitario','cantidad_stock','proveedor','fecha_registro','codigo_barras','precio_paquete','unidades_por_paquete'],
    'ventas':    ['id','fecha','producto','cantidad','precio_unit','total','modo','producto_id'],
    'gastos':    ['id','fecha','motivo','monto'],
    'stock_movimientos': ['id','fecha','producto_id','tipo','referencia','cantidad_unidades','precio_unit','costo_unit'],
    'reposiciones': ['id','fecha','producto_id','cantidad','costo_unit','proveedor'],
    'proveedores': ['id','nombre','telefono','email'],
    'compras': ['id','fecha','proveedor_id','total'],
    'compra_items': ['id','compra_id','producto_id','cantidad','costo_unit','subtotal'],
    'ventas_enc': ['id','fecha','total'],
    'venta_items': ['id','venta_id','producto_id','modo','cantidad','unidades','precio_unit','subtotal'],
}

PREFIX_CB = "PROD"
PAD_CB = 4

# -------------------- DB bootstrap (crea todo) --------------------
def crear_base_datos():
    conn = get_conn(); c = conn.cursor()

    # --- Base mínima ---
    c.execute('''CREATE TABLE IF NOT EXISTS productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        categoria TEXT,
        precio_unitario REAL,
        cantidad_stock INTEGER,
        proveedor TEXT,
        fecha_registro TEXT,
        codigo_barras TEXT UNIQUE
    )''')
    c.execute("""CREATE INDEX IF NOT EXISTS idx_productos_busqueda
                 ON productos (nombre, categoria, codigo_barras)""")

    c.execute('''CREATE TABLE IF NOT EXISTS ventas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT,
        producto TEXT,
        cantidad INTEGER,
        precio_unit REAL,
        total REAL,
        modo TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS gastos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT,
        motivo TEXT,
        monto REAL
    )''')

    c.execute("""CREATE TABLE IF NOT EXISTS config (
        clave TEXT PRIMARY KEY,
        valor TEXT
    )""")

    # --- Migraciones suaves productos ---
    try: c.execute("ALTER TABLE productos ADD COLUMN precio_paquete REAL")
    except sqlite3.OperationalError: pass
    try: c.execute("ALTER TABLE productos ADD COLUMN unidades_por_paquete INTEGER")
    except sqlite3.OperationalError: pass

    # --- Migraciones suaves ventas ---
    try: c.execute("ALTER TABLE ventas ADD COLUMN producto_id INTEGER")
    except sqlite3.OperationalError: pass
    try: c.execute("CREATE INDEX IF NOT EXISTS idx_ventas_producto_id ON ventas(producto_id)")
    except sqlite3.OperationalError: pass

    # --- Umbral por defecto ---
    c.execute("""INSERT OR IGNORE INTO config (clave, valor) VALUES ('umbral_bajo_stock', '5')""")

    # --- Kardex / Movimientos de stock ---
    c.execute("""
    CREATE TABLE IF NOT EXISTS stock_movimientos (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      fecha TEXT NOT NULL,
      producto_id INTEGER NOT NULL,
      tipo TEXT NOT NULL CHECK (tipo IN ('venta','reposicion','ajuste')),
      referencia TEXT,
      cantidad_unidades INTEGER NOT NULL,
      precio_unit REAL,
      costo_unit REAL,
      FOREIGN KEY(producto_id) REFERENCES productos(id)
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_mov_productofecha ON stock_movimientos(producto_id, fecha)")

    # --- Reposiciones (registro simple) ---
    c.execute("""
    CREATE TABLE IF NOT EXISTS reposiciones (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      fecha TEXT NOT NULL,
      producto_id INTEGER NOT NULL,
      cantidad INTEGER NOT NULL,
      costo_unit REAL,
      proveedor TEXT,
      FOREIGN KEY(producto_id) REFERENCES productos(id)
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_repo_productofecha ON reposiciones(producto_id, fecha)")

    # --- Proveedores / Compras / Detalle ---
    c.execute("""
    CREATE TABLE IF NOT EXISTS proveedores (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      nombre TEXT NOT NULL,
      telefono TEXT, email TEXT
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS compras (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      fecha TEXT NOT NULL,
      proveedor_id INTEGER,
      total REAL,
      FOREIGN KEY(proveedor_id) REFERENCES proveedores(id)
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS compra_items (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      compra_id INTEGER NOT NULL,
      producto_id INTEGER NOT NULL,
      cantidad INTEGER NOT NULL,
      costo_unit REAL NOT NULL,
      subtotal REAL NOT NULL,
      FOREIGN KEY(compra_id) REFERENCES compras(id),
      FOREIGN KEY(producto_id) REFERENCES productos(id)
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_compra_items_compra ON compra_items(compra_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_compra_items_producto ON compra_items(producto_id)")

    # --- Ventas con detalle (encabezado+items) ---
    c.execute("""
    CREATE TABLE IF NOT EXISTS ventas_enc (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      fecha TEXT NOT NULL,
      total REAL NOT NULL
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS venta_items (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      venta_id INTEGER NOT NULL,
      producto_id INTEGER NOT NULL,
      modo TEXT,
      cantidad INTEGER NOT NULL,
      unidades INTEGER NOT NULL,
      precio_unit REAL NOT NULL,
      subtotal REAL NOT NULL,
      FOREIGN KEY(venta_id) REFERENCES ventas_enc(id),
      FOREIGN KEY(producto_id) REFERENCES productos(id)
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_venta_items_venta ON venta_items(venta_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_venta_items_producto ON venta_items(producto_id)")

    conn.commit(); conn.close()

def ensure_login_tables():
    conn = get_conn(); c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      rol TEXT NOT NULL DEFAULT 'admin',
      activo INTEGER NOT NULL DEFAULT 1,
      creado_en TEXT NOT NULL
    )""")
    # Admin por defecto
    c.execute("SELECT COUNT(*) FROM usuarios WHERE username='admin'")
    if c.fetchone()[0] == 0:
        pw_hash = generate_password_hash("admin123")
        c.execute("""INSERT INTO usuarios (username, password_hash, rol, activo, creado_en)
                     VALUES ('admin', ?, 'admin', 1, datetime('now'))""", (pw_hash,))
    conn.commit(); conn.close()

crear_base_datos()
ensure_login_tables()

# -------------------- Helpers varios --------------------
def _query_all(tabla, cols):
    conn = get_conn(); c = conn.cursor()
    c.execute(f"SELECT {', '.join(cols)} FROM {tabla}")
    rows = c.fetchall()
    conn.close()
    return rows

def _query_all_filtered(tabla, cols, desde_str, hasta_str):
    conn = get_conn(); c = conn.cursor()
    c.execute(f"SELECT {', '.join(cols)} FROM {tabla} WHERE date(fecha) BETWEEN ? AND ? ORDER BY fecha DESC",
              (desde_str, hasta_str))
    rows = c.fetchall(); conn.close()
    return rows

def _rango_fechas(r, desde_arg, hasta_arg):
    hoy = date.today()
    if r == 'hoy':   return hoy, hoy, 'Hoy'
    if r == 'semana':return hoy - timedelta(days=6), hoy, 'Últimos 7 días'
    if r == 'mes':   return hoy.replace(day=1), hoy, 'Mes actual'
    try:
        d = datetime.strptime(desde_arg, '%Y-%m-%d').date()
        h = datetime.strptime(hasta_arg, '%Y-%m-%d').date()
        if d > h: d, h = h, d
        return d, h, 'Personalizado'
    except Exception:
        return hoy.replace(day=1), hoy, 'Mes actual'

def get_umbral_bajo_stock():
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT valor FROM config WHERE clave='umbral_bajo_stock'")
    fila = c.fetchone(); conn.close()
    return int(fila[0]) if fila and str(fila[0]).isdigit() else 5

def set_umbral_bajo_stock(nuevo):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO config (clave, valor) VALUES ('umbral_bajo_stock', ?)", (str(nuevo),))
    conn.commit(); conn.close()

def generar_siguiente_codigo():
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT codigo_barras FROM productos WHERE codigo_barras LIKE ?", (f"{PREFIX_CB}%",))
    filas = c.fetchall(); conn.close()
    max_n = 0
    patron = re.compile(rf"^{PREFIX_CB}(\d+)$")
    for (cod,) in filas:
        if not cod: continue
        m = patron.match(cod)
        if m:
            n = int(m.group(1))
            if n > max_n: max_n = n
    return f"{PREFIX_CB}{str(max_n+1).zfill(PAD_CB)}"

# -------------------- Login --------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT id, username, password_hash, rol, activo FROM usuarios WHERE username = ?", (username,))
        row = c.fetchone(); conn.close()

        if not row:
            flash("Usuario o contraseña incorrectos", "error")
            return render_template('login.html'), 401

        uid, uname, phash, rol, activo = row
        if not activo:
            flash("Usuario inactivo", "error")
            return render_template('login.html'), 403

        if not check_password_hash(phash, password):
            flash("Usuario o contraseña incorrectos", "error")
            return render_template('login.html'), 401

        session['user_id'] = uid
        session['username'] = uname
        session['rol'] = rol

        next_url = request.args.get('next') or url_for('inicio')
        return redirect(next_url)

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# -------------------- Inicio --------------------
@app.route('/')
def root_redirect():
    return redirect(url_for('inicio'))

@app.route('/inicio')
@login_required
def inicio():
    ctx = _finanzas_data('mes', '', '')
    return render_template('inicio.html', **ctx)

# -------------------- Finanzas: datos comunes --------------------
def _finanzas_data(r, desde_arg, hasta_arg):
    desde_d, hasta_d, rango_label = _rango_fechas(r, desde_arg, hasta_arg)
    desde_str = desde_d.strftime('%Y-%m-%d'); hasta_str = hasta_d.strftime('%Y-%m-%d')

    conn = get_conn(); c = conn.cursor()

    c.execute("SELECT nombre, precio_unitario, cantidad_stock, precio_paquete, unidades_por_paquete FROM productos")
    productos = c.fetchall()

    c.execute("""SELECT fecha, producto, cantidad, precio_unit, total
                 FROM ventas WHERE date(fecha) BETWEEN ? AND ? ORDER BY fecha DESC""",
              (desde_str, hasta_str))
    ventas = c.fetchall()

    c.execute("""SELECT fecha, motivo, monto
                 FROM gastos WHERE date(fecha) BETWEEN ? AND ? ORDER BY fecha DESC""",
              (desde_str, hasta_str))
    gastos = c.fetchall()

    total_ventas = sum(v[4] for v in ventas) if ventas else 0
    total_gastos = sum(g[2] for g in gastos) if gastos else 0
    ganancia_neta = total_ventas - total_gastos

    c.execute("""SELECT date(fecha) f, SUM(total) monto
                 FROM ventas WHERE date(fecha) BETWEEN ? AND ?
                 GROUP BY f ORDER BY f""", (desde_str, hasta_str))
    ventas_por_dia = c.fetchall()
    ventas_labels = [row[0] for row in ventas_por_dia]
    ventas_values = [row[1] for row in ventas_por_dia]

    c.execute("""SELECT producto, SUM(cantidad) cant
                 FROM ventas WHERE date(fecha) BETWEEN ? AND ?
                 GROUP BY producto ORDER BY cant DESC LIMIT 5""",
              (desde_str, hasta_str))
    top_rows = c.fetchall()
    top_labels = [row[0] for row in top_rows]
    top_values = [row[1] for row in top_rows]

    conn.close()

    return {
        'r': r, 'desde': desde_str, 'hasta': hasta_str, 'rango_label': rango_label,
        'productos': productos,
        'ventas': ventas, 'gastos': gastos,
        'total_ventas': total_ventas, 'total_gastos': total_gastos, 'ganancia_neta': ganancia_neta,
        'ventas_labels': ventas_labels, 'ventas_values': ventas_values,
        'top_labels': top_labels, 'top_values': top_values
    }

# -------------------- Inventario --------------------
@app.route('/inventario', methods=['GET'])
@login_required
def inventario():
    q = request.args.get('q', '').strip()
    solo_bajo = request.args.get('solo_bajo', '0') == '1'
    umbral = get_umbral_bajo_stock()

    conn = get_conn(); c = conn.cursor()
    base_sql = "SELECT * FROM productos"
    where, params = [], []
    if q:
        where.append("(nombre LIKE ? OR categoria LIKE ? OR codigo_barras LIKE ?)")
        patron = f"%{q}%"
        params += [patron, patron, patron]
    if solo_bajo:
        where.append("cantidad_stock <= ?")
        params.append(umbral)
    if where:
        base_sql += " WHERE " + " AND ".join(where)
    base_sql += " ORDER BY id DESC"
    c.execute(base_sql, params)
    productos = c.fetchall()
    c.execute("SELECT COUNT(*) FROM productos WHERE cantidad_stock <= ?", (umbral,))
    low_count = c.fetchone()[0]
    conn.close()

    return render_template('index.html',
                           productos=productos, q=q,
                           solo_bajo=1 if solo_bajo else 0,
                           umbral=umbral, low_count=low_count)

# -------------------- Finanzas (vistas separadas) --------------------
@app.route('/finanzas')
def finanzas_redirect():
    return redirect(url_for('fin_panel'))

@app.route('/finanzas/panel')
@login_required
def fin_panel():
    r = request.args.get('r', 'mes'); desde = request.args.get('desde', ''); hasta = request.args.get('hasta', '')
    ctx = _finanzas_data(r, desde, hasta)
    return render_template('fin_panel.html', **ctx)

@app.route('/finanzas/ventas')
@login_required
def fin_ventas():
    r = request.args.get('r', 'mes'); desde = request.args.get('desde', ''); hasta = request.args.get('hasta', '')
    ctx = _finanzas_data(r, desde, hasta)
    return render_template('fin_ventas_lista.html', **ctx)

@app.route('/finanzas/gastos')
@login_required
def fin_gastos():
    r = request.args.get('r', 'mes'); desde = request.args.get('desde', ''); hasta = request.args.get('hasta', '')
    ctx = _finanzas_data(r, desde, hasta)
    return render_template('fin_gastos_lista.html', **ctx)

@app.route('/finanzas/venta/nueva')
@login_required
def fin_venta_nueva():
    r = request.args.get('r', 'mes'); desde = request.args.get('desde', ''); hasta = request.args.get('hasta', '')
    ctx = _finanzas_data(r, desde, hasta)
    return render_template('fin_venta_form.html', **ctx)

@app.route('/finanzas/gasto/nuevo')
@login_required
def fin_gasto_nuevo():
    r = request.args.get('r', 'mes'); desde = request.args.get('desde', ''); hasta = request.args.get('hasta', '')
    ctx = _finanzas_data(r, desde, hasta)
    return render_template('fin_gasto_form.html', **ctx)

@app.route('/finanzas/reposicion')
@login_required
def fin_reposicion():
    r = request.args.get('r', 'mes'); desde = request.args.get('desde', ''); hasta = request.args.get('hasta', '')
    ctx = _finanzas_data(r, desde, hasta)
    return render_template('fin_reposicion_form.html', **ctx)

# -------------------- Acciones (POST) --------------------
@app.route('/agregar', methods=['POST'])
@login_required
def agregar():
    nombre = request.form['nombre'].strip()
    categoria = request.form['categoria'].strip()
    precio = float(request.form['precio'])
    cantidad = int(request.form['cantidad'])
    proveedor = request.form['proveedor'].strip()
    codigo = request.form.get('codigo', '').strip()
    precio_paquete = request.form.get('precio_paquete', '').strip()
    unidades_paquete = request.form.get('unidades_por_paquete', '').strip()
    precio_paquete = float(precio_paquete) if precio_paquete else None
    unidades_paquete = int(unidades_paquete) if unidades_paquete else None
    if not codigo:
        codigo = generar_siguiente_codigo()
    fecha = datetime.now().strftime('%Y-%m-%d')

    conn = get_conn(); c = conn.cursor()
    c.execute("""INSERT INTO productos
        (nombre, categoria, precio_unitario, cantidad_stock, proveedor, fecha_registro, codigo_barras, precio_paquete, unidades_por_paquete)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (nombre, categoria, precio, cantidad, proveedor, fecha, codigo, precio_paquete, unidades_paquete))
    conn.commit(); conn.close()
    return redirect(url_for('inventario'))

@app.route('/registrar_venta', methods=['POST'])
@login_required
def registrar_venta():
    producto = request.form['producto']
    modo = request.form.get('modo', 'unidad')
    cantidad = int(request.form['cantidad'])

    conn = get_conn(); c = conn.cursor()
    c.execute("""SELECT id, precio_unitario, cantidad_stock, precio_paquete, unidades_por_paquete
                 FROM productos WHERE nombre = ?""", (producto,))
    row = c.fetchone()
    if not row: conn.close(); return "❌ Error: producto no encontrado", 400

    pid, precio_unitario, stock_actual, precio_paquete, unidades_por_paquete = row

    if modo == 'paquete':
        if not precio_paquete or not unidades_por_paquete:
            conn.close(); return "❌ Error: este producto no tiene configurado precio de paquete o unidades por paquete"
        precio_usado = float(precio_paquete)
        unidades_necesarias = cantidad * int(unidades_por_paquete)
    else:
        precio_usado = float(precio_unitario)
        unidades_necesarias = cantidad

    if stock_actual < unidades_necesarias:
        conn.close(); return "❌ Error: No hay suficiente stock para esta venta"

    total = round(precio_usado * cantidad, 2)
    fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    c.execute("""INSERT INTO ventas (fecha, producto, cantidad, precio_unit, total, modo, producto_id)
                 VALUES (?, ?, ?, ?, ?, ?, ?)""",
              (fecha, producto, cantidad, precio_usado, total, modo, pid))
    venta_id = c.lastrowid

    c.execute("UPDATE productos SET cantidad_stock = ? WHERE id = ?", (stock_actual - unidades_necesarias, pid))

    c.execute("""INSERT INTO stock_movimientos
                    (fecha, producto_id, tipo, referencia, cantidad_unidades, precio_unit, costo_unit)
                 VALUES (?, ?, 'venta', ?, ?, ?, NULL)""",
              (fecha, pid, f'venta:{venta_id}', -unidades_necesarias, precio_usado))

    conn.commit(); conn.close()
    return redirect(url_for('fin_ventas'))

@app.route('/registrar_gasto', methods=['POST'])
@login_required
def registrar_gasto():
    motivo = request.form['motivo'].strip()
    monto = float(request.form['monto'])
    fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO gastos (fecha, motivo, monto) VALUES (?, ?, ?)", (fecha, motivo, monto))
    conn.commit(); conn.close()
    return redirect(url_for('fin_gastos'))

@app.route('/reposicion', methods=['POST'])
@login_required
def reposicion():
    producto = request.form['producto_repos']
    cantidad = int(request.form['cantidad_repos'])

    costo_unit_str = request.form.get('costo_unit', '').strip()
    proveedor = request.form.get('proveedor', '').strip() or None
    costo_unit = float(costo_unit_str) if costo_unit_str else None

    fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT id FROM productos WHERE nombre = ?", (producto,))
    row = c.fetchone()
    if not row: conn.close(); return "❌ Error: producto no encontrado", 400
    pid = row[0]

    c.execute("UPDATE productos SET cantidad_stock = cantidad_stock + ? WHERE id = ?", (cantidad, pid))

    c.execute("""INSERT INTO reposiciones (fecha, producto_id, cantidad, costo_unit, proveedor)
                 VALUES (?, ?, ?, ?, ?)""", (fecha, pid, cantidad, costo_unit, proveedor))
    repo_id = c.lastrowid

    c.execute("""INSERT INTO stock_movimientos
                    (fecha, producto_id, tipo, referencia, cantidad_unidades, precio_unit, costo_unit)
                 VALUES (?, ?, 'reposicion', ?, ?, NULL, ?)""",
              (fecha, pid, f'repo:{repo_id}', cantidad, costo_unit))

    conn.commit(); conn.close()
    return redirect(url_for('fin_reposicion'))

# -------------------- Compras (simple 1 ítem) --------------------
@app.route('/compras/nueva', methods=['GET', 'POST'])
@login_required
def compras_nueva():
    if request.method == 'POST':
        producto_nombre = request.form['producto']
        cantidad = int(request.form['cantidad'])
        costo_unit = float(request.form['costo_unit'])
        proveedor_txt = request.form.get('proveedor', '').strip() or None

        fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        conn = get_conn(); c = conn.cursor()

        proveedor_id = None
        if proveedor_txt:
            c.execute("SELECT id FROM proveedores WHERE nombre = ?", (proveedor_txt,))
            row = c.fetchone()
            if row: proveedor_id = row[0]
            else:
                c.execute("INSERT INTO proveedores (nombre) VALUES (?)", (proveedor_txt,))
                proveedor_id = c.lastrowid

        c.execute("SELECT id FROM productos WHERE nombre = ?", (producto_nombre,))
        prod = c.fetchone()
        if not prod: conn.close(); return "❌ Producto no encontrado", 400
        producto_id = prod[0]

        total = round(costo_unit * cantidad, 2)
        c.execute("INSERT INTO compras (fecha, proveedor_id, total) VALUES (?, ?, ?)", (fecha, proveedor_id, total))
        compra_id = c.lastrowid

        c.execute("""INSERT INTO compra_items
                        (compra_id, producto_id, cantidad, costo_unit, subtotal)
                     VALUES (?, ?, ?, ?, ?)""", (compra_id, producto_id, cantidad, costo_unit, total))

        c.execute("UPDATE productos SET cantidad_stock = cantidad_stock + ? WHERE id = ?", (cantidad, producto_id))

        c.execute("""INSERT INTO stock_movimientos
                        (fecha, producto_id, tipo, referencia, cantidad_unidades, precio_unit, costo_unit)
                     VALUES (?, ?, 'reposicion', ?, ?, NULL, ?)""",
                  (fecha, producto_id, f'compra:{compra_id}', cantidad, costo_unit))

        conn.commit(); conn.close()
        return redirect(url_for('fin_reposicion'))

    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT nombre FROM productos ORDER BY nombre ASC")
    productos = [r[0] for r in c.fetchall()]
    conn.close()
    return render_template('compras_form.html', productos=productos)

# -------------------- Admin --------------------
@app.route('/admin')
@login_required
def admin():
    tablas = list(ALLOWED_TABLES.keys())
    tabla = request.args.get('tabla', 'productos').lower()
    if tabla not in ALLOWED_TABLES: tabla = 'productos'
    try:
        page = int(request.args.get('page', '1'))
        if page < 1: page = 1
    except: page = 1
    page_size = 20; offset = (page - 1) * page_size
    cols = ALLOWED_TABLES[tabla]
    conn = get_conn(); c = conn.cursor()
    c.execute(f"SELECT COUNT(*) FROM {tabla}"); total = c.fetchone()[0]
    order_by = "id DESC" if "id" in cols else f"{cols[0]} ASC"
    c.execute(f"SELECT {', '.join(cols)} FROM {tabla} ORDER BY {order_by} LIMIT ? OFFSET ?", (page_size, offset))
    rows = c.fetchall(); conn.close()
    return render_template('admin.html',
        tablas=tablas, tabla=tabla, cols=cols, rows=rows,
        total=total, page=page, page_size=page_size, base_url=url_for('admin'))

# -------------------- Export CSV --------------------
@app.route('/export/<tabla>.csv')
@login_required
def export_csv(tabla):
    tabla = tabla.lower()
    if tabla not in ALLOWED_TABLES:
        return "Tabla no permitida", 400
    cols = ALLOWED_TABLES[tabla]
    rows = _query_all(tabla, cols)
    si = io.StringIO(); writer = csv.writer(si)
    writer.writerow(cols); writer.writerows(rows)
    output = si.getvalue(); si.close()
    return Response(output, mimetype='text/csv',
        headers={ "Content-Disposition": f"attachment; filename={tabla}.csv" })

@app.route('/export/ventas_filtrado.csv')
@login_required
def export_ventas_filtrado():
    r = request.args.get('r', 'mes'); desde = request.args.get('desde', ''); hasta = request.args.get('hasta', '')
    ctx = _finanzas_data(r, desde, hasta)
    cols = ALLOWED_TABLES['ventas']
    si = io.StringIO(); writer = csv.writer(si)
    writer.writerow(cols)
    for row in _query_all_filtered('ventas', cols, ctx['desde'], ctx['hasta']):
        writer.writerow(row)
    output = si.getvalue(); si.close()
    return Response(output, mimetype='text/csv',
        headers={ "Content-Disposition": "attachment; filename=ventas_filtrado.csv" })

@app.route('/export/gastos_filtrado.csv')
@login_required
def export_gastos_filtrado():
    r = request.args.get('r', 'mes'); desde = request.args.get('desde', ''); hasta = request.args.get('hasta', '')
    ctx = _finanzas_data(r, desde, hasta)
    cols = ALLOWED_TABLES['gastos']
    si = io.StringIO(); writer = csv.writer(si)
    writer.writerow(cols)
    for row in _query_all_filtered('gastos', cols, ctx['desde'], ctx['hasta']):
        writer.writerow(row)
    output = si.getvalue(); si.close()
    return Response(output, mimetype='text/csv',
        headers={ "Content-Disposition": "attachment; filename=gastos_filtrado.csv" })

# -------------------- Editar / Eliminar producto --------------------
@app.route('/producto/<int:pid>/editar', methods=['GET','POST'])
@login_required
def editar_producto(pid):
    conn = get_conn(); c = conn.cursor()
    if request.method == 'POST':
        nombre = request.form['nombre'].strip()
        categoria = request.form['categoria'].strip()
        precio = float(request.form['precio']); cantidad = int(request.form['cantidad'])
        proveedor = request.form['proveedor'].strip()
        codigo = request.form['codigo'].strip()
        try:
            c.execute("""UPDATE productos
                         SET nombre=?, categoria=?, precio_unitario=?, cantidad_stock=?, proveedor=?, codigo_barras=?
                         WHERE id=?""", (nombre, categoria, precio, cantidad, proveedor, codigo, pid))
            conn.commit()
        finally:
            conn.close()
        return redirect(url_for('inventario'))
    c.execute("""SELECT id, nombre, categoria, precio_unitario, cantidad_stock, proveedor, codigo_barras
                 FROM productos WHERE id=?""", (pid,))
    producto = c.fetchone(); conn.close()
    if not producto: return "Producto no encontrado", 404
    return render_template('editar_producto.html', p=producto)

@app.route('/producto/<int:pid>/eliminar', methods=['POST'])
@login_required
def eliminar_producto(pid):
    conn = get_conn(); c = conn.cursor()
    c.execute("DELETE FROM productos WHERE id=?", (pid,))
    conn.commit(); conn.close()
    return redirect(url_for('inventario'))

# --- Configurar umbral de bajo stock ---
@app.route('/config/umbral', methods=['POST'])
@login_required
def actualizar_umbral():
    """Actualiza el umbral de bajo stock y regresa a /inventario conservando filtros."""
    try:
        nuevo = int(request.form.get('umbral', 0))
        if nuevo < 0:
            nuevo = 0
        set_umbral_bajo_stock(nuevo)
    except Exception:
        # No rompas la vista si llega algo inválido
        pass

    # Mantén los filtros que venían en la URL
    q = request.args.get('q', '')
    solo_bajo = request.args.get('solo_bajo', '')
    return redirect(url_for('inventario', q=q, solo_bajo=solo_bajo))

# -------------------- Ventas detalle (test 1 ítem) --------------------
@app.route('/ventas/detalle/test', methods=['GET'])
@login_required
def venta_detalle_test():
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT nombre, precio_unitario, precio_paquete, unidades_por_paquete FROM productos ORDER BY nombre")
    productos = c.fetchall()
    conn.close()
    return render_template('ventas_detalle_test.html', productos=productos)

@app.route('/ventas/detalle/nueva', methods=['POST'])
@login_required
def venta_detalle_nueva():
    producto = request.form['producto']
    modo = request.form.get('modo', 'unidad')
    cantidad = int(request.form['cantidad'])
    precio_unit = float(request.form['precio_unit'])

    conn = get_conn(); c = conn.cursor()
    c.execute("""SELECT id, cantidad_stock, precio_paquete, unidades_por_paquete, precio_unitario
                 FROM productos WHERE nombre=?""", (producto,))
    row = c.fetchone()
    if not row: conn.close(); return "Producto no encontrado", 400
    pid, stock, precio_pack, u_pack, precio_unid = row

    if modo == 'paquete':
        if not precio_pack or not u_pack:
            conn.close(); return "Sin configuración de paquete", 400
        unidades = cantidad * int(u_pack)
    else:
        unidades = cantidad

    if stock < unidades:
        conn.close(); return "Stock insuficiente", 400

    subtotal = round(precio_unit * cantidad, 2)
    fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    c.execute("INSERT INTO ventas_enc (fecha, total) VALUES (?, ?)", (fecha, subtotal))
    venta_id = c.lastrowid

    c.execute("""INSERT INTO venta_items
                 (venta_id, producto_id, modo, cantidad, unidades, precio_unit, subtotal)
                 VALUES (?, ?, ?, ?, ?, ?, ?)""",
              (venta_id, pid, modo, cantidad, unidades, precio_unit, subtotal))

    c.execute("UPDATE productos SET cantidad_stock = cantidad_stock - ? WHERE id = ?", (unidades, pid))

    c.execute("""INSERT INTO stock_movimientos
                 (fecha, producto_id, tipo, referencia, cantidad_unidades, precio_unit, costo_unit)
                 VALUES (?, ?, 'venta', ?, ?, ?, NULL)""",
              (fecha, pid, f'venta_enc:{venta_id}', -unidades, precio_unit))

    conn.commit(); conn.close()
    return "OK"

# -------------------- Reporte de Reposiciones --------------------
@app.route('/reportes/reposiciones')
@login_required
def reportes_reposiciones():
    r = request.args.get('r', 'mes')
    desde = request.args.get('desde', '')
    hasta = request.args.get('hasta', '')
    producto_id = request.args.get('producto_id', '').strip()
    origen = request.args.get('origen', '')  # '', 'compra', 'manual'

    desde_d, hasta_d, rango_label = _rango_fechas(r, desde, hasta)
    desde_str = desde_d.strftime('%Y-%m-%d'); hasta_str = hasta_d.strftime('%Y-%m-%d')

    conn = get_conn(); c = conn.cursor()

    c.execute("SELECT id, nombre FROM productos ORDER BY nombre")
    productos = c.fetchall()

    base = """
      SELECT m.fecha, p.nombre, p.codigo_barras, p.categoria,
             m.cantidad_unidades, m.costo_unit, m.referencia
      FROM stock_movimientos m
      JOIN productos p ON p.id = m.producto_id
      WHERE m.tipo = 'reposicion'
        AND date(m.fecha) BETWEEN ? AND ?
    """
    params = [desde_str, hasta_str]

    if producto_id:
        base += " AND m.producto_id = ?"
        params.append(producto_id)

    if origen == 'compra':
        base += " AND m.referencia LIKE 'compra:%'"
    elif origen == 'manual':
        base += " AND m.referencia LIKE 'repo:%'"

    base += " ORDER BY m.fecha DESC"

    c.execute(base, params)
    rows = c.fetchall(); conn.close()

    total_unidades = sum(rw[4] for rw in rows) if rows else 0
    total_valor = sum((rw[4] * (rw[5] or 0)) for rw in rows) if rows else 0.0

    return render_template('reportes_reposiciones.html',
                           r=r, desde=desde_str, hasta=hasta_str, rango_label=rango_label,
                           productos=productos, producto_id=str(producto_id or ''),
                           origen=origen, rows=rows,
                           total_unidades=total_unidades, total_valor=round(total_valor, 2))

@app.route('/export/reposiciones_filtrado.csv')
@login_required
def export_reposiciones_filtrado():
    r = request.args.get('r', 'mes')
    desde = request.args.get('desde', '')
    hasta = request.args.get('hasta', '')
    producto_id = request.args.get('producto_id', '').strip()
    origen = request.args.get('origen', '')

    desde_d, hasta_d, _ = _rango_fechas(r, desde, hasta)
    desde_str = desde_d.strftime('%Y-%m-%d'); hasta_str = hasta_d.strftime('%Y-%m-%d')

    conn = get_conn(); c = conn.cursor()
    base = """
      SELECT m.fecha, p.nombre, p.codigo_barras, p.categoria,
             m.cantidad_unidades, m.costo_unit, m.referencia
      FROM stock_movimientos m
      JOIN productos p ON p.id = m.producto_id
      WHERE m.tipo = 'reposicion'
        AND date(m.fecha) BETWEEN ? AND ?
    """
    params = [desde_str, hasta_str]

    if producto_id:
        base += " AND m.producto_id = ?"
        params.append(producto_id)

    if origen == 'compra':
        base += " AND m.referencia LIKE 'compra:%'"
    elif origen == 'manual':
        base += " AND m.referencia LIKE 'repo:%'"

    base += " ORDER BY m.fecha DESC"

    c.execute(base, params)
    rows = c.fetchall(); conn.close()

    si = io.StringIO(); writer = csv.writer(si)
    writer.writerow(['fecha', 'producto', 'codigo_barras', 'categoria',
                     'cantidad', 'costo_unit', 'valor_total', 'origen'])
    for (fecha, nombre, codigo, categoria, cant, costo, ref) in rows:
        valor = round((costo or 0) * cant, 2)
        origen_label = 'Compra' if ref and str(ref).startswith('compra:') else 'Reposición'
        writer.writerow([fecha, nombre, codigo, categoria, cant, costo or '', valor, origen_label])

    output = si.getvalue(); si.close()
    return Response(output, mimetype='text/csv',
                    headers={"Content-Disposition": "attachment; filename=reposiciones_filtrado.csv"})

# -------------------- Main --------------------
if __name__ == '__main__':
    app.run(debug=True)
