"""
Fluxo do aluno.

Duas trilhas distintas convivem aqui, e nao devem ser confundidas
(CLAUDE.md secao 2):

- **Instrumento de pesquisa** (pre/pos-teste): conjunto fixo de questoes, ordem
  fixa, aplicado igualmente as **duas turmas**. E dele que sai o dado
  comparativo do TCC2.
- **App de recomendacao** (objetivo -> teste adaptativo -> recomendacao): so a
  turma piloto. E o tratamento que esta sendo avaliado.

O bloqueio da turma controle vale **apenas** para a segunda trilha. Aplica-lo
tambem ao instrumento trancaria o grupo controle fora do proprio instrumento que
produz a comparacao, e nao sobraria com o que comparar o ganho do piloto
(CLAUDE.md secao 10).

Quem decide a etapa e o professor, pelo admin, e nao o aluno: sem isso alguem
poderia responder o pos-teste antes da atividade. A etapa e **por turma** —
piloto e controle podem seguir calendarios diferentes (CLAUDE.md secao 11) —,
entao toda leitura de etapa usa a turma do aluno, via `StudySettings.stage_for`.

As views sao finas. Toda decisao mora nos motores (`assessment.engine`,
`domain.recommendation`) ou em `assessment.services`.
"""

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from assessment.forms import AnswerForm, GoalForm, StudentCodeForm
from assessment.models import (
    AssessmentSession,
    InstrumentSession,
    StudyPhase,
    StudySettings,
    StudyStage,
)
from assessment.services import (
    build_assessment,
    finalize,
    finalize_instrument,
    goal_item_for_topic,
    goal_topics,
    instrument_questions,
    next_instrument_question,
    next_question,
    recommendation_for,
    record_instrument_response,
    record_response,
    sample_question_for,
    start_instrument,
    start_session,
)
from domain.models import KnowledgeItem
from domain.recommendation import RecommendationReason
from students.models import Student, StudyGroup

STUDENT_KEY = "student_id"
SESSION_KEY = "assessment_session_id"

# Em que fase do instrumento cada etapa do estudo coloca o aluno.
STAGE_PHASE = {
    StudyStage.PRE_TEST: StudyPhase.PRE,
    StudyStage.POST_TEST: StudyPhase.POST,
}


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


def _has_finished(student: Student, phase: str) -> bool:
    return InstrumentSession.objects.filter(
        student=student, phase=phase, finished_at__isnull=False
    ).exists()


def identify(request: HttpRequest) -> HttpResponse:
    """
    Tela de entrada: o aluno informa o codigo que o professor entregou.

    Aceita as duas turmas. O grupo controle entra normalmente porque precisa do
    instrumento de pesquisa; o que ele nao alcanca e o motor de recomendacao.
    """
    if request.method == "POST":
        form = StudentCodeForm(request.POST)
        if form.is_valid():
            request.session.cycle_key()
            request.session[STUDENT_KEY] = form.student.pk
            request.session.pop(SESSION_KEY, None)
            return redirect("assessment:next_step")
    else:
        form = StudentCodeForm()

    return render(request, "assessment/identify.html", {"form": form})


def next_step(request: HttpRequest) -> HttpResponse:
    """
    Manda o aluno para onde ele deve estar agora.

    Ponto unico de decisao: etapa do estudo, turma e o que o aluno ja concluiu.
    Concentrar isso numa view so evita que cada tela reimplemente a regra com
    uma variacao sutil.
    """
    student = _current_student(request)
    if student is None:
        return redirect("assessment:identify")

    stage = StudySettings.stage_for(student)

    if stage == StudyStage.CLOSED:
        return render(request, "assessment/closed.html", {"student": student})

    if stage == StudyStage.POST_TEST:
        if _has_finished(student, StudyPhase.POST):
            return render(request, "assessment/all_done.html", {"student": student})
        return redirect("assessment:instrument")

    # Pre-teste vem antes de qualquer uso do app, inclusive para quem chegou
    # atrasado e so apareceu na etapa da atividade.
    if not _has_finished(student, StudyPhase.PRE):
        return redirect("assessment:instrument")

    if stage == StudyStage.PRE_TEST:
        return render(request, "assessment/waiting.html", {"student": student})

    # Etapa da atividade.
    if student.group == StudyGroup.CONTROL:
        return render(request, "assessment/control_activity.html", {"student": student})

    session = _current_session(request)
    if session is not None and session.is_finished:
        return redirect("assessment:recommendation")
    if session is not None:
        return redirect("assessment:take_test")
    return redirect("assessment:choose_goal")


# --------------------------------------------------------------------------
# Instrumento de pesquisa — as duas turmas
# --------------------------------------------------------------------------


def instrument(request: HttpRequest) -> HttpResponse:
    """Pre ou pos-teste, uma questao por requisicao, na ordem fixa."""
    student = _current_student(request)
    if student is None:
        return redirect("assessment:identify")

    stage = StudySettings.stage_for(student)
    phase = STAGE_PHASE.get(stage)
    if phase is None:
        # Etapa de atividade: o pre-teste so continua aberto para quem ainda nao
        # o concluiu.
        if stage == StudyStage.ACTIVITY and not _has_finished(student, StudyPhase.PRE):
            phase = StudyPhase.PRE
        else:
            return redirect("assessment:next_step")

    if _has_finished(student, phase):
        return redirect("assessment:next_step")

    session = start_instrument(student, phase)
    question = next_instrument_question(session)

    if question is None:
        finalize_instrument(session)
        return redirect("assessment:instrument_done")

    if request.method == "POST":
        form = AnswerForm(request.POST)
        if form.is_valid():
            if form.cleaned_data["question"] != question.pk:
                return redirect("assessment:instrument")

            chosen = form.cleaned_data.get("alternative")
            if chosen is None or not 0 <= chosen < len(question.alternatives):
                messages.error(request, "Escolha uma das alternativas para continuar.")
                return redirect("assessment:instrument")

            record_instrument_response(session, question, chosen)
            return redirect("assessment:instrument")

    total = len(instrument_questions())
    answered = session.responses.count()
    return render(
        request,
        "assessment/instrument.html",
        {
            "student": student,
            "question": question,
            "alternatives": list(enumerate(question.alternatives)),
            "number": answered + 1,
            "total": total,
            "progress": round(answered / total * 100) if total else 0,
            "is_post": phase == StudyPhase.POST,
        },
    )


def instrument_done(request: HttpRequest) -> HttpResponse:
    """Confirmacao de que a aplicacao do instrumento foi concluida."""
    student = _current_student(request)
    if student is None:
        return redirect("assessment:identify")

    stage = StudySettings.stage_for(student)
    return render(
        request,
        "assessment/instrument_done.html",
        {
            "student": student,
            "is_post": stage == StudyStage.POST_TEST,
            "is_pilot": student.group == StudyGroup.PILOT,
            "activity_open": stage == StudyStage.ACTIVITY,
        },
    )


# --------------------------------------------------------------------------
# App de recomendacao — so a turma piloto
# --------------------------------------------------------------------------


def _app_access(request: HttpRequest):
    """
    Porteiro das telas do motor de recomendacao.

    Devolve `(student, None)` quando o acesso e permitido, ou `(None, resposta)`
    com o redirecionamento a seguir. Tres condicoes, todas metodologicas: a
    turma controle nao entra, a etapa precisa ser a da atividade, e o pre-teste
    precisa estar concluido — "antes de qualquer uso do app" e literal.
    """
    student = _current_student(request)
    if student is None:
        return None, redirect("assessment:identify")
    if student.group == StudyGroup.CONTROL:
        return None, redirect("assessment:next_step")
    if StudySettings.stage_for(student) != StudyStage.ACTIVITY:
        return None, redirect("assessment:next_step")
    if not _has_finished(student, StudyPhase.PRE):
        return None, redirect("assessment:next_step")
    return student, None


def choose_goal(request: HttpRequest) -> HttpResponse:
    """Tela de objetivo: o aluno escolhe o topico que quer alcancar."""
    student, denied = _app_access(request)
    if denied is not None:
        return denied

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
    _, denied = _app_access(request)
    if denied is not None:
        return denied

    session = _current_session(request)
    if session is None:
        return redirect("assessment:choose_goal")
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
    _, denied = _app_access(request)
    if denied is not None:
        return denied

    session = _current_session(request)
    if session is None:
        return redirect("assessment:choose_goal")
    if not session.is_finished:
        return redirect("assessment:take_test")

    result = recommendation_for(session)

    recommended_item = (
        KnowledgeItem.objects.select_related("topic").get(code=result.item)
        if result.item
        else None
    )
    # Texto explicativo provisorio ate a Parte 6. Vem so do banco adaptativo —
    # ver `sample_question_for` sobre o vazamento que isso evita.
    sample_question = (
        sample_question_for(recommended_item) if recommended_item else None
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
            .order_by("topic__position", "position", "code"),
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
