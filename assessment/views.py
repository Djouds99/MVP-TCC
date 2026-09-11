"""
Fluxo do aluno: identificacao -> objetivo -> teste adaptativo -> recomendacao.

As views sao finas de proposito. Toda a decisao mora nos motores
(`assessment.engine` e `domain.recommendation`), alcancados por
`assessment.services` — aqui so acontece conversa com o navegador.

Sem conta de usuario: o vinculo entre o navegador e a sessao de teste vive no
cookie de sessao do Django, que guarda so os ids do aluno e da sessao. Nenhum
dado pessoal entra ai, porque nao existe nenhum no sistema.
"""

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from assessment.forms import AnswerForm, GoalForm, StudentCodeForm
from assessment.models import AssessmentSession
from assessment.services import (
    build_assessment,
    finalize,
    goal_item_for_topic,
    goal_topics,
    next_question,
    recommendation_for,
    record_response,
    start_session,
)
from domain.models import KnowledgeItem, Question
from domain.recommendation import RecommendationReason
from students.models import Student, StudyGroup

STUDENT_KEY = "student_id"
SESSION_KEY = "assessment_session_id"


def _current_student(request: HttpRequest) -> Student | None:
    student_id = request.session.get(STUDENT_KEY)
    if student_id is None:
        return None
    return Student.objects.filter(pk=student_id).first()


def _current_session(request: HttpRequest) -> AssessmentSession | None:
    session_id = request.session.get(SESSION_KEY)
    if session_id is None:
        return None
    return (
        AssessmentSession.objects.filter(pk=session_id)
        .select_related("student", "goal_item", "goal_item__topic", "resulting_state")
        .first()
    )


def identify(request: HttpRequest) -> HttpResponse:
    """Tela de entrada: o aluno informa o codigo que o professor entregou."""
    if request.method == "POST":
        form = StudentCodeForm(request.POST)
        if form.is_valid():
            student = form.student

            # Grupo controle nao usa o aplicativo — essa e a definicao do
            # desenho comparativo. Deixar entrar contaminaria a comparacao de
            # ganho entre os grupos (CLAUDE.md secao 2).
            if student.group == StudyGroup.CONTROL:
                return render(
                    request, "assessment/control_group.html", {"student": student}
                )

            request.session.cycle_key()
            request.session[STUDENT_KEY] = student.pk
            request.session.pop(SESSION_KEY, None)
            return redirect("assessment:choose_goal")
    else:
        form = StudentCodeForm()

    return render(request, "assessment/identify.html", {"form": form})


def choose_goal(request: HttpRequest) -> HttpResponse:
    """Tela de objetivo: o aluno escolhe o topico que quer alcancar."""
    student = _current_student(request)
    if student is None:
        return redirect("assessment:identify")

    if request.method == "POST":
        form = GoalForm(request.POST)
        if form.is_valid():
            topic = form.cleaned_data["topic"]
            session = start_session(student, goal_item_for_topic(topic))
            request.session[SESSION_KEY] = session.pk
            return redirect("assessment:take_test")
    else:
        form = GoalForm()

    return render(
        request,
        "assessment/choose_goal.html",
        {"form": form, "student": student, "topics": goal_topics()},
    )


def take_test(request: HttpRequest) -> HttpResponse:
    """
    Teste adaptativo, uma pergunta por requisicao.

    O POST grava e redireciona (padrao post/redirect/get), para que atualizar a
    pagina nao reenvie a mesma resposta.
    """
    session = _current_session(request)
    if session is None:
        return redirect("assessment:identify")
    if session.is_finished:
        return redirect("assessment:recommendation")

    question = next_question(session)

    if question is None:
        # O motor convergiu: fecha a sessao e grava o estado estimado.
        finalize(session)
        return redirect("assessment:recommendation")

    if request.method == "POST":
        form = AnswerForm(request.POST)
        if form.is_valid():
            # Envio velho (aluno voltou pelo navegador): ignora em silencio e
            # reapresenta a questao atual, em vez de gravar resposta duplicada.
            if form.cleaned_data["question"] != question.pk:
                return redirect("assessment:take_test")

            chosen = form.cleaned_data.get("alternative")
            if chosen is None or not 0 <= chosen < len(question.alternatives):
                messages.error(request, "Escolha uma das alternativas para continuar.")
                return redirect("assessment:take_test")

            record_response(session, question, chosen)
            return redirect("assessment:take_test")

    assessment = build_assessment(session)
    return render(
        request,
        "assessment/take_test.html",
        {
            "session": session,
            "question": question,
            "alternatives": list(enumerate(question.alternatives)),
            "number": session.responses.count() + 1,
            "remaining": assessment.estimated_remaining_questions,
            "progress": round(assessment.progress * 100),
        },
    )


def recommendation(request: HttpRequest) -> HttpResponse:
    """Tela de recomendacao: o que o motor indica como proximo passo."""
    session = _current_session(request)
    if session is None:
        return redirect("assessment:identify")
    if not session.is_finished:
        return redirect("assessment:take_test")

    result = recommendation_for(session)

    recommended_item = (
        KnowledgeItem.objects.select_related("topic").get(code=result.item)
        if result.item
        else None
    )
    # Serve como texto explicativo provisorio ate a Parte 6; a questao do item
    # da uma amostra concreta do que o aluno vai encontrar ali.
    sample_question = (
        Question.objects.filter(item=recommended_item).order_by("position").first()
        if recommended_item
        else None
    )

    mastered = session.resulting_state.item_codes
    return render(
        request,
        "assessment/recommendation.html",
        {
            "session": session,
            "result": result,
            "item": recommended_item,
            "sample_question": sample_question,
            "mastered_items": KnowledgeItem.objects.select_related("topic")
            .filter(code__in=mastered)
            .order_by("topic__position", "position"),
            "mastered_count": len(mastered),
            "total_items": KnowledgeItem.objects.count(),
            "question_count": session.responses.count(),
            # A comparacao de motivo fica aqui, e nao no template: o Django
            # tenta chamar a classe do enum ao resolver `Reason.X` e a
            # comparacao cai sempre no ramo errado, em silencio.
            "is_goal_directed": result.reason
            == RecommendationReason.GOAL_DIRECTED,
            "is_domain_complete": result.reason
            == RecommendationReason.DOMAIN_COMPLETE,
            "is_goal_reached": result.reason
            == RecommendationReason.GOAL_ALREADY_REACHED,
        },
    )


def leave(request: HttpRequest) -> HttpResponse:
    """Encerra a visita. Util quando o aparelho e compartilhado na sala."""
    request.session.flush()
    return redirect("assessment:identify")
