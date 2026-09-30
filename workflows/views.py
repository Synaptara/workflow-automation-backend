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


import requests
from decouple import config
from django.contrib.auth.models import User
from rest_framework_simplejwt.tokens import RefreshToken


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class SocialAuthView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, provider):
        code = request.data.get("code")
        if not code:
            return Response(
                {"error": "No code provided"}, status=status.HTTP_400_BAD_REQUEST
            )

        email = None
        username = None
        frontend_url = config("FRONTEND_URL", default="http://localhost:5173")

        if provider == "google":
            token_res = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": config("GOOGLE_CLIENT_ID"),
                    "client_secret": config("GOOGLE_CLIENT_SECRET"),
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": f"{frontend_url}/auth/callback/google",
                },
                timeout=10,
            )
            if not token_res.ok:
                return Response(
                    {"error": "Failed to exchange Google token"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            access_token = token_res.json().get("access_token")

            user_res = requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
            user_data = user_res.json()
            email = user_data.get("email")
            username = email.split("@")[0] if email else None

        elif provider == "github":
            token_res = requests.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": config("GITHUB_CLIENT_ID"),
                    "client_secret": config("GITHUB_CLIENT_SECRET"),
                    "code": code,
                    "redirect_uri": f"{frontend_url}/auth/callback/github",
                },
                timeout=10,
            )
            if not token_res.ok:
                return Response(
                    {"error": "Failed to exchange GitHub token"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            access_token = token_res.json().get("access_token")

            user_res = requests.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
            user_data = user_res.json()
            username = user_data.get("login")
            email = user_data.get("email")

            if not email:
                email_res = requests.get(
                    "https://api.github.com/user/emails",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=10,
                )
                emails = email_res.json()
                primary_email = next((e for e in emails if e.get("primary")), None)
                if primary_email:
                    email = primary_email.get("email")

        else:
            return Response(
                {"error": "Invalid provider"}, status=status.HTTP_400_BAD_REQUEST
            )

        if not email:
            return Response(
                {"error": "Could not retrieve email from provider"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Secure User Matching Logic
        # Strict Provider Isolation Logic
        # This forces google_user@email.com and github_user@email.com to be two totally separate accounts.
        provider_username = f"{provider}_{email}"

        user = User.objects.filter(username=provider_username).first()

        if not user:
            user = User.objects.create_user(username=provider_username, email=email)

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            }
        )


def _validate_step(s):
    step_type = s.get("step_type")
    if step_type not in STEP_TYPES:
        return f"Invalid step_type: {step_type!r}"

    if step_type == "action":
        action_key = s.get("action_key", "")
        # FIX 1: Allow blank action_keys because our new UI drops them as unconfigured slates!
        if action_key and action_key not in EXECUTOR_REGISTRY:
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

    # FIX 2: We completely removed the `len(str(config)) > 5000` limit here.
    # Enterprise workflows (like AI Prompts and Email bodies) will regularly exceed 5KB!

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

        # Validate before wiping the database
        for s in steps_data:
            error = _validate_step(s)
            if error:
                return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
            if "client_id" not in s or not s["client_id"]:
                return Response(
                    {"detail": "Missing client_id in step data"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        workflow.steps.all().delete()
        id_map = {}
        created = []
        for s in steps_data:
            client_id = s["client_id"]
            obj = WorkflowStep.objects.create(
                workflow=workflow,
                client_id=client_id,
                step_type=s["step_type"],
                action_key=s.get("action_key", ""),
                app_event=s.get("app_event", ""),
                config=s.get("config", {}),
                branch=s.get("branch", ""),
                order=s.get("order", 0),
            )
            id_map[client_id] = obj
            created.append((s, obj))

        for s, obj in created:
            parent_client_id = s.get("parent_client_id")
            if parent_client_id and parent_client_id in id_map:
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

        # ... inside WorkflowViewSet ...

        @action(detail=False, methods=["get"])
        def templates(self, request):
            """Returns a list of pre-built workflow templates."""
            templates = [
                {
                    "id": "trello-to-discord",
                    "name": "Trello to Discord Alert",
                    "description": "Automatically send a Discord message when a new Trello card is created.",
                    "color": "#5865F2",
                    "steps": [
                        {
                            "client_id": "trigger_1",
                            "step_type": "trigger",
                            "action_key": "trello_new_card",
                            "config": {"ui_pos": {"x": 250, "y": 200}},
                        },
                        {
                            "client_id": "action_1",
                            "step_type": "action",
                            "action_key": "discord",
                            "config": {
                                "content": "New Trello Card Created: {{trigger.name}}\n{{trigger.url}}",
                                "ui_pos": {"x": 600, "y": 200},
                            },
                            "parent_client_id": "trigger_1",
                        },
                    ],
                },
                {
                    "id": "webhook-to-notion",
                    "name": "Save Webhook Data to Notion",
                    "description": "Listen for incoming data and log it directly into a Notion database as a new page.",
                    "color": "#000000",
                    "steps": [
                        {
                            "client_id": "trigger_1",
                            "step_type": "trigger",
                            "action_key": "webhook",
                            "config": {"ui_pos": {"x": 250, "y": 200}},
                        },
                        {
                            "client_id": "action_1",
                            "step_type": "action",
                            "action_key": "notion",
                            "config": {
                                "title": "New Webhook Alert",
                                "content": "Received Payload: {{trigger}}",
                                "ui_pos": {"x": 600, "y": 200},
                            },
                            "parent_client_id": "trigger_1",
                        },
                    ],
                },
            ]
            return Response(templates)

        @action(detail=False, methods=["post"])
        def use_template(self, request):
            """Clones a template into a real workflow for the authenticated user."""
            template_name = request.data.get("name", "New Workflow from Template")
            steps_data = request.data.get("steps", [])

            # Create the workflow
            workflow = Workflow.objects.create(owner=request.user, name=template_name)

            # Clone the steps
            id_map = {}
            created = []
            for s in steps_data:
                obj = WorkflowStep.objects.create(
                    workflow=workflow,
                    client_id=s.get("client_id", ""),
                    step_type=s["step_type"],
                    action_key=s.get("action_key", ""),
                    config=s.get("config", {}),
                )
                id_map[s["client_id"]] = obj
                created.append((s, obj))

            # Wire up the parent/child edges
            for s, obj in created:
                parent_client_id = s.get("parent_client_id")
                if parent_client_id:
                    obj.parent = id_map[parent_client_id]
                    obj.save(update_fields=["parent"])

            return Response(
                {"id": workflow.id, "name": workflow.name},
                status=status.HTTP_201_CREATED,
            )


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


class IntegrationOAuthView(APIView):
    """
    Handles OAuth callbacks for the Integrations Vault.
    Exchanges the authorization code for access/refresh tokens and stores them encrypted.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, provider):
        code = request.data.get("code")
        if not code:
            return Response(
                {"error": "No code provided"}, status=status.HTTP_400_BAD_REQUEST
            )

        frontend_url = config("FRONTEND_URL", default="http://localhost:5173")
        redirect_uri = f"{frontend_url}/integrations/callback/{provider}"
        credential_data = {}

        try:
            if provider == "github":
                token_res = requests.post(
                    "https://github.com/login/oauth/access_token",
                    headers={"Accept": "application/json"},
                    data={
                        "client_id": config("GITHUB_CLIENT_ID"),
                        "client_secret": config("GITHUB_CLIENT_SECRET"),
                        "code": code,
                        "redirect_uri": redirect_uri,
                    },
                    timeout=10,
                )
                if not token_res.ok:
                    return Response(
                        {"error": "GitHub token exchange failed"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                res_data = token_res.json()
                credential_data = {
                    "access_token": res_data.get("access_token"),
                    "token_type": res_data.get("token_type", "bearer"),
                    "scope": res_data.get("scope"),
                }

            elif provider == "google_sheets":
                token_res = requests.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": config("GOOGLE_CLIENT_ID"),
                        "client_secret": config("GOOGLE_CLIENT_SECRET"),
                        "code": code,
                        "grant_type": "authorization_code",
                        "redirect_uri": redirect_uri,
                    },
                    timeout=10,
                )
                if not token_res.ok:
                    return Response(
                        {"error": "Google token exchange failed"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                res_data = token_res.json()
                credential_data = {
                    "access_token": res_data.get("access_token"),
                    "refresh_token": res_data.get(
                        "refresh_token"
                    ),  # Crucial for background tasks
                    "token_type": res_data.get("token_type", "Bearer"),
                    "expires_in": res_data.get("expires_in"),
                }

            elif provider == "discord":
                token_res = requests.post(
                    "https://discord.com/api/oauth2/token",
                    data={
                        "client_id": config("DISCORD_CLIENT_ID"),
                        "client_secret": config("DISCORD_CLIENT_SECRET"),
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": redirect_uri,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=10,
                )
                if not token_res.ok:
                    return Response(
                        {"error": "Discord token exchange failed"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                res_data = token_res.json()
                credential_data = {
                    "access_token": res_data.get("access_token"),
                    "refresh_token": res_data.get("refresh_token"),
                    "token_type": res_data.get("token_type", "Bearer"),
                    "expires_in": res_data.get("expires_in"),
                }

            else:
                return Response(
                    {"error": "Unsupported integration provider"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Store the tokens in the Vault (automatically encrypted by EncryptedJSONField)
            if credential_data.get("access_token"):
                Credential.objects.update_or_create(
                    owner=request.user,
                    service=provider,
                    defaults={"data": credential_data},
                )
                return Response({"status": "success"})
            else:
                return Response(
                    {"error": "Token response did not contain an access_token"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except requests.RequestException as e:
            return Response(
                {"error": f"Network error during token exchange: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


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
