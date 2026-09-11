"""
Exporta resposta a resposta do instrumento, para auditoria manual.

Existe para que os escores de `export_results` possam ser recalculados a mao:
contar as linhas com `acertou=sim` de um aluno numa fase tem que dar exatamente
o numero que a outra exportacao mostra. Sem isso, o escore seria um numero que
so o sistema sabe de onde veio.
"""

import csv
import io

from django.core.management.base import BaseCommand

from assessment.models import InstrumentResponse

COLUMNS = [
    "codigo",
    "turma",
    "fase",
    "questao",
    "item",
    "topico",
    "ordem",
    "alternativa_escolhida",
    "acertou",
    "respondido_em",
]


class Command(BaseCommand):
    help = "Exporta cada resposta do pre/pos-teste, em CSV, para auditoria."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default=None,
            help="Arquivo de saida. Sem isso, escreve na saida padrao.",
        )

    def handle(self, *args, **options):
        responses = (
            InstrumentResponse.objects.select_related(
                "session__student", "question__item__topic"
            )
            .order_by(
                "session__student__group",
                "session__student__code",
                "session__phase",
                "question__position",
            )
        )

        rows = [
            {
                "codigo": response.session.student.code,
                "turma": response.session.student.group,
                "fase": response.session.phase,
                "questao": response.question.code,
                "item": response.question.item.code,
                "topico": response.question.item.topic.code,
                "ordem": response.question.position,
                "alternativa_escolhida": (
                    "" if response.chosen_index is None else response.chosen_index
                ),
                "acertou": "sim" if response.is_correct else "nao",
                "respondido_em": response.answered_at.isoformat(timespec="seconds"),
            }
            for response in responses
        ]

        if options["output"]:
            with open(options["output"], "w", newline="", encoding="utf-8") as handle:
                self._write(handle, rows)
            self.stdout.write(
                self.style.SUCCESS(
                    f"{len(rows)} respostas exportadas para {options['output']}."
                )
            )
        else:
            # Passa pelo `self.stdout` do Django, e nao pelo `sys.stdout` cru,
            # para respeitar redirecionamento. `ending=""` evita que o wrapper
            # acrescente uma quebra de linha extra ao CSV.
            buffer = io.StringIO()
            self._write(buffer, rows)
            self.stdout.write(buffer.getvalue(), ending="")

    @staticmethod
    def _write(handle, rows) -> None:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
