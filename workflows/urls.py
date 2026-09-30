from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    CredentialViewSet,
    GlobalRunHistoryView,
    RegisterView,
    SocialAuthView,
    TaskUsageView,
    WebhookTriggerView,
    WorkflowViewSet,
)

router = DefaultRouter()
router.register("workflows", WorkflowViewSet, basename="workflow")
router.register("credentials", CredentialViewSet, basename="credentials")

urlpatterns = [
    path("auth/register/", RegisterView.as_view()),
    path("auth/login/", TokenObtainPairView.as_view()),
    path("auth/refresh/", TokenRefreshView.as_view()),
    path("auth/social/<str:provider>/", SocialAuthView.as_view()),
    path("hooks/<uuid:workflow_id>/<str:secret>/", WebhookTriggerView.as_view()),
    path("runs/history/", GlobalRunHistoryView.as_view()),
    path("usage/", TaskUsageView.as_view()),
] + router.urls
