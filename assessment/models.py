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

from domain.models import CurriculumRelease, KnowledgeItem, KnowledgeState, Question
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
