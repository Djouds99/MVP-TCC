from django.contrib import admin
from django.urls import path

from config import views

urlpatterns = [
    path("", views.index, name="index"),
    path("healthz", views.healthz, name="healthz"),
    path("admin/", admin.site.urls),
]
