#!/usr/bin/env bash
# Passo de build da hospedagem. Encerra no primeiro erro para que uma migracao
# falha derrube o deploy em vez de subir um app pela metade.
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate --no-input
python manage.py load_curriculum
