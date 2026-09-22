#!/usr/bin/env bash

# Run database migrations just in case
python manage.py migrate

# Start the Celery worker in the background (notice the & at the end)
celery -A config worker -l info &

# Start the Daphne web server in the foreground
daphne -b 0.0.0.0 -p $PORT config.asgi:application