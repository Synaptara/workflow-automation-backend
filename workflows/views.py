import hashlib
import hmac
import json
import logging
import random

import requests
from decouple import config
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Prefetch
from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .condition import OPERATORS
from .executors import EXECUTOR_REGISTRY
from .models import (
    Announcement,
    AnnouncementRead,
    Credential,
    Notification,
    TaskUsage,
    Workflow,
    WorkflowRun,
    WorkflowStep,
)
from .serializers import (
    AnnouncementSerializer,
    NotificationSerializer,
    RegisterSerializer,
    WorkflowRunSerializer,
    WorkflowSerializer,
    WorkflowStepSerializer,
)
from .tasks import run_workflow

logger = logging.getLogger(__name__)

STEP_TYPES = {"trigger", "condition", "action"}


def _is_vault_error(msg: str) -> bool:
    lowered = msg.lower()
    return any(
        term in lowered
        for term in (
            "vault",
            "re-authenticate",
            "expired",
            "401",
            "unauthorized",
            "not connected",
        )
    )


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AnonRateThrottle]

    def create(self, request, *args, **kwargs):
        # QA-09 FIX: Validate username, email, and password fields FIRST
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data.get("email")
        submitted_otp = str(request.data.get("otp") or "").strip()

        if not submitted_otp:
            return Response(
                {"error": "OTP is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        cached_otp = cache.get(f"otp_{email}")
        if not cached_otp or cached_otp != submitted_otp:
            return Response(
                {"error": "Invalid or expired OTP"}, status=status.HTTP_400_BAD_REQUEST
            )

        cache.delete(f"otp_{email}")
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        response = Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )

        user = User.objects.get(email=email)
        TaskUsage.objects.get_or_create(user=user, defaults={"plan_type": "free"})

        return response


class SocialAuthView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, provider):
        code = request.data.get("code")
        if not code:
            return Response(
                {"error": "No code provided"}, status=status.HTTP_400_BAD_REQUEST
            )

        email = None
        is_verified = False
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
            is_verified = user_data.get("verified_email", False)

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

            email_res = requests.get(
                "https://api.github.com/user/emails",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
            emails = email_res.json() if email_res.ok else []
            primary_email = next(
                (e for e in emails if isinstance(e, dict) and e.get("primary")), None
            )

            if primary_email:
                email = primary_email.get("email")
                is_verified = primary_email.get("verified", False)

        else:
            return Response(
                {"error": "Invalid provider"}, status=status.HTTP_400_BAD_REQUEST
            )

        if not email:
            return Response(
                {"error": "Could not retrieve email from provider"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not is_verified:
            return Response(
                {
                    "error": "Unverified email addresses cannot be used for secure login."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        user = User.objects.filter(email=email).first()

        if not user:
            base_username = email.split("@")[0]
            username = base_username
            counter = 1

            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

            user = User.objects.create_user(username=username, email=email)

        TaskUsage.objects.get_or_create(user=user, defaults={"plan_type": "free"})

        refresh = RefreshToken.for_user(user)
        response = Response(
            {
                "access": str(refresh.access_token),
                "username": user.username,
            }
        )
        response.set_cookie(
            key="refresh_token",
            value=str(refresh),
            max_age=7 * 24 * 60 * 60,
            httponly=True,
            secure=not settings.DEBUG,
            samesite="None" if not settings.DEBUG else "Lax",
        )
        return response


def _validate_step(s):
    step_type = s.get("step_type")
    if step_type not in STEP_TYPES:
        return f"Invalid step_type: {step_type!r}"

    if step_type == "action":
        action_key = s.get("action_key", "")
        if action_key and action_key not in EXECUTOR_REGISTRY:
            return f"Unknown action_key: {action_key!r} (available: {list(EXECUTOR_REGISTRY)})"

    if step_type == "condition":
        config_obj = s.get("config", {})
        if not isinstance(config_obj, dict):
            return "Condition config must be an object"
        operator = config_obj.get("operator", "==")
        if operator not in OPERATORS:
            return f"Unsupported operator: {operator!r}"

    config_obj = s.get("config", {})
    if not isinstance(config_obj, dict):
        return "config must be an object"

    return None


class WorkflowViewSet(viewsets.ModelViewSet):
    serializer_class = WorkflowSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Workflow.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        workflow_count = Workflow.objects.filter(owner=self.request.user).count()
        usage, _ = TaskUsage.objects.get_or_create(user=self.request.user)

        if usage.plan_type == "free" and workflow_count >= 2:
            raise PermissionDenied(
                "Free plan limit reached. Please upgrade to create more than 2 workflows."
            )

        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["put"], url_path="steps")
    def save_steps(self, request, pk=None):
        workflow = self.get_object()
        steps_data = request.data.get("steps", [])

        for s in steps_data:
            error = _validate_step(s)
            if error:
                return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
            if "client_id" not in s or not s["client_id"]:
                return Response(
                    {"detail": "Missing client_id in step data"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            with transaction.atomic():
                existing = {st.client_id: st for st in workflow.steps.all()}
                id_map, created = {}, []
                for s in steps_data:
                    cid = s["client_id"]
                    fields = dict(
                        step_type=s["step_type"],
                        action_key=s.get("action_key", ""),
                        app_event=s.get("app_event", ""),
                        config=s.get("config", {}),
                        branch=s.get("branch", ""),
                        order=s.get("order", 0),
                        parent=None,
                    )
                    obj = existing.get(cid)
                    if obj:
                        for k, v in fields.items():
                            setattr(obj, k, v)
                        obj.save()
                    else:
                        obj = WorkflowStep.objects.create(
                            workflow=workflow, client_id=cid, **fields
                        )
                    id_map[cid] = obj
                    created.append((s, obj))
                workflow.steps.exclude(client_id__in=id_map.keys()).delete()

                for s, obj in created:
                    parent_client_id = s.get("parent_client_id")
                    if parent_client_id and parent_client_id in id_map:
                        obj.parent = id_map[parent_client_id]
                        obj.save(update_fields=["parent"])

                for s, obj in created:
                    if (
                        obj.step_type == "trigger"
                        and obj.action_key in EXECUTOR_REGISTRY
                    ):
                        executor = EXECUTOR_REGISTRY[obj.action_key]

                        if hasattr(executor, "register_webhook"):
                            vault_creds = Credential.objects.filter(
                                owner=request.user, service=obj.action_key
                            ).first()

                            step_config = (
                                dict(obj.config) if isinstance(obj.config, dict) else {}
                            )
                            if vault_creds and isinstance(vault_creds.data, dict):
                                step_config.update(vault_creds.data)

                            backend_url = config(
                                "BACKEND_URL", default="https://api.orkflo.com"
                            ).rstrip("/")
                            webhook_url = f"{backend_url}/api/webhooks/{workflow.id}/{workflow.webhook_secret}/"

                            executor.register_webhook(
                                obj.app_event, step_config, webhook_url
                            )

        except ValueError as e:
            msg = str(e)
            needs_vault = _is_vault_error(msg)
            return Response(
                {
                    "detail": msg,
                    "code": "vault_auth_required"
                    if needs_vault
                    else "validation_error",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            logger.exception("save_steps failed for workflow %s", workflow.id)
            return Response(
                {"detail": "An unexpected error occurred while saving."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

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
            .prefetch_related("step_runs__step")
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
        # Only return services that have valid, non-empty decrypted credential data
        creds = Credential.objects.filter(owner=request.user)
        return Response(
            [c.service for c in creds if isinstance(c.data, dict) and bool(c.data)]
        )

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
                    "refresh_token": res_data.get("refresh_token"),
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
    """Returns the user's current billing, task usage metrics, and workflow limits."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        usage, _ = TaskUsage.objects.get_or_create(user=request.user)
        workflow_count = request.user.workflows.count()
        percent = (
            min(100, int((usage.count / usage.limit) * 100)) if usage.limit > 0 else 0
        )

        plan_type = getattr(usage, "plan_type", "free").lower()
        workflow_limit = 2 if plan_type == "free" else "Unlimited"

        return Response(
            {
                "plan": plan_type.capitalize(),
                "count": usage.count,
                "limit": usage.limit,
                "percentage": percent,
                "task_count": usage.count,
                "task_limit": usage.limit,
                "task_percentage": percent,
                "workflow_count": workflow_count,
                "workflow_limit": workflow_limit,
            }
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

        usage = TaskUsage.objects.filter(user=workflow.owner).first()
        if usage and usage.limit and usage.count >= usage.limit:
            return Response(
                {"detail": "Task limit reached."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        payload = request.data
        trigger_step = workflow.steps.filter(step_type="trigger").first()

        if trigger_step and trigger_step.action_key in EXECUTOR_REGISTRY:
            executor = EXECUTOR_REGISTRY[trigger_step.action_key]
            if hasattr(executor, "normalize_payload"):
                payload = executor.normalize_payload(trigger_step.app_event, payload)

        run = WorkflowRun.objects.create(workflow=workflow, trigger_payload=payload)
        run_workflow.delay(str(run.id))
        return Response({"run_id": str(run.id)}, status=status.HTTP_202_ACCEPTED)


class SendOTPView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "otp"

    def post(self, request):
        from django.core.exceptions import ValidationError
        from django.core.validators import validate_email

        email = str(request.data.get("email") or "").strip().lower()
        if not email:
            return Response(
                {"error": "Email is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_email(email)
        except ValidationError:
            return Response(
                {"error": "Enter a valid email address"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if User.objects.filter(email__iexact=email).exists():
            return Response(
                {"error": "Email already registered"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # QA-07 FIX: Per-email 60s cooldown + 5/hour cap in Redis to stop mail-bombing
        cooldown_key = f"otp_cooldown_{email}"
        hourly_key = f"otp_hourly_{email}"
        if cache.get(cooldown_key):
            return Response(
                {"error": "Please wait 60 seconds before requesting another code."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        sent_count = cache.get(hourly_key, 0)
        if sent_count >= 5:
            return Response(
                {
                    "error": "Too many OTP requests for this email. Try again in an hour."
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        otp = str(random.randint(100000, 999999))
        cache.set(f"otp_{email}", otp, timeout=600)
        cache.set(cooldown_key, True, timeout=60)
        cache.set(hourly_key, sent_count + 1, timeout=3600)

        send_mail(
            "Verify your Orkflo account",
            f"Your verification code is: {otp}. It expires in 10 minutes.",
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
        )
        return Response({"status": "OTP sent successfully"})


class UniversalIngressView(APIView):
    """
    The central ingestion funnel for all high-volume external events (Discord, Slack, etc.).
    Handles deduplication and drops payloads directly into the Celery Queue.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = []

    def post(self, request, source):
        expected = config("INGRESS_SECRET", default="")
        if not expected or not hmac.compare_digest(
            request.headers.get("X-Ingress-Secret", ""), expected
        ):
            return Response(status=status.HTTP_403_FORBIDDEN)

        payload = request.data
        event_id = payload.get("id") or payload.get("event_id")

        if not event_id:
            payload_str = json.dumps(payload, sort_keys=True).encode("utf-8")
            event_id = hashlib.sha256(payload_str).hexdigest()

        cache_key = f"ingress_{source}_{event_id}"
        if cache.get(cache_key):
            return Response(
                {"status": "ignored", "reason": "duplicate"}, status=status.HTTP_200_OK
            )

        cache.set(cache_key, True, timeout=600)

        from .tasks import route_ingested_event

        route_ingested_event.delay(source, payload)

        return Response(
            {"status": "queued", "event_id": event_id}, status=status.HTTP_202_ACCEPTED
        )


class SecureLoginView(TokenObtainPairView):
    throttle_classes = [AnonRateThrottle]

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        refresh_token = response.data.get("refresh")

        if refresh_token:
            del response.data["refresh"]
            response.set_cookie(
                key="refresh_token",
                value=refresh_token,
                max_age=7 * 24 * 60 * 60,
                httponly=True,
                secure=not settings.DEBUG,
                samesite="None" if not settings.DEBUG else "Lax",
            )
        return response


class SecureRefreshView(TokenRefreshView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "token_refresh"

    def post(self, request, *args, **kwargs):
        refresh_token = request.COOKIES.get("refresh_token")

        if not refresh_token:
            return Response(
                {"detail": "Refresh cookie missing."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = self.get_serializer(data={"refresh": refresh_token})

        try:
            serializer.is_valid(raise_exception=True)
        except Exception:
            return Response(
                {"detail": "Refresh token expired or invalid."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        response = Response(serializer.validated_data, status=status.HTTP_200_OK)

        new_refresh = serializer.validated_data.get("refresh")
        if new_refresh:
            if "refresh" in response.data:
                del response.data["refresh"]

            response.set_cookie(
                key="refresh_token",
                value=new_refresh,
                max_age=7 * 24 * 60 * 60,
                httponly=True,
                secure=not settings.DEBUG,
                samesite="None" if not settings.DEBUG else "Lax",
            )

        return response


class TestTriggerView(APIView):
    """
    Live Data Fetcher for the Workflow Builder.
    Dynamically routes to the correct integration to fetch recent test data,
    using the user's encrypted Vault credentials.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        action_key = request.data.get("action_key")
        app_event = request.data.get("app_event")
        config_data = dict(request.data.get("config") or {})

        if not action_key or not app_event:
            return Response(
                {"detail": "Missing action_key or app_event"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if action_key not in EXECUTOR_REGISTRY:
            return Response(
                {"detail": f"Unsupported integration: {action_key}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        vault_creds = Credential.objects.filter(
            owner=request.user, service=action_key
        ).first()
        if vault_creds and isinstance(vault_creds.data, dict):
            config_data.update(vault_creds.data)

        executor = EXECUTOR_REGISTRY[action_key]

        try:
            test_data = executor.fetch_test_data(app_event, config_data)
            return Response(test_data, status=status.HTTP_200_OK)
        except NotImplementedError:
            return Response(
                {"detail": "Live fetching is not yet supported for this integration."},
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )
        except ValueError as e:
            msg = str(e)
            needs_vault = _is_vault_error(msg)
            return Response(
                {
                    "detail": msg,
                    "error": msg,
                    "code": "vault_auth_required"
                    if needs_vault
                    else "validation_error",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            logger.exception("TestTriggerView failed for %s", action_key)
            return Response(
                {"detail": "Failed to fetch test data."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class NotificationViewSet(viewsets.ViewSet):
    """Handles fetching and reading notifications & announcements."""

    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        user = request.user
        unread_only = request.query_params.get("unread") == "1"

        notifs_qs = Notification.objects.filter(user=user)
        if unread_only:
            notifs_qs = notifs_qs.filter(is_read=False)
        notifs = NotificationSerializer(notifs_qs[:50], many=True).data

        read_prefetch = Prefetch(
            "announcementread_set",
            queryset=AnnouncementRead.objects.filter(user=user),
            to_attr="user_reads",
        )
        announcements_qs = Announcement.objects.prefetch_related(read_prefetch)

        announcements_data = []
        for ann in announcements_qs[:20]:
            is_read = len(ann.user_reads) > 0
            if unread_only and is_read:
                continue
            ann.read_by_user = is_read
            announcements_data.append(
                AnnouncementSerializer(ann, context={"request": request}).data
            )

        combined = notifs + announcements_data
        combined.sort(key=lambda x: x["created_at"], reverse=True)

        return Response(combined[:50])

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        user = request.user
        notif_count = Notification.objects.filter(user=user, is_read=False).count()

        total_announcements = Announcement.objects.count()
        read_announcements = AnnouncementRead.objects.filter(user=user).count()
        unread_announcements = max(0, total_announcements - read_announcements)

        return Response({"unread_count": notif_count + unread_announcements})

    @action(detail=True, methods=["post"], url_path="read")
    def mark_read(self, request, pk=None):
        user = request.user

        if Announcement.objects.filter(id=pk).exists():
            AnnouncementRead.objects.get_or_create(user=user, announcement_id=pk)
            return Response({"status": "read"})

        Notification.objects.filter(user=user, id=pk).update(is_read=True)
        return Response({"status": "read"})

    @action(detail=False, methods=["post"], url_path="read-all")
    def mark_all_read(self, request):
        user = request.user
        Notification.objects.filter(user=user, is_read=False).update(is_read=True)

        announcements = Announcement.objects.all()
        reads_to_create = []
        existing_reads = set(
            AnnouncementRead.objects.filter(user=user).values_list(
                "announcement_id", flat=True
            )
        )

        for ann in announcements:
            if ann.id not in existing_reads:
                reads_to_create.append(AnnouncementRead(user=user, announcement=ann))

        if reads_to_create:
            AnnouncementRead.objects.bulk_create(reads_to_create)

        return Response({"status": "all_read"})


class RunDetailView(generics.RetrieveAPIView):
    serializer_class = WorkflowRunSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            WorkflowRun.objects.filter(workflow__owner=self.request.user)
            .select_related("workflow")
            .prefetch_related("step_runs__step")
        )


class LogoutView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = []

    def post(self, request):
        res = Response(status=status.HTTP_204_NO_CONTENT)
        res.delete_cookie(
            "refresh_token", samesite="None" if not settings.DEBUG else "Lax"
        )
        return res
