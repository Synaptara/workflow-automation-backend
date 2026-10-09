#!/usr/bin/env bash

# Trap SIGINT (Ctrl+C) and kill all background jobs spawned by this script
trap 'kill $(jobs -p)' SIGINT SIGTERM EXIT

python manage.py migrate

echo "Starting Celery Beat..."
celery -A config beat -l info -S django &

echo "Starting Celery Worker..."
celery -A config worker -l info --concurrency=1 &

echo "Starting Daphne..."
daphne -b 0.0.0.0 -p "${PORT:-8000}" config.asgi:application
