import os
from flask import Flask
from flask_login import LoginManager
from .routes import bp

try:
    from .db import init_app as init_db, get_db
except Exception:
    init_db = None
    from .db import get_db  # si al menos existe get_db

try:
    from .user import User
except Exception:
    User = None

def create_app():
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)

    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev"),
        DATABASE=os.path.join(app.instance_path, "app.db"),
    )

    # Registrar blueprints
    app.register_blueprint(bp)

    # Inicializar DB si hay hook
    if init_db:
        try:
            init_db(app)
        except Exception:
            pass

    # ---- Flask-Login ----
    login_manager = LoginManager()
    login_manager.login_view = "main.login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id: str):
        if not User:
            return None
        try:
            db = get_db()
            row = db.execute(
                "SELECT id, email, nombre FROM usuarios WHERE id=?",
                (user_id,)
            ).fetchone()
            if row:
                return User(row["id"], row["email"], row["nombre"])
        except Exception:
            return None
        return None

    return app
