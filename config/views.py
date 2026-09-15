"""
Views de servico: verificacao de ambiente e checagem de saude.

Nao fazem parte do fluxo do aluno, que vive em `assessment.views`. Ficam de pe
porque continuam uteis para confirmar, depois de um deploy, que o dominio
carregado no banco e o esperado.
"""

from django.db import connection
from django.http import HttpResponse
from django.shortcuts import render

from domain.models import CurriculumRelease, KnowledgeItem, KnowledgeState, Topic


def status(request):
    topics = Topic.objects.prefetch_related("prerequisites", "items").order_by(
        "position", "code"
    )
    return render(
        request,
        "status.html",
        {
            "topics": topics,
            "item_count": KnowledgeItem.objects.count(),
            "state_count": KnowledgeState.objects.count(),
            "release": CurriculumRelease.current(),
        },
    )


def healthz(request):
    """
    Checagem de saude para a hospedagem.

    Toca o banco de proposito: um processo que sobe mas nao alcanca o banco esta
    fora do ar na pratica, e e melhor a plataforma saber disso.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return HttpResponse("banco indisponivel\n", status=503, content_type="text/plain")
    return HttpResponse("ok\n", content_type="text/plain")
