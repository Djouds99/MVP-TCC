"""
Gera codigos de acesso para uma turma.

Uso tipico, antes da aplicacao:
    python manage.py create_students --group pilot --count 30
    python manage.py create_students --group control --count 30

A saida e uma lista de codigos para o professor imprimir e distribuir. O sistema
nao registra a quem cada codigo foi entregue — essa associacao, se existir, fica
so com o professor, fora da aplicacao.
"""

from django.core.management.base import BaseCommand, CommandError

from students.codes import DEFAULT_CODE_LENGTH, MAX_CODE_LENGTH, MIN_CODE_LENGTH
from students.models import Student, StudyGroup


class Command(BaseCommand):
    help = "Gera codigos de acesso para o grupo piloto ou controle."

    def add_arguments(self, parser):
        parser.add_argument(
            "--group",
            required=True,
            choices=[choice.value for choice in StudyGroup],
            help="Grupo do desenho comparativo.",
        )
        parser.add_argument(
            "--count", type=int, required=True, help="Quantidade de codigos a gerar."
        )
        parser.add_argument(
            "--length",
            type=int,
            default=DEFAULT_CODE_LENGTH,
            help=f"Comprimento do codigo ({MIN_CODE_LENGTH} a {MAX_CODE_LENGTH}).",
        )

    def handle(self, *args, **options):
        count = options["count"]
        if count < 1:
            raise CommandError("--count deve ser pelo menos 1.")

        length = options["length"]
        if not MIN_CODE_LENGTH <= length <= MAX_CODE_LENGTH:
            raise CommandError(
                f"--length deve estar entre {MIN_CODE_LENGTH} e {MAX_CODE_LENGTH}."
            )

        group = options["group"]
        created = [
            Student.create_with_generated_code(group=group, length=length)
            for _ in range(count)
        ]

        self.stdout.write(f"{len(created)} codigos gerados ({group}):")
        for student in created:
            self.stdout.write(f"  {student.code}")
