#!/usr/bin/env bash
set -euo pipefail
echo "[1/6] Backup..."
mkdir -p backups
cp data/app.db "backups/app.db.$(date +%F-%H%M%S).bak" 2>/dev/null || true

echo "[2/6] Re-crear data/app.db desde scripts/schema.sql (si existe)..."
rm -f data/app.db
if [ -f scripts/schema.sql ]; then
  sqlite3 data/app.db < scripts/schema.sql
else
  echo "Aviso: no hay scripts/schema.sql, seguimos con core."
  sqlite3 data/app.db "VACUUM;"
fi

echo "[3/6] Crear core (si faltara)..."
sqlite3 data/app.db < sql/010_core.sql

echo "[4/6] Atributos dinámicos..."
sqlite3 data/app.db < sql/020_dynamic_attrs.sql

echo "[5/6] Migración 030 (costos/COGS + vistas)..."
python3 scripts/migrate_030.py

echo "[6/6] Listo ✅"
