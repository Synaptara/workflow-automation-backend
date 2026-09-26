#!/usr/bin/env bash

python manage.py migrate

celery -A config worker -l info --concurrency=1 &

# Notice the ${PORT:-8000} syntax
daphne -b 0.0.0.0 -p "${PORT:-8000}" config.asgi:application