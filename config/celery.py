import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Register the autonomous polling loop
app.conf.beat_schedule = {
    "poll-external-triggers-every-minute": {
        "task": "workflows.tasks.poll_external_triggers",
        "schedule": 60.0,  # Executes every 60 seconds
    },
}
