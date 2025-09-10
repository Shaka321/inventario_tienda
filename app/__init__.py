import os
from flask import Flask
from .routes import bp
try:
    from .db import init_app as init_db
except Exception:
    init_db = None

def create_app():
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    app.config.from_mapping(
        SECRET_KEY='dev',
        DATABASE=os.path.join(app.instance_path, 'app.db'),
    )
    app.register_blueprint(bp)
    if init_db:
        try:
            init_db(app)
        except Exception:
            pass
    return app
