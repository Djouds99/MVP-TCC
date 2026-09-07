"""
Carrega `domain/data/curriculum.json` no banco e regenera o espaco de conhecimento.

O comando e idempotente: rodar duas vezes seguidas com o mesmo arquivo deixa o
banco no mesmo estado. O arquivo continua sendo a fonte da verdade; o banco e
uma projecao dele.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from domain.curriculum import CurriculumError, load_curriculum
from domain.knowledge_space import generate_knowledge_states
from domain.models import CurriculumRelease, KnowledgeItem, KnowledgeState, Topic


class Command(BaseCommand):
    help = "Carrega o curriculo versionado e regenera os estados de conhecimento."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default=None,
            help="Arquivo de curriculo alternativo (padrao: domain/data/curriculum.json).",
        )
        parser.add_argument(
            "--prune",
            action="store_true",
            help=(
                "Autoriza remover do banco topicos e itens que nao existem mais no "
                "arquivo. Sem esta opcao o comando falha ao encontrar orfaos, para "
                "nao apagar em cascata dados ja coletados."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Valida o arquivo e mostra o resumo, sem escrever no banco.",
        )

    def handle(self, *args, **options):
        try:
            curriculum = load_curriculum(options["path"])
        except CurriculumError as exc:
            raise CommandError(f"Curriculo invalido: {exc}") from exc

        closure = curriculum.item_prerequisite_closure()
        states = generate_knowledge_states(closure)

        self.stdout.write(
            f"Curriculo {curriculum.version} ({curriculum.checksum[:12]}): "
            f"{len(curriculum.topics)} topicos, {len(closure)} itens, "
            f"{len(states)} estados de conhecimento."
        )

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("--dry-run: nada foi gravado."))
            return

        with transaction.atomic():
            self._check_orphans(curriculum, prune=options["prune"])
            self._sync_topics(curriculum)
            self._sync_items(curriculum, closure)
            self._sync_states(states)

            CurriculumRelease.objects.create(
                version=curriculum.version,
                checksum=curriculum.checksum,
                item_count=len(closure),
                state_count=len(states),
            )

        self.stdout.write(self.style.SUCCESS("Curriculo carregado."))

    def _check_orphans(self, curriculum, *, prune: bool) -> None:
        topic_codes = {topic.code for topic in curriculum.topics}
        item_codes = set(curriculum.item_codes)

        stale_topics = Topic.objects.exclude(code__in=topic_codes)
        stale_items = KnowledgeItem.objects.exclude(code__in=item_codes)

        if not stale_topics.exists() and not stale_items.exists():
            return

        if not prune:
            orphans = sorted(
                list(stale_topics.values_list("code", flat=True))
                + list(stale_items.values_list("code", flat=True))
            )
            raise CommandError(
                "Existem no banco topicos/itens que nao estao mais no arquivo: "
                + ", ".join(orphans)
                + ". Rode novamente com --prune se a remocao for mesmo intencional "
                "(ela apaga em cascata o que depender desses registros)."
            )

        removed_items = stale_items.count()
        removed_topics = stale_topics.count()
        stale_items.delete()
        stale_topics.delete()
        self.stdout.write(
            self.style.WARNING(
                f"--prune: removidos {removed_topics} topicos e {removed_items} itens."
            )
        )

    def _sync_topics(self, curriculum) -> None:
        for spec in curriculum.topics:
            Topic.objects.update_or_create(
                code=spec.code,
                defaults={
                    "name": spec.name,
                    "summary": spec.summary,
                    "position": spec.position,
                    "bncc_skills": list(spec.bncc_skills),
                },
            )

        topics_by_code = {topic.code: topic for topic in Topic.objects.all()}
        for spec in curriculum.topics:
            topics_by_code[spec.code].prerequisites.set(
                [topics_by_code[code] for code in spec.prerequisites]
            )

    def _sync_items(self, curriculum, closure) -> None:
        topics_by_code = {topic.code: topic for topic in Topic.objects.all()}

        for spec in curriculum.iter_items():
            KnowledgeItem.objects.update_or_create(
                code=spec.code,
                defaults={
                    "topic": topics_by_code[spec.topic_code],
                    "name": spec.name,
                    "description": spec.description,
                    "position": spec.position,
                    "difficulty": spec.difficulty,
                },
            )

        items_by_code = {item.code: item for item in KnowledgeItem.objects.all()}
        # Grava o fecho transitivo, nao so as arestas diretas: consultar "o que
        # este item exige" vira uma unica leitura, sem percorrer o grafo.
        for code, prerequisites in closure.items():
            items_by_code[code].prerequisites.set(
                [items_by_code[prerequisite] for prerequisite in prerequisites]
            )

    def _sync_states(self, states) -> None:
        items_by_code = {item.code: item for item in KnowledgeItem.objects.all()}
        signatures = {KnowledgeState.make_signature(state): state for state in states}

        # Casa pela assinatura em vez de recriar tudo: os estados sao referenciados
        # por outras tabelas nas etapas seguintes do projeto, e recriar as linhas
        # invalidaria essas referencias.
        removed = KnowledgeState.objects.exclude(signature__in=signatures).delete()[0]
        if removed:
            self.stdout.write(f"Estados removidos por nao existirem mais: {removed}.")

        for signature, item_codes in signatures.items():
            state, _ = KnowledgeState.objects.update_or_create(
                signature=signature, defaults={"size": len(item_codes)}
            )
            state.items.set([items_by_code[code] for code in item_codes])
