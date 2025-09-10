@echo off
setlocal
cd /d %~dp0
py -3 -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist instance mkdir instance
py scripts\reset_data_only.py
py scripts\migrate_030.py
py scripts\migrate_040_product_size_variant.py
py scripts\migrate_040_variantes.py
py -c "import sqlite3 as s; from werkzeug.security import generate_password_hash as g; import os; os.makedirs('instance', exist_ok=True); db=s.connect('instance/app.db'); db.execute('CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY, email TEXT UNIQUE, nombre TEXT, pass_hash TEXT)'); db.execute('INSERT OR IGNORE INTO usuarios (email,nombre,pass_hash) VALUES (?,?,?)', ('admin@local','admin', g('admin123'))); db.commit(); db.close()"
echo Listo. Ejecuta run.bat
