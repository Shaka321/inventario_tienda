# Inventario Tienda (Flask)

Aplicación de inventario y finanzas con Flask.
Este repositorio se clona sin datos (DB y backups ignorados). Cada usuario crea su propia base local.

REQUISITOS
- Python 3.9+ (recomendado 3.10+)
- pip
- git

INSTALACIÓN RÁPIDA (Linux / macOS / WSL)
1) git clone https://github.com/Shaka321/inventario_tienda.git
2) cd inventario_tienda
3) python3 -m venv .venv
4) . .venv/bin/activate
5) pip install -r requirements.txt
6) python scripts/reset_data_only.py
7) python scripts/migrate_030.py
8) python scripts/migrate_040_product_size_variant.py
9) python scripts/migrate_040_variantes.py
10) export FLASK_APP=app_finance.py
11) flask run

INSTALACIÓN RÁPIDA (Windows PowerShell)
1) git clone https://github.com/Shaka321/inventario_tienda.git
2) cd inventario_tienda
3) py -3 -m venv .venv
4) .\.venv\Scripts\Activate.ps1
5) pip install -r requirements.txt
6) py scripts\reset_data_only.py
7) py scripts\migrate_030.py
8) py scripts\migrate_040_product_size_variant.py
9) py scripts\migrate_040_variantes.py
10) $env:FLASK_APP="app_finance.py"
11) flask run

LIMPIO DE DATOS
- Se ignoran: instance/, *.db, backups/
- Cada clon empieza sin datos y cada persona carga sus propios productos/gastos.

PROBLEMAS FRECUENTES
- “No encuentra app o routes.py”: asegúrate de estar en la raíz y exportar FLASK_APP=app_finance.py.
- Error al activar venv en Windows: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force.
- Faltan dependencias: pip install -r requirements.txt.
