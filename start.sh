#!/usr/bin/env bash

python manage.py migrate

# Restrict Celery to exactly 1 background process to prevent memory crashes
celery -A config worker -l info --concurrency=1 &

daphne -b 0.0.0.0 -p $PORT config.asgi:application