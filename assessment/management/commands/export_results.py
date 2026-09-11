"""
Exporta o dado comparativo do estudo em CSV.

Uma linha por aluno, com turma, pre, pos e ganho. A analise estatistica acontece
fora daqui — o sistema entrega o dado bruto e mais nada, para que qualquer
numero citado no TCC2 possa ser refeito a mao a partir do CSV de respostas
(`export_responses`).

Aplicacao nao concluida sai como celula vazia, nunca como zero: zero significa
"errou todas", vazio significa "nao fez". Tratar os dois como a mesma coisa
enviesaria o ganho medio.
"""

import csv
import io

from django.core.management.base import BaseCommand

from assessment.services import instrument_results
from students.models import Student, StudyGroup

COLUMNS = [
    "codigo",
    "turma",
    "pre_acertos",
    "pos_acertos",
    "ganho",
    "total_questoes",
    "pre_concluido_em",
    "pos_concluido_em",
    "usou_o_app",
    "sessoes_no_app",
]


class Command(BaseCommand):
    help = "Exporta turma, pre-teste, pos-teste e ganho de cada aluno, em CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default=None,
            help="Arquivo de saida. Sem isso, escreve na saida padrao.",
        )
        parser.add_argument(
            "--group",
            choices=[choice.value for choice in StudyGroup],
            default=None,
            help="Exporta so uma das turmas. Sem isso, exporta as duas.",
        )

    def handle(self, *args, **options):
        students = Student.objects.prefetch_related(
            "instrument_sessions", "assessment_sessions"
        ).order_by("group", "code")
        if options["group"]:
            students = students.filter(group=options["group"])

        rows = [self._row(student) for student in students]

        if options["output"]:
            with open(options["output"], "w", newline="", encoding="utf-8") as handle:
                self._write(handle, rows)
            self.stdout.write(
                self.style.SUCCESS(
                    f"{len(rows)} alunos exportados para {options['output']}."
                )
            )
        else:
            # Passa pelo `self.stdout` do Django, e nao pelo `sys.stdout` cru,
            # para respeitar redirecionamento. `ending=""` evita que o wrapper
            # acrescente uma quebra de linha extra ao CSV.
            buffer = io.StringIO()
            self._write(buffer, rows)
            self.stdout.write(buffer.getvalue(), ending="")

    def _row(self, student: Student) -> dict:
        results = instrument_results(student)
        finished_app_sessions = student.assessment_sessions.filter(
            finished_at__isnull=False
        ).count()
        return {
            "codigo": student.code,
            "turma": student.group,
            "pre_acertos": results["pre_score"],
            "pos_acertos": results["post_score"],
            "ganho": results["gain"],
            "total_questoes": results["max_score"],
            "pre_concluido_em": self._moment(results["pre_finished_at"]),
            "pos_concluido_em": self._moment(results["post_finished_at"]),
            # Coluna de auditoria: um aluno de controle com isto em "sim" seria
            # contaminacao do desenho, e precisa aparecer no dado, nao ficar
            # escondido.
            "usou_o_app": "sim" if finished_app_sessions else "nao",
            "sessoes_no_app": finished_app_sessions,
        }

    @staticmethod
    def _moment(value) -> str:
        return value.isoformat(timespec="seconds") if value else ""

    @staticmethod
    def _write(handle, rows) -> None:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if value is None else value for key, value in row.items()})
