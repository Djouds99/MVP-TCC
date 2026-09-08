"""
Ponte entre o motor puro e o banco.

E aqui que a sessao de teste vira linhas gravadas e o resultado vira um estado
de conhecimento pronto para alimentar a recomendacao da Parte 2 — sem nenhuma
conversao manual no meio. A interface da Parte 5 deve chamar estas funcoes, nao
o motor diretamente.

A relacao de pre-requisito e lida do banco, e nao do arquivo de curriculo, de
proposito: as questoes servidas ao aluno vem do banco, e usar as duas fontes ao
mesmo tempo abriria espaco para o motor raciocinar sobre um item que a tela nao
consegue perguntar, caso alguem esqueca de rodar `load_curriculum`.
"""

from django.db import transaction
from django.utils import timezone

from domain.models import CurriculumRelease, KnowledgeItem, KnowledgeState, Question
from domain.recommendation import Recommendation, recommend_next_item
from assessment.engine import AdaptiveAssessment, Answer
from assessment.models import AssessmentSession, QuestionResponse


def closure_from_database() -> dict[str, frozenset[str]]:
    """
    Fecho transitivo dos pre-requisitos, montado a partir do banco.

    `KnowledgeItem.prerequisites` ja guarda o fecho (ver `load_curriculum`),
    entao nao ha grafo a percorrer aqui.
    """
    items = KnowledgeItem.objects.prefetch_related("prerequisites")
    return {
        item.code: frozenset(
            prerequisite.code for prerequisite in item.prerequisites.all()
        )
        for item in items
    }


def canonical_item_order() -> list[str]:
    """Ordem de leitura do curriculo, para desempate estavel no motor."""
    return list(
        KnowledgeItem.objects.order_by(
            "topic__position", "position", "code"
        ).values_list("code", flat=True)
    )


def build_assessment(session: AssessmentSession) -> AdaptiveAssessment:
    """
    Reconstroi o motor a partir das respostas ja gravadas na sessao.

    Nada de estado de teste guardado no servidor entre requisicoes: as respostas
    no banco sao a unica fonte, e refazer o caminho a partir delas da sempre o
    mesmo resultado.
    """
    responses = session.responses.select_related("question__item").order_by("position")
    answers = [
        Answer(item=response.question.item.code, correct=response.is_correct)
        for response in responses
    ]
    return AdaptiveAssessment.from_answers(
        closure_from_database(), answers, item_order=canonical_item_order()
    )


def start_session(student, goal_item: KnowledgeItem | None = None) -> AssessmentSession:
    return AssessmentSession.objects.create(
        student=student,
        goal_item=goal_item,
        curriculum_release=CurriculumRelease.objects.order_by("-loaded_at").first(),
    )


def next_question(session: AssessmentSession) -> Question | None:
    """
    Proxima questao a apresentar, ou None se o teste ja convergiu.

    O motor escolhe o item; a questao e a de menor `position` entre as do item
    que ainda nao foram usadas nesta sessao.
    """
    assessment = build_assessment(session)
    item_code = assessment.next_item
    if item_code is None:
        return None

    already_used = session.responses.values_list("question_id", flat=True)
    return (
        Question.objects.filter(item__code=item_code)
        .exclude(id__in=already_used)
        .order_by("position", "code")
        .first()
    )


@transaction.atomic
def record_response(
    session: AssessmentSession, question: Question, chosen_index: int | None
) -> QuestionResponse:
    """Grava a resposta do aluno e devolve a linha criada."""
    if session.is_finished:
        raise ValueError("A sessao ja foi encerrada; nao aceita novas respostas.")

    position = session.responses.count() + 1
    return QuestionResponse.objects.create(
        session=session,
        question=question,
        chosen_index=chosen_index,
        is_correct=question.is_correct(chosen_index),
        position=position,
    )


@transaction.atomic
def finalize(session: AssessmentSession) -> KnowledgeState:
    """
    Fecha a sessao e grava o estado de conhecimento estimado.

    Levanta ValueError se o teste ainda nao convergiu — encerrar antes disso
    gravaria como medida algo que ainda nao e medida.
    """
    assessment = build_assessment(session)
    estimated = assessment.knowledge_state

    state = KnowledgeState.objects.get(
        signature=KnowledgeState.make_signature(estimated)
    )
    session.resulting_state = state
    session.finished_at = timezone.now()
    session.save(update_fields=["resulting_state", "finished_at"])
    return state


def recommendation_for(session: AssessmentSession) -> Recommendation:
    """
    Recomendacao da Parte 2 a partir do resultado desta sessao.

    E o ponto de encontro dos dois motores: o estado que o teste adaptativo
    estimou entra direto na regra de fronteira com desempate por objetivo.
    """
    if session.resulting_state is None:
        raise ValueError(
            "A sessao ainda nao tem estado estimado; chame `finalize` antes."
        )

    goal = session.goal_item.code if session.goal_item else None
    return recommend_next_item(
        session.resulting_state.item_codes, closure_from_database(), goal=goal
    )
