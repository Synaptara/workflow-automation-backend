from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.urls import path

from .views import RegisterView, WorkflowViewSet, WebhookTriggerView

router = DefaultRouter()
router.register("workflows", WorkflowViewSet, basename="workflow")

urlpatterns = [
    path("auth/register/", RegisterView.as_view()),
    path("auth/login/", TokenObtainPairView.as_view()),
    path("auth/refresh/", TokenRefreshView.as_view()),
    path("hooks/<uuid:workflow_id>/<str:secret>/", WebhookTriggerView.as_view()),
] + router.urls
