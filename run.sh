#!/usr/bin/env bash
set -e

# Asegurar venv
if [ ! -d "venv" ]; then
  echo "❌ No existe 'venv'. Corre primero: ./install.sh"
  exit 1
fi

# Activar venv
source venv/bin/activate

# Exportar variables para Flask
export FLASK_APP=app:create_app
# Si PORT/HOST no están en .env, usa defaults:
export FLASK_RUN_PORT=${PORT:-5000}
export FLASK_RUN_HOST=${HOST:-0.0.0.0}

# Levantar
flask run
