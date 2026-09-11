from django.urls import path

from assessment import views

app_name = "assessment"

urlpatterns = [
    path("", views.identify, name="identify"),
    path("objetivo/", views.choose_goal, name="choose_goal"),
    path("teste/", views.take_test, name="take_test"),
    path("recomendacao/", views.recommendation, name="recommendation"),
    path("sair/", views.leave, name="leave"),
]
