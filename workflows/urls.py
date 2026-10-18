from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    CheckoutSessionView,  # NEW
    CredentialViewSet,
    DodoWebhookView,  # NEW
    GlobalRunHistoryView,
    IntegrationOAuthView,
    LogoutView,
    NotificationViewSet,
    RegisterView,
    RunDetailView,
    SecureLoginView,
    SecureRefreshView,
    SendOTPView,
    SocialAuthView,
    TaskUsageView,
    TestTriggerView,
    UniversalIngressView,
    WebhookTriggerView,
    WebSocketTicketView,
    WorkflowViewSet,
)

router = DefaultRouter()
router.register("workflows", WorkflowViewSet, basename="workflow")
router.register("credentials", CredentialViewSet, basename="credentials")
router.register("notifications", NotificationViewSet, basename="notifications")

urlpatterns = [
    path("auth/register/", RegisterView.as_view()),
    path("auth/login/", SecureLoginView.as_view()),
    path("auth/refresh/", SecureRefreshView.as_view()),
    path("auth/ws-ticket/", WebSocketTicketView.as_view(), name="ws-ticket"),
    path("auth/social/<str:provider>/", SocialAuthView.as_view()),
    path("credentials/oauth/<str:provider>/", IntegrationOAuthView.as_view()),
    path(
        "webhooks/<uuid:workflow_id>/<str:secret>/",
        WebhookTriggerView.as_view(),
        name="webhook_trigger",
    ),
    path(
        "hooks/<uuid:workflow_id>/<str:secret>/",
        WebhookTriggerView.as_view(),
        name="webhook_trigger_alias",
    ),
    path(
        "ingress/<str:source>/",
        UniversalIngressView.as_view(),
        name="universal_ingress",
    ),
    path("runs/<uuid:pk>/", RunDetailView.as_view()),
    path("runs/history/", GlobalRunHistoryView.as_view()),
    path("auth/send-otp/", SendOTPView.as_view(), name="send-otp"),
    path("auth/logout/", LogoutView.as_view()),
    path("usage/", TaskUsageView.as_view()),
    path("test-trigger/", TestTriggerView.as_view(), name="test-trigger"),
    # --- BILLING ENDPOINTS ---
    path("billing/checkout/", CheckoutSessionView.as_view(), name="checkout_session"),
    path("billing/webhook/", DodoWebhookView.as_view(), name="dodo_webhook"),
] + router.urls
