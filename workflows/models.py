import uuid
from django.db import models
from django.contrib.auth.models import User


class Workflow(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="workflows")
    name = models.CharField(max_length=255)
    webhook_secret = models.CharField(max_length=64, default=uuid.uuid4)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class WorkflowStep(models.Model):
    STEP_TYPES = [("trigger", "Trigger"), ("condition", "Condition"), ("action", "Action")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="steps")
    step_type = models.CharField(max_length=20, choices=STEP_TYPES)
    action_key = models.CharField(max_length=50, blank=True)  # "slack", "trello", "payment"
    config = models.JSONField(default=dict, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    branch = models.CharField(max_length=10, blank=True)  # "true" / "false" / ""
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.workflow.name} · {self.step_type}"


class WorkflowRun(models.Model):
    STATUS = [("pending", "Pending"), ("running", "Running"), ("success", "Success"), ("failed", "Failed")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="runs")
    status = models.CharField(max_length=20, choices=STATUS, default="pending")
    trigger_payload = models.JSONField(default=dict)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)


class StepRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(WorkflowRun, on_delete=models.CASCADE, related_name="step_runs")
    step = models.ForeignKey(WorkflowStep, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, default="pending")
    output = models.JSONField(default=dict)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)


class Credential(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="credentials")
    service = models.CharField(max_length=50)  # "slack", "trello", "stripe"
    data = models.JSONField(default=dict)  # encrypt this before the Day 5 hardening pass
    created_at = models.DateTimeField(auto_now_add=True)
