from decouple import config
from django.contrib import admin
from django.urls import include, path

ADMIN_URL = config("DJANGO_ADMIN_URL", default="admin/").strip("/") + "/"

urlpatterns = [
    path(ADMIN_URL, admin.site.urls),
    path("api/", include("workflows.urls")),
]
