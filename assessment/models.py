"""
Dados dinamicos do teste de posicionamento.

Enquanto topicos, itens e questoes sao conteudo versionado (app `domain`), o que
mora aqui e o que so existe porque um aluno usou o sistema: as respostas dadas e
o estado estimado a partir delas (CLAUDE.md secao 5).

Nada aqui e aprendizado entre sessoes. Cada sessao e recalculada do zero a
partir das proprias respostas; nao ha peso, modelo ou parametro que atravesse de
um aluno para outro nem de uma sessao para a seguinte (CLAUDE.md secao 2). As
respostas ficam gravadas porque sao o dado da pesquisa, nao porque alimentem o
algoritmo.
"""

from django.db import models

from domain.models import (
    CurriculumRelease,
    KnowledgeItem,
    KnowledgeState,
    Question,
)
from students.models import Student


class AssessmentSession(models.Model):
    """Uma aplicacao do teste de posicionamento para um aluno."""

    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="assessment_sessions"
    )
    goal_item = models.ForeignKey(
        KnowledgeItem,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="Objetivo declarado pelo aluno, usado no desempate da recomendacao.",
    )
    # Amarra a sessao a versao de conteudo que estava no ar quando ela rodou.
    # Sem isso nao da para afirmar, no TCC2, sobre qual banco de questoes cada
    # medida foi feita.
    curriculum_release = models.ForeignKey(
        CurriculumRelease,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assessment_sessions",
    )
    resulting_state = models.ForeignKey(
        KnowledgeState,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assessment_sessions",
        help_text="Estado estimado. Vazio enquanto o teste nao converge.",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "sessao de teste"
        verbose_name_plural = "sessoes de teste"

    def __str__(self) -> str:
        situacao = "concluida" if self.is_finished else "em andamento"
        return f"{self.student.code} — {situacao}"

    @property
    def is_finished(self) -> bool:
        return self.finished_at is not None

    @property
    def question_count(self) -> int:
        return self.responses.count()


class QuestionResponse(models.Model):
    """Uma resposta do aluno a uma questao, dentro de uma sessao."""

    session = models.ForeignKey(
        AssessmentSession, on_delete=models.CASCADE, related_name="responses"
    )
    question = models.ForeignKey(
        Question, on_delete=models.PROTECT, related_name="responses"
    )
    # Guardado alem do certo/errado: qual alternativa errada atrai mais aluno e
    # informacao util para a analise do conteudo, e sai de graca.
    chosen_index = models.PositiveSmallIntegerField(null=True, blank=True)
    is_correct = models.BooleanField()
    position = models.PositiveSmallIntegerField(
        help_text="Ordem da questao dentro da sessao, a partir de 1."
    )
    answered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["session", "position"]
        constraints = [
            # O motor adaptativo nunca repete um item, e repetir mudaria o
            # significado do resultado — melhor o banco recusar.
            models.UniqueConstraint(
                fields=["session", "question"], name="unique_response_per_question"
            ),
            models.UniqueConstraint(
                fields=["session", "position"], name="unique_position_per_session"
            ),
        ]
        verbose_name = "resposta"
        verbose_name_plural = "respostas"

    def __str__(self) -> str:
        return f"{self.question.code}: {'certo' if self.is_correct else 'errado'}"


class StudyPhase(models.TextChoices):
    """Qual aplicacao do instrumento — a de antes ou a de depois."""

    PRE = "pre", "Pré-teste"
    POST = "post", "Pós-teste"


class StudyStage(models.TextChoices):
    """
    Em que ponto do estudo a aplicacao esta.

    Quem decide e o professor, no admin, e nao o aluno: sem isso um aluno
    poderia abrir o pos-teste antes da atividade, e "antes" e "depois" deixariam
    de significar alguma coisa. E o mecanismo que sustenta o desenho pre/pos.
    """

    PRE_TEST = "pre_test", "Pré-teste aberto"
    ACTIVITY = "activity", "Atividade (piloto usa o app)"
    POST_TEST = "post_test", "Pós-teste aberto"
    CLOSED = "closed", "Encerrado"


class StudySettings(models.Model):
    """
    Linha unica de configuracao do estudo.

    Existe so para guardar a etapa atual. Um registro de configuracao no banco,
    e nao uma variavel de ambiente, porque o professor precisa conseguir virar a
    chave pelo admin no meio da aula, sem redeploy.
    """

    stage = models.CharField(
        max_length=12, choices=StudyStage.choices, default=StudyStage.PRE_TEST
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "configuracao do estudo"
        verbose_name_plural = "configuracao do estudo"

    def __str__(self) -> str:
        return self.get_stage_display()

    def save(self, *args, **kwargs):
        # Singleton: sempre a mesma linha, para nao existir duas configuracoes
        # divergentes sem ninguem perceber.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def current(cls) -> "StudySettings":
        settings, _ = cls.objects.get_or_create(pk=1)
        return settings


class InstrumentSession(models.Model):
    """
    Uma aplicacao do instrumento de pesquisa a um aluno.

    Distinto do `AssessmentSession`: aquele e o teste adaptativo interno do app,
    que so a turma piloto faz; este e o pre/pos-teste de desempenho, com itens
    fixos, aplicado igualmente as duas turmas (CLAUDE.md secao 2). Confundir os
    dois invalidaria a comparacao.
    """

    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="instrument_sessions"
    )
    phase = models.CharField(max_length=4, choices=StudyPhase.choices)
    curriculum_release = models.ForeignKey(
        CurriculumRelease,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="instrument_sessions",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["student", "phase"]
        constraints = [
            # Uma aplicacao por fase por aluno: repetir o pre-teste mudaria o
            # que o escore significa.
            models.UniqueConstraint(
                fields=["student", "phase"], name="unique_instrument_session_per_phase"
            )
        ]
        verbose_name = "aplicacao do instrumento"
        verbose_name_plural = "aplicacoes do instrumento"

    def __str__(self) -> str:
        return f"{self.student.code} — {self.get_phase_display()}"

    @property
    def is_finished(self) -> bool:
        return self.finished_at is not None

    @property
    def score(self) -> int:
        """Numero de acertos. So faz sentido com a aplicacao concluida."""
        return self.responses.filter(is_correct=True).count()


class InstrumentResponse(models.Model):
    """Resposta a uma questao do instrumento."""

    session = models.ForeignKey(
        InstrumentSession, on_delete=models.CASCADE, related_name="responses"
    )
    question = models.ForeignKey(
        Question, on_delete=models.PROTECT, related_name="instrument_responses"
    )
    chosen_index = models.PositiveSmallIntegerField(null=True, blank=True)
    is_correct = models.BooleanField()
    answered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["session", "question__position"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "question"],
                name="unique_instrument_response_per_question",
            )
        ]
        verbose_name = "resposta do instrumento"
        verbose_name_plural = "respostas do instrumento"

    def __str__(self) -> str:
        return f"{self.question.code}: {'certo' if self.is_correct else 'errado'}"
