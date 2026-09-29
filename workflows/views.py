import json

from django_celery_beat.models import IntervalSchedule, PeriodicTask
from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .condition import OPERATORS
from .executors import EXECUTOR_REGISTRY
from .models import Credential, TaskUsage, Workflow, WorkflowRun, WorkflowStep
from .serializers import (
    RegisterSerializer,
    WorkflowRunSerializer,
    WorkflowSerializer,
    WorkflowStepSerializer,
)
from .tasks import run_workflow

STEP_TYPES = {"trigger", "condition", "action"}


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


def _validate_step(s):
    step_type = s.get("step_type")
    if step_type not in STEP_TYPES:
        return f"Invalid step_type: {step_type!r}"

    if step_type == "action":
        action_key = s.get("action_key", "")
        if action_key not in EXECUTOR_REGISTRY:
            return f"Unknown action_key: {action_key!r} (available: {list(EXECUTOR_REGISTRY)})"

    if step_type == "condition":
        config = s.get("config", {})
        if not isinstance(config, dict):
            return "Condition config must be an object"
        operator = config.get("operator", "==")
        if operator not in OPERATORS:
            return f"Unsupported operator: {operator!r}"

    config = s.get("config", {})
    if not isinstance(config, dict):
        return "config must be an object"
    if len(str(config)) > 5000:
        return "config is too large (max ~5000 chars)"

    return None


class WorkflowViewSet(viewsets.ModelViewSet):
    serializer_class = WorkflowSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Workflow.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["put"], url_path="steps")
    def save_steps(self, request, pk=None):
        workflow = self.get_object()
        steps_data = request.data.get("steps", [])

        for s in steps_data:
            error = _validate_step(s)
            if error:
                return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        workflow.steps.all().delete()
        id_map = {}
        created = []
        for s in steps_data:
            obj = WorkflowStep.objects.create(
                workflow=workflow,
                client_id=s.get("client_id", ""),
                step_type=s["step_type"],
                action_key=s.get("action_key", ""),
                config=s.get("config", {}),
                branch=s.get("branch", ""),
                order=s.get("order", 0),
            )
            id_map[s["client_id"]] = obj
            created.append((s, obj))

        for s, obj in created:
            parent_client_id = s.get("parent_client_id")
            if parent_client_id:
                obj.parent = id_map[parent_client_id]
                obj.save(update_fields=["parent"])

        has_schedule = False
        for s, obj in created:
            if obj.step_type == "trigger" and obj.action_key == "schedule":
                has_schedule = True
                interval_minutes = int(obj.config.get("interval", 15))
                schedule, _ = IntervalSchedule.objects.get_or_create(
                    every=interval_minutes,
                    period=IntervalSchedule.MINUTES,
                )
                PeriodicTask.objects.update_or_create(
                    name=f"workflow-schedule-{workflow.id}",
                    defaults={
                        "interval": schedule,
                        "task": "workflows.tasks.trigger_scheduled_workflow",
                        "args": json.dumps([str(workflow.id)]),
                        "enabled": workflow.is_active,
                    },
                )
                break

        if not has_schedule:
            PeriodicTask.objects.filter(
                name=f"workflow-schedule-{workflow.id}"
            ).delete()

        return Response(WorkflowStepSerializer(workflow.steps.all(), many=True).data)

    @action(detail=True, methods=["get"], url_path="runs")
    def runs(self, request, pk=None):
        workflow = self.get_object()
        runs = workflow.runs.order_by("-started_at")[:50]
        return Response(WorkflowRunSerializer(runs, many=True).data)


class GlobalRunHistoryView(generics.ListAPIView):
    """Fetches the 100 most recent runs across ALL of the user's workflows."""

    serializer_class = WorkflowRunSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            WorkflowRun.objects.filter(workflow__owner=self.request.user)
            .select_related("workflow")
            .order_by("-started_at")[:100]
        )


class CredentialViewSet(viewsets.ViewSet):
    """Manages the encrypted Integrations Vault."""

    permission_classes = [permissions.IsAuthenticated]

    def create(self, request):
        service = request.data.get("service")
        data = request.data.get("data", {})
        if not service:
            return Response(
                {"error": "Service name required"}, status=status.HTTP_400_BAD_REQUEST
            )

        Credential.objects.update_or_create(
            owner=request.user, service=service, defaults={"data": data}
        )
        return Response({"status": "success"})

    def list(self, request):
        # Only return the keys/service names, never the decrypted payloads
        creds = Credential.objects.filter(owner=request.user)
        return Response([c.service for c in creds])

    def destroy(self, request, pk=None):
        Credential.objects.filter(owner=request.user, service=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TaskUsageView(APIView):
    """Returns the user's current billing/task usage metrics."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        usage, _ = TaskUsage.objects.get_or_create(user=request.user)
        percent = (
            min(100, int((usage.count / usage.limit) * 100)) if usage.limit > 0 else 0
        )
        return Response(
            {"count": usage.count, "limit": usage.limit, "percentage": percent}
        )


class WebhookTriggerView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "webhook"

    def post(self, request, workflow_id, secret):
        content_length = request.META.get("CONTENT_LENGTH")
        if content_length and int(content_length) > 1024 * 1024:
            return Response(
                {"detail": "Payload too large."},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        if not isinstance(request.data, dict):
            return Response(
                {"detail": "Expected JSON object."}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            workflow = Workflow.objects.get(
                id=workflow_id, webhook_secret=secret, is_active=True
            )
        except Workflow.DoesNotExist:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        run = WorkflowRun.objects.create(
            workflow=workflow, trigger_payload=request.data
        )
        run_workflow.delay(str(run.id))
        return Response({"run_id": str(run.id)}, status=status.HTTP_202_ACCEPTED)
