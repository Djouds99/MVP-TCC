"""
Views minimas da Parte 1.

Nao sao a interface do aluno — servem para provar que o caminho de deploy
funciona e que o dominio carregado no banco e o esperado. Serao substituidas
pelo fluxo real (teste adaptativo -> recomendacao) nas partes seguintes.
"""

from django.db import connection
from django.http import HttpResponse
from django.shortcuts import render

from domain.models import CurriculumRelease, KnowledgeItem, KnowledgeState, Topic


def index(request):
    topics = (
        Topic.objects.prefetch_related("prerequisites", "items").order_by("position")
    )
    return render(
        request,
        "index.html",
        {
            "topics": topics,
            "item_count": KnowledgeItem.objects.count(),
            "state_count": KnowledgeState.objects.count(),
            "release": CurriculumRelease.objects.order_by("-loaded_at").first(),
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
