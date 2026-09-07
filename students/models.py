"""
Identificacao do participante.

Nao existe conta de usuario: nenhum nome, e-mail, matricula ou data de
nascimento e armazenado, nem deve ser acrescentado depois. O unico identificador
e um codigo curto atribuido pelo professor, que serve para ligar pre-teste,
pos-teste e grupo (piloto/controle) ao mesmo participante (CLAUDE.md secao 8).
"""

from django.core.exceptions import ValidationError
from django.db import models

from students.codes import (
    CODE_ALPHABET,
    DEFAULT_CODE_LENGTH,
    MAX_CODE_LENGTH,
    MIN_CODE_LENGTH,
    generate_code,
)


def validate_code_format(value: str) -> None:
    if not MIN_CODE_LENGTH <= len(value) <= MAX_CODE_LENGTH:
        raise ValidationError(
            f"O codigo deve ter de {MIN_CODE_LENGTH} a {MAX_CODE_LENGTH} caracteres."
        )
    invalid = sorted(set(value) - set(CODE_ALPHABET))
    if invalid:
        raise ValidationError(
            "O codigo contem caracteres fora do alfabeto permitido: "
            + ", ".join(invalid)
        )


class StudyGroup(models.TextChoices):
    """
    Grupo do desenho comparativo (CLAUDE.md secao 2).

    PILOT usa o aplicativo; CONTROL nao usa. Os dois respondem pre-teste e
    pos-teste com os mesmos itens, e a comparacao e feita pelo ganho de cada
    grupo, nao pelo placar bruto.
    """

    PILOT = "pilot", "Piloto (usa o aplicativo)"
    CONTROL = "control", "Controle (nao usa o aplicativo)"


class Student(models.Model):
    code = models.CharField(
        max_length=MAX_CODE_LENGTH,
        unique=True,
        validators=[validate_code_format],
        help_text="Codigo curto entregue ao aluno. Sem relacao com dados pessoais.",
    )
    group = models.CharField(
        max_length=10,
        choices=StudyGroup.choices,
        help_text="Piloto ou controle. Definido na geracao dos codigos.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["group", "code"]
        verbose_name = "aluno"
        verbose_name_plural = "alunos"

    def __str__(self) -> str:
        return f"{self.code} ({self.get_group_display()})"

    def clean(self) -> None:
        super().clean()
        validate_code_format(self.code)

    @classmethod
    def create_with_generated_code(
        cls, group: str, length: int = DEFAULT_CODE_LENGTH, max_attempts: int = 50
    ) -> "Student":
        """
        Cria um aluno com codigo novo, repetindo o sorteio em caso de colisao.

        A colisao e improvavel no volume de duas turmas, mas o `unique=True` do
        banco e a garantia real — o laco so evita que uma colisao rara vire erro
        na tela do professor.
        """
        for _ in range(max_attempts):
            code = generate_code(length)
            if not cls.objects.filter(code=code).exists():
                return cls.objects.create(code=code, group=group)
        raise RuntimeError(
            "Nao foi possivel gerar um codigo livre. Aumente o comprimento do codigo."
        )
