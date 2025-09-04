# app/__init__.py
import os
from flask import Flask
from dotenv import load_dotenv
from flask_login import LoginManager
from werkzeug.security import generate_password_hash
from .db import init_db_if_needed, get_db

def create_app():
    load_dotenv()
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))  # carpeta app/

    # Usamos las carpetas DENTRO de app/
    app = Flask(
        __name__,
        template_folder=os.path.join(BASE_DIR, "templates"),
        static_folder=os.path.join(BASE_DIR, "static"),
    )
    app.config["SECRET_KEY"]   = os.getenv("SECRET_KEY", "dev-key")
    app.config["DATABASE_URL"] = os.getenv("DATABASE_URL", "sqlite:///data/app.db")

    # Rutas (Blueprint)
    from .routes import bp as routes_bp
    app.register_blueprint(routes_bp)

    # DB garantizada
    os.makedirs("data", exist_ok=True)
    init_db_if_needed(app)

    # ---- Flask-Login ----
    login_manager = LoginManager()
    login_manager.login_view = "main.login"   # endpoint del login
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        # Importamos aquí para evitar ciclos y para que PyInstaller resuelva bien
        from .user import User
        db = get_db()
        row = db.execute(
            "SELECT id, email, nombre FROM usuarios WHERE id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        return User(row["id"], row["email"], row["nombre"])

    # Admin por defecto si no existe (admin@example.com / admin123)
    with app.app_context():
        db = get_db()
        row = db.execute(
            "SELECT id FROM usuarios WHERE email=?",
            ("admin@example.com",)
        ).fetchone()
        if not row:
            db.execute(
                "INSERT INTO usuarios (email, nombre, pass_hash) VALUES (?,?,?)",
                ("admin@example.com", "Admin", generate_password_hash("admin123")),
            )
            db.commit()

    # Cierra conexión al final del request
    @app.teardown_appcontext
    def close_connection(exception):
        db = getattr(get_db, "_conn", None)
        if db is not None:
            db.close()
            get_db._conn = None

    return app
