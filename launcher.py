# launcher.py
import os
import sys
import pathlib
from app import create_app

def ensure_env(base_dir: pathlib.Path):
    env_path = base_dir / ".env"
    example = base_dir / ".env.example"
    if (not env_path.exists()) and example.exists():
        try:
            env_path.write_text(example.read_text(), encoding="utf-8")
        except Exception:
            pass

def get_base_dir() -> pathlib.Path:
    # En binario (--onefile), sys.executable apunta al ejecutable real.
    # En modo "código", usamos __file__.
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent

def main():
    base_dir = get_base_dir()

    # Asegura data/ y .env al lado del ejecutable
    data_dir = base_dir / "data"
    data_dir.mkdir(exist_ok=True)
    ensure_env(base_dir)

    # Forzar DB dentro de data/ del ejecutable (ideal para USB)
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{data_dir.as_posix()}/app.db")

    # Host/Port por defecto
    os.environ.setdefault("HOST", "0.0.0.0")
    os.environ.setdefault("PORT", "5000")

    app = create_app()
    app.run(host=os.environ["HOST"], port=int(os.environ["PORT"]))

if __name__ == "__main__":
    main()
