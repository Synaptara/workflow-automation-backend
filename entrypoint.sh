#!/bin/sh
set -e

# If DB_HOST is set, wait for PostgreSQL to become reachable
if [ -n "$DB_HOST" ]; then
  echo "Waiting for PostgreSQL at $DB_HOST:${DB_PORT:-5432}..."
  while ! nc -z "$DB_HOST" "${DB_PORT:-5432}"; do
    sleep 0.5
  done
  echo "PostgreSQL is online and ready."
fi

exec "$@"
