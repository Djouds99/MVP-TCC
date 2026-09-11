from django.contrib import admin
from django.urls import include, path

from config import views

urlpatterns = [
    path("", include("assessment.urls")),
    path("status/", views.status, name="status"),
    path("healthz", views.healthz, name="healthz"),
    path("admin/", admin.site.urls),
]
