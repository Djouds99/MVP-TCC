from django.urls import path

from assessment import views

app_name = "assessment"

urlpatterns = [
    path("", views.identify, name="identify"),
    path("continuar/", views.next_step, name="next_step"),
    # Instrumento de pesquisa: as duas turmas.
    path("prova/", views.instrument, name="instrument"),
    path("prova/concluida/", views.instrument_done, name="instrument_done"),
    # App de recomendacao: so a turma piloto.
    path("objetivo/", views.choose_goal, name="choose_goal"),
    path("teste/", views.take_test, name="take_test"),
    path("recomendacao/", views.recommendation, name="recommendation"),
    path("sair/", views.leave, name="leave"),
]
