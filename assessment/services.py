"""
Ponte entre o motor puro e o banco.

E aqui que a sessao de teste vira linhas gravadas e o resultado vira um estado
de conhecimento pronto para alimentar a recomendacao da Parte 2 — sem nenhuma
conversao manual no meio. As views chamam estas funcoes, nunca o motor
diretamente.

A relacao de pre-requisito e lida do banco, e nao do arquivo de curriculo, de
proposito: as questoes servidas ao aluno vem do banco, e usar as duas fontes ao
mesmo tempo abriria espaco para o motor raciocinar sobre um item que a tela nao
consegue perguntar, caso alguem esqueca de rodar `load_curriculum`.
"""

from django.db import transaction
from django.utils import timezone

from domain.models import (
    CurriculumRelease,
    KnowledgeItem,
    KnowledgeState,
    Question,
    QuestionPurpose,
    Topic,
)
from domain.recommendation import Recommendation, recommend_next_item
from assessment.engine import AdaptiveAssessment, Answer
from assessment.models import (
    AssessmentSession,
    InstrumentResponse,
    InstrumentSession,
    QuestionResponse,
    StudyPhase,
)


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
        # Filtra pelo proposito: servir aqui uma questao do instrumento daria a
        # turma piloto exposicao aos itens pelos quais ela e medida.
        Question.objects.filter(
            item__code=item_code, purpose=QuestionPurpose.ADAPTIVE
        )
        .exclude(id__in=already_used)
        .order_by("position", "code")
        .first()
    )


def sample_question_for(item: KnowledgeItem) -> Question | None:
    """
    Questao usada como amostra do item na tela de recomendacao.

    Sai **so do banco adaptativo**. A tela de recomendacao e vista pela turma
    piloto entre o pre e o pos-teste; uma questao do instrumento aqui seria o
    aluno encontrando, antes do pos-teste, um item pelo qual ele e medido
    (CLAUDE.md secao 11).

    Quem protege e o filtro por proposito, nao a ordenacao: havia empate de
    `position` entre as duas questoes de `pc-par-ordenado`, que o SQLite
    desempatava a favor da adaptativa por ordem de insercao e o Postgres de
    producao nao desempata de forma garantida.
    """
    return (
        Question.objects.filter(item=item, purpose=QuestionPurpose.ADAPTIVE)
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
    # Simetrico ao que `record_instrument_response` ja faz: a view nunca manda
    # uma questao do instrumento para ca, mas o servico nao depende disso.
    if question.purpose != QuestionPurpose.ADAPTIVE:
        raise ValueError(
            f"A questao `{question.code}` nao pertence ao banco adaptativo."
        )

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


def goal_item_for_topic(topic: Topic) -> KnowledgeItem:
    """
    Traduz "quero dominar o topico T" no item que o motor entende como objetivo.

    Decisao de modelagem com implicacao metodologica: o aluno declara um topico,
    mas a regra de desempate opera sobre itens. O objetivo vira o **ultimo item
    do topico na ordem declarada**, porque o caminho de pre-requisitos ate ele
    contem todos os outros itens do mesmo topico — ou seja, "dominar o topico
    inteiro".

    Isso pressupoe que os itens de um topico formam uma cadeia. Vale no
    curriculo atual e ha teste conferindo; se um topico passar a ter dois itens
    finais independentes, o teste falha em vez de escolher um em silencio.
    """
    item = topic.items.order_by("-position", "-code").first()
    if item is None:
        raise ValueError(f"Topico `{topic.code}` nao tem itens.")
    return item


def goal_topics() -> list[Topic]:
    """Topicos que o aluno pode declarar como objetivo, na ordem da cadeia."""
    return list(Topic.objects.prefetch_related("items").order_by("position", "code"))


def topic_of_item(item_code: str) -> Topic:
    return Topic.objects.get(items__code=item_code)


# --------------------------------------------------------------------------
# Instrumento de pesquisa (pre/pos-teste)
#
# Alcanca as DUAS turmas, inclusive a controle. O bloqueio da Parte 4 vale para
# o motor de recomendacao, nao para o instrumento: se a turma controle ficasse
# trancada fora daqui, nao haveria com o que comparar o ganho da turma piloto, e
# a medida principal do estudo deixaria de existir (CLAUDE.md secoes 2 e 10).
# --------------------------------------------------------------------------


def instrument_questions() -> list[Question]:
    """
    As questoes do instrumento, na ordem fixa declarada no arquivo.

    A ordem e a mesma para todo aluno, nas duas turmas e nas duas aplicacoes —
    e o que torna os escores comparaveis entre si.
    """
    return list(
        Question.objects.filter(purpose=QuestionPurpose.INSTRUMENT)
        .select_related("item", "item__topic")
        .order_by("position", "code")
    )


def start_instrument(student, phase: str) -> InstrumentSession:
    """Abre (ou recupera) a aplicacao do instrumento para este aluno e fase."""
    session, _ = InstrumentSession.objects.get_or_create(
        student=student,
        phase=phase,
        defaults={
            "curriculum_release": CurriculumRelease.objects.order_by(
                "-loaded_at"
            ).first()
        },
    )
    return session


def next_instrument_question(session: InstrumentSession) -> Question | None:
    """
    Proxima questao nao respondida, na ordem fixa. `None` quando acabou.

    Nao ha adaptacao nenhuma aqui, de proposito: todo aluno responde o mesmo
    conjunto, na mesma sequencia.
    """
    answered = set(session.responses.values_list("question_id", flat=True))
    for question in instrument_questions():
        if question.pk not in answered:
            return question
    return None


@transaction.atomic
def record_instrument_response(
    session: InstrumentSession, question: Question, chosen_index: int | None
) -> InstrumentResponse:
    if session.is_finished:
        raise ValueError("Esta aplicacao ja foi encerrada; nao aceita novas respostas.")
    if question.purpose != QuestionPurpose.INSTRUMENT:
        raise ValueError(
            f"A questao `{question.code}` nao pertence ao instrumento de pesquisa."
        )

    return InstrumentResponse.objects.create(
        session=session,
        question=question,
        chosen_index=chosen_index,
        is_correct=question.is_correct(chosen_index),
    )


@transaction.atomic
def finalize_instrument(session: InstrumentSession) -> InstrumentSession:
    """
    Encerra a aplicacao.

    Exige que todas as questoes tenham sido respondidas: um escore parcial
    entraria na comparacao como se fosse desempenho, quando na verdade e
    aplicacao incompleta.
    """
    if next_instrument_question(session) is not None:
        raise ValueError(
            "Ainda ha questoes do instrumento sem resposta; encerrar agora "
            "gravaria um escore parcial como se fosse desempenho."
        )
    if not session.is_finished:
        session.finished_at = timezone.now()
        session.save(update_fields=["finished_at"])
    return session


def instrument_results(student) -> dict:
    """
    Pre, pos e ganho de um aluno.

    Aplicacao nao concluida vira `None`, e nao zero: zero significa "errou
    tudo", `None` significa "nao fez". Tratar os dois como a mesma coisa
    corromperia a comparacao de ganho.
    """
    sessions = {
        session.phase: session
        for session in student.instrument_sessions.filter(finished_at__isnull=False)
    }
    pre = sessions.get(StudyPhase.PRE)
    post = sessions.get(StudyPhase.POST)

    pre_score = pre.score if pre else None
    post_score = post.score if post else None
    gain = (
        post_score - pre_score
        if pre_score is not None and post_score is not None
        else None
    )
    return {
        "student": student,
        "pre_score": pre_score,
        "post_score": post_score,
        "gain": gain,
        "max_score": Question.objects.filter(
            purpose=QuestionPurpose.INSTRUMENT
        ).count(),
        "pre_finished_at": pre.finished_at if pre else None,
        "post_finished_at": post.finished_at if post else None,
    }
