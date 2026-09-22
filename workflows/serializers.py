from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import Workflow, WorkflowStep, WorkflowRun, StepRun


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = User
        fields = ["id", "username", "email", "password"]

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class WorkflowStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowStep
        fields = ["id", "step_type", "action_key", "config", "parent", "branch", "order"]


class WorkflowSerializer(serializers.ModelSerializer):
    steps = WorkflowStepSerializer(many=True, read_only=True)
    webhook_url = serializers.SerializerMethodField()

    class Meta:
        model = Workflow
        fields = ["id", "name", "is_active", "created_at", "webhook_secret", "webhook_url", "steps"]
        read_only_fields = ["webhook_secret"]

    def get_webhook_url(self, obj):
        return f"/api/hooks/{obj.id}/{obj.webhook_secret}/"


class StepRunSerializer(serializers.ModelSerializer):
    step_type = serializers.CharField(source="step.step_type", read_only=True)
    action_key = serializers.CharField(source="step.action_key", read_only=True)

    class Meta:
        model = StepRun
        fields = ["id", "step", "step_type", "action_key", "status", "output", "error", "started_at", "finished_at"]


class WorkflowRunSerializer(serializers.ModelSerializer):
    step_runs = StepRunSerializer(many=True, read_only=True)

    class Meta:
        model = WorkflowRun
        fields = ["id", "status", "trigger_payload", "started_at", "finished_at", "step_runs"]
