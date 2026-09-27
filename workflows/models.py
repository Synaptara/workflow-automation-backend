import uuid
import json
import base64
import hashlib
from cryptography.fernet import Fernet
from django.db import models
from django.conf import settings
from django.contrib.auth.models import User

# Generate a reliable 32-byte Fernet key from Django's SECRET_KEY
_key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
_fernet = Fernet(_key)

class EncryptedJSONField(models.TextField):
    """Stores JSON dictionaries as AES-256 encrypted strings in the database."""
    
    def get_prep_value(self, value):
        if value is None:
            return value
        if not isinstance(value, str):
            value = json.dumps(value)
        # Encrypt the string and save it to the database
        return _fernet.encrypt(value.encode('utf-8')).decode('utf-8')

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        try:
            # Attempt to decrypt
            decrypted = _fernet.decrypt(value.encode('utf-8')).decode('utf-8')
            return json.loads(decrypted)
        except Exception:
            # Graceful fallback: If it fails to decrypt, it's likely old plaintext data
            try:
                return json.loads(value)
            except Exception:
                return {}

    def to_python(self, value):
        if isinstance(value, (dict, list)) or value is None:
            return value
        return self.from_db_value(value, None, None)


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
    client_id = models.CharField(max_length=50, blank=True)
    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="steps")
    step_type = models.CharField(max_length=20, choices=STEP_TYPES)
    action_key = models.CharField(max_length=50, blank=True)
    
    # ENCRYPTED: Uses our new custom field
    config = EncryptedJSONField(default=dict, blank=True)
    
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    branch = models.CharField(max_length=10, blank=True)
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
    service = models.CharField(max_length=50)
    
    # ENCRYPTED: Uses our new custom field
    data = EncryptedJSONField(default=dict)
    
    created_at = models.DateTimeField(auto_now_add=True)