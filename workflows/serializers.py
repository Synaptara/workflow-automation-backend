from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import (
    Announcement,
    Notification,
    StepRun,
    Workflow,
    WorkflowRun,
    WorkflowStep,
)


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = User
        fields = ["id", "username", "email", "password"]

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class WorkflowStepSerializer(serializers.ModelSerializer):
    parent_client_id = serializers.CharField(source="parent.client_id", read_only=True)

    # CRITICAL FIX: Tell DRF to serve this as pure JSON, not a string!
    config = serializers.JSONField(required=False)

    class Meta:
        model = WorkflowStep
        fields = [
            "client_id",
            "step_type",
            "action_key",
            "app_event",
            "config",
            "parent_client_id",
            "branch",
            "order",
        ]


class WorkflowSerializer(serializers.ModelSerializer):
    steps = WorkflowStepSerializer(many=True, read_only=True)
    webhook_url = serializers.SerializerMethodField()

    class Meta:
        model = Workflow
        fields = [
            "id",
            "name",
            "is_active",
            "created_at",
            "webhook_url",
            "steps",
        ]

    def get_webhook_url(self, obj):
        return f"/api/hooks/{obj.id}/{obj.webhook_secret}/"


class StepRunSerializer(serializers.ModelSerializer):
    step_type = serializers.CharField(source="step.step_type", read_only=True)
    action_key = serializers.CharField(source="step.action_key", read_only=True)

    class Meta:
        model = StepRun
        fields = [
            "id",
            "step",
            "step_type",
            "action_key",
            "status",
            "output",
            "error",
            "started_at",
            "finished_at",
        ]


class WorkflowRunSerializer(serializers.ModelSerializer):
    step_runs = StepRunSerializer(many=True, read_only=True)
    # 1. Reach across the foreign key to grab the actual workflow name
    workflow_name = serializers.CharField(source="workflow.name", read_only=True)

    class Meta:
        model = WorkflowRun
        fields = [
            "id",
            "workflow",  # Keep the ID for linking
            "workflow_name",  # 2. Add the new name field here
            "status",
            "trigger_payload",
            "started_at",
            "finished_at",
            "step_runs",
        ]


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            "id",
            "type",
            "title",
            "body",
            "link",
            "data",
            "is_read",
            "created_at",
        ]


class AnnouncementSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()
    is_read = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(source="published_at")

    class Meta:
        model = Announcement
        fields = ["id", "type", "title", "body", "link", "is_read", "created_at"]

    def get_type(self, obj):
        return "product"

    def get_is_read(self, obj):
        user = self.context.get("request").user
        if not user or not user.is_authenticated:
            return False
        # If it exists in the tracking table, they've read it
        return hasattr(obj, "read_by_user") and obj.read_by_user
