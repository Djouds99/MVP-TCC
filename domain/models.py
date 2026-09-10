"""
Modelagem do dominio de conhecimento (KST).

Vocabulario adotado, e a correspondencia com o repositorio de referencia
(`ishwar6/KST-Learning-Path`), que usa nomes diferentes dos da literatura:

    literatura (Doignon & Falmagne;      referencia            aqui
    Steiner, Nussbaumer & Albert)
    ------------------------------------ --------------------- -----------------
    item do dominio Q                    `State`               `KnowledgeItem`
    estado de conhecimento K ⊆ Q         `Node`                `KnowledgeState`

Os nomes da literatura foram preferidos porque o texto do TCC2 cita a teoria, e
chamar de "State" aquilo que na teoria e um *item* (e nao um estado) produziria
divergencia entre codigo e metodologia.

O conteudo (topicos, itens, pre-requisitos) e dado versionado em
`domain/data/curriculum.json` e entra no banco pelo comando `load_curriculum`
(CLAUDE.md secao 5: dado versionado, nao CMS). O banco guarda a estrutura para
poder ser consultada e relacionada as respostas do aluno, mas a fonte da verdade
continua sendo o arquivo.
"""

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Topic(models.Model):
    """Topico da cadeia de pre-requisitos. Unidade de recomendacao e de conteudo."""

    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    summary = models.TextField(blank=True)
    # Ordem canonica da cadeia, usada so para exibicao previsivel; a ordem que
    # importa para o motor KST e a relacao de pre-requisito, nao este campo.
    position = models.PositiveSmallIntegerField(default=0)
    bncc_skills = models.JSONField(default=list, blank=True)
    prerequisites = models.ManyToManyField(
        "self",
        symmetrical=False,
        blank=True,
        related_name="dependents",
    )

    class Meta:
        ordering = ["position", "code"]
        verbose_name = "topico"
        verbose_name_plural = "topicos"

    def __str__(self) -> str:
        return self.name


class KnowledgeItem(models.Model):
    """
    Item atomico de conhecimento — um elemento do dominio Q.

    E a unidade que o teste adaptativo tenta classificar como dominada ou nao.
    """

    code = models.SlugField(max_length=40, unique=True)
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="items")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    position = models.PositiveSmallIntegerField(default=0)
    difficulty = models.PositiveSmallIntegerField(
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="1 a 5. Usado para ordenar itens dentro do topico.",
    )
    # Fecho transitivo da relacao de pre-requisito entre itens, ja resolvido no
    # carregamento a partir das arestas declaradas no JSON — nao ha heranca de
    # topico desde a revisao de 10/09/2026. Guardar o fecho evita recalcular a
    # cada consulta e torna a verificacao de "estado bem formado" uma comparacao
    # direta de conjuntos.
    prerequisites = models.ManyToManyField(
        "self",
        symmetrical=False,
        blank=True,
        related_name="dependents",
    )

    class Meta:
        ordering = ["topic__position", "position", "code"]
        verbose_name = "item de conhecimento"
        verbose_name_plural = "itens de conhecimento"

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class KnowledgeState(models.Model):
    """
    Estado de conhecimento: subconjunto de itens dominados.

    O conjunto de todos os estados forma o espaco de conhecimento, gerado a
    partir da relacao de pre-requisito (todo subconjunto fechado para baixo).
    Como o dominio deste MVP e pequeno (15 itens, 46 estados), o espaco e
    enumerado e materializado no banco — nao ha custo em manter todos os
    estados.
    """

    # Assinatura canonica: codigos dos itens ordenados e unidos por "|".
    # Estado vazio => string vazia. Permite localizar um estado a partir de um
    # conjunto de itens com um unico SELECT, sem varrer a tabela M2M.
    signature = models.TextField(unique=True)
    items = models.ManyToManyField(KnowledgeItem, blank=True, related_name="states")
    size = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["size", "signature"]
        verbose_name = "estado de conhecimento"
        verbose_name_plural = "estados de conhecimento"

    def __str__(self) -> str:
        return f"{{{self.signature}}}" if self.signature else "{} (estado vazio)"

    @staticmethod
    def make_signature(item_codes) -> str:
        return "|".join(sorted(item_codes))

    @property
    def item_codes(self) -> set[str]:
        return set(self.signature.split("|")) if self.signature else set()


class Question(models.Model):
    """
    Questao de multipla escolha que sonda um item de conhecimento.

    Conteudo versionado como o resto do dominio: vem do arquivo de curriculo e e
    regravada a cada `load_curriculum`.

    `alternatives` guarda so os textos, e a resposta certa fica separada em
    `correct_index`. Assim a lista que vai para a interface nunca carrega junto
    qual das opcoes e a correta.
    """

    code = models.SlugField(max_length=60, unique=True)
    item = models.ForeignKey(
        KnowledgeItem, on_delete=models.CASCADE, related_name="questions"
    )
    statement = models.TextField()
    alternatives = models.JSONField(default=list)
    correct_index = models.PositiveSmallIntegerField()
    difficulty = models.PositiveSmallIntegerField(
        default=3, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["item__topic__position", "item__position", "position", "code"]
        verbose_name = "questao"
        verbose_name_plural = "questoes"

    def __str__(self) -> str:
        return self.code

    def clean(self) -> None:
        super().clean()
        if len(self.alternatives) < 2:
            raise ValidationError("A questao precisa de pelo menos duas alternativas.")
        if not 0 <= self.correct_index < len(self.alternatives):
            raise ValidationError(
                "`correct_index` nao aponta para nenhuma das alternativas."
            )

    def is_correct(self, chosen_index: int | None) -> bool:
        return chosen_index == self.correct_index

    @property
    def correct_alternative(self) -> str:
        return self.alternatives[self.correct_index]


class CurriculumRelease(models.Model):
    """
    Registro de qual versao do arquivo de curriculo esta carregada.

    Serve a reprodutibilidade: permite afirmar, no TCC2, sobre qual versao de
    conteudo cada aplicacao (piloto/controle) rodou.
    """

    version = models.CharField(max_length=40)
    checksum = models.CharField(max_length=64, help_text="SHA-256 do arquivo JSON.")
    loaded_at = models.DateTimeField(auto_now_add=True)
    item_count = models.PositiveIntegerField(default=0)
    question_count = models.PositiveIntegerField(default=0)
    state_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-loaded_at"]
        get_latest_by = "loaded_at"
        verbose_name = "versao do curriculo"
        verbose_name_plural = "versoes do curriculo"

    def __str__(self) -> str:
        return f"{self.version} ({self.checksum[:8]})"
