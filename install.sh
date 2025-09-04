#!/usr/bin/env bash
set -e

# 1) Crear venv si no existe
if [ ! -d "venv" ]; then
  echo "📦 Creando entorno virtual (venv)..."
  python3 -m venv venv
else
  echo "✅ venv ya existe. Continuando..."
fi

# 2) Activar venv
source venv/bin/activate

# 3) Actualizar pip e instalar deps
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4) Crear .env a partir de .env.example si no existe
if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    cp .env.example .env
    echo "📝 Se creó .env a partir de .env.example"
  else
    echo "⚠️  No hay .env.example; créalo para configurar variables."
  fi
else
  echo "✅ .env ya existe. No se sobrescribe."
fi

echo "✅ Instalación lista. Ejecuta: ./run.sh"
