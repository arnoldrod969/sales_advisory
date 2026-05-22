#!/bin/sh
set -eu

echo "Attente de la base MySQL ${DB_HOST:-db}:${DB_PORT:-3306}..."
while ! nc -z "${DB_HOST:-db}" "${DB_PORT:-3306}"; do
  sleep 2
done

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers ${GUNICORN_WORKERS:-3} \
  --timeout ${GUNICORN_TIMEOUT:-120}
