from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    CredentialViewSet,
    GlobalRunHistoryView,
    IntegrationOAuthView,
    RegisterView,
    SecureLoginView,
    SecureRefreshView,
    SendOTPView,
    SocialAuthView,
    TaskUsageView,
    UniversalIngressView,
    WebhookTriggerView,
    WorkflowViewSet,
)

router = DefaultRouter()
router.register("workflows", WorkflowViewSet, basename="workflow")
router.register("credentials", CredentialViewSet, basename="credentials")

urlpatterns = [
    path("auth/register/", RegisterView.as_view()),
    path("auth/login/", SecureLoginView.as_view()),
    path("auth/refresh/", SecureRefreshView.as_view()),
    path("auth/social/<str:provider>/", SocialAuthView.as_view()),
    path("credentials/oauth/<str:provider>/", IntegrationOAuthView.as_view()),
    path("hooks/<uuid:workflow_id>/<str:secret>/", WebhookTriggerView.as_view()),
    # 2. Wire the Ingestion Engine here
    path(
        "ingress/<str:source>/",
        UniversalIngressView.as_view(),
        name="universal_ingress",
    ),
    path("runs/history/", GlobalRunHistoryView.as_view()),
    path("auth/send-otp/", SendOTPView.as_view(), name="send-otp"),
    path("usage/", TaskUsageView.as_view()),
] + router.urls
