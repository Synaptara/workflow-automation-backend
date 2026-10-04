#!/usr/bin/env bash

python manage.py migrate

# Start the Celery Beat scheduler in the background (The Clock)
celery -A config beat -l info -S django &

# Start the Celery Worker in the background (The Muscle)
celery -A config worker -l info --concurrency=1 &

# Notice the ${PORT:-8000} syntax
daphne -b 0.0.0.0 -p "${PORT:-8000}" config.asgi:application
