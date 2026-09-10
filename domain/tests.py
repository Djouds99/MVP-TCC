"""
Testes do dominio.

O foco esta na geracao do espaco de conhecimento e na validacao do arquivo de
curriculo: sao as duas coisas que, se estiverem erradas, tornam errada toda
recomendacao construida em cima delas.
"""

import json
import tempfile
from io import StringIO
from itertools import combinations
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from domain.curriculum import CurriculumError, load_curriculum
from domain.knowledge_space import (
    PrerequisiteCycleError,
    generate_knowledge_states,
    is_knowledge_state,
    transitive_closure,
)
from domain.models import CurriculumRelease, KnowledgeItem, KnowledgeState, Topic


def write_curriculum(payload: dict) -> Path:
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    )
    with handle:
        json.dump(payload, handle, ensure_ascii=False)
    return Path(handle.name)


def minimal_payload(**overrides) -> dict:
    payload = {
        "version": "test",
        "subject": "Matemática",
        "topics": [
            {
                "code": "t1",
                "name": "Topico 1",
                "position": 1,
                "prerequisites": [],
                "items": [
                    {"code": "a1", "name": "A1", "position": 1, "prerequisites": []},
                    {"code": "a2", "name": "A2", "position": 2, "prerequisites": ["a1"]},
                ],
            },
            {
                "code": "t2",
                "name": "Topico 2",
                "position": 2,
                "prerequisites": ["t1"],
                "items": [
                    {
                        "code": "b1",
                        "name": "B1",
                        "position": 1,
                        "prerequisites": ["a2"],
                    },
                ],
            },
        ],
    }
    payload.update(overrides)
    return payload


class TransitiveClosureTests(TestCase):
    def test_chain_accumulates_ancestors(self):
        closure = transitive_closure({"a": [], "b": ["a"], "c": ["b"]})
        self.assertEqual(closure["a"], frozenset())
        self.assertEqual(closure["b"], {"a"})
        self.assertEqual(closure["c"], {"a", "b"})

    def test_diamond_does_not_duplicate(self):
        closure = transitive_closure(
            {"a": [], "b": ["a"], "c": ["a"], "d": ["b", "c"]}
        )
        self.assertEqual(closure["d"], {"a", "b", "c"})

    def test_cycle_is_rejected(self):
        with self.assertRaises(PrerequisiteCycleError):
            transitive_closure({"a": ["b"], "b": ["a"]})

    def test_unknown_prerequisite_is_rejected(self):
        with self.assertRaises(ValueError):
            transitive_closure({"a": ["fantasma"]})


class KnowledgeSpaceTests(TestCase):
    def test_independent_items_give_full_powerset(self):
        states = generate_knowledge_states({"a": [], "b": []})
        self.assertEqual(len(states), 4)

    def test_chain_gives_only_prefixes(self):
        states = generate_knowledge_states({"a": [], "b": ["a"], "c": ["a", "b"]})
        self.assertEqual(
            [sorted(state) for state in states],
            [[], ["a"], ["a", "b"], ["a", "b", "c"]],
        )

    def test_empty_and_full_states_are_always_present(self):
        closure = transitive_closure({"a": [], "b": ["a"], "c": ["a"]})
        states = generate_knowledge_states(closure)
        self.assertIn(frozenset(), states)
        self.assertIn(frozenset({"a", "b", "c"}), states)

    def test_matches_brute_force_enumeration(self):
        """
        Confere a busca incremental contra a definicao: varrer todos os
        subconjuntos e ficar com os fechados para baixo. So e viavel porque o
        dominio deste MVP e pequeno — serve de rede de seguranca, nao de metodo.
        """
        closure = load_curriculum().item_prerequisite_closure()
        codes = sorted(closure)

        brute_force = {
            frozenset(subset)
            for size in range(len(codes) + 1)
            for subset in combinations(codes, size)
            if is_knowledge_state(subset, closure)
        }
        self.assertEqual(set(generate_knowledge_states(closure)), brute_force)


class CurriculumFileTests(TestCase):
    def test_real_curriculum_loads(self):
        curriculum = load_curriculum()
        self.assertEqual(len(curriculum.topics), 5)
        self.assertEqual(len(curriculum.item_codes), 15)
        self.assertEqual(len(set(curriculum.item_codes)), 15)

    def test_checksum_changes_with_content(self):
        first = load_curriculum(write_curriculum(minimal_payload()))
        second = load_curriculum(write_curriculum(minimal_payload(version="outra")))
        self.assertNotEqual(first.checksum, second.checksum)

    def test_closure_is_exactly_what_the_items_declare(self):
        curriculum = load_curriculum(write_curriculum(minimal_payload()))
        closure = curriculum.item_prerequisite_closure()
        # b1 declara a2, que declara a1. Nada vem de heranca de topico.
        self.assertEqual(closure["b1"], {"a1", "a2"})

    def test_partial_access_across_topics_is_allowed(self):
        """
        A regra validada em 10/09/2026 (CLAUDE.md secao 9): um item pode
        depender de parte de um topico anterior, nao do topico inteiro.
        """
        payload = minimal_payload()
        payload["topics"][1]["items"][0]["prerequisites"] = ["a1"]

        closure = load_curriculum(
            write_curriculum(payload)
        ).item_prerequisite_closure()

        self.assertEqual(closure["b1"], {"a1"})
        self.assertNotIn("a2", closure["b1"])

    def test_edge_into_a_topic_outside_the_chain_is_rejected(self):
        payload = minimal_payload()
        # t2 deixa de declarar t1, mas b1 continua apontando para la.
        payload["topics"][1]["prerequisites"] = []
        with self.assertRaisesMessage(CurriculumError, "nao esta na cadeia"):
            load_curriculum(write_curriculum(payload))

    def test_topic_prerequisite_without_any_item_edge_is_rejected(self):
        """
        A cadeia de topicos nao gera mais aresta nenhuma, entao ela pode
        divergir da estrutura de itens em silencio. Aqui ela afirma uma
        dependencia que nenhum item realiza.
        """
        payload = minimal_payload()
        payload["topics"][1]["items"][0]["prerequisites"] = []
        with self.assertRaisesMessage(CurriculumError, "nenhum item"):
            load_curriculum(write_curriculum(payload))

    def test_item_prerequisite_that_does_not_exist_is_rejected(self):
        payload = minimal_payload()
        payload["topics"][1]["items"][0]["prerequisites"] = ["fantasma"]
        with self.assertRaisesMessage(CurriculumError, "pre-requisito inexistente"):
            load_curriculum(write_curriculum(payload))

    def test_duplicate_item_code_is_rejected(self):
        payload = minimal_payload()
        payload["topics"][1]["items"][0]["code"] = "a1"
        with self.assertRaisesMessage(CurriculumError, "Codigo de item duplicado"):
            load_curriculum(write_curriculum(payload))

    def test_unknown_topic_prerequisite_is_rejected(self):
        payload = minimal_payload()
        payload["topics"][1]["prerequisites"] = ["fantasma"]
        with self.assertRaisesMessage(CurriculumError, "pre-requisito inexistente"):
            load_curriculum(write_curriculum(payload))

    def test_cycle_between_topics_is_rejected(self):
        payload = minimal_payload()
        payload["topics"][0]["prerequisites"] = ["t2"]
        with self.assertRaises(PrerequisiteCycleError):
            load_curriculum(write_curriculum(payload))

    def test_difficulty_outside_range_is_rejected(self):
        payload = minimal_payload()
        payload["topics"][0]["items"][0]["difficulty"] = 9
        with self.assertRaisesMessage(CurriculumError, "fora do intervalo"):
            load_curriculum(write_curriculum(payload))


class LoadCurriculumCommandTests(TestCase):
    def test_loads_real_curriculum_into_database(self):
        call_command("load_curriculum", verbosity=0, stdout=StringIO())

        self.assertEqual(Topic.objects.count(), 5)
        self.assertEqual(KnowledgeItem.objects.count(), 15)
        self.assertEqual(KnowledgeState.objects.count(), 46)
        self.assertTrue(KnowledgeState.objects.filter(signature="").exists())
        self.assertEqual(
            KnowledgeState.objects.order_by("-size").first().size,
            KnowledgeItem.objects.count(),
        )

    def test_is_idempotent(self):
        call_command("load_curriculum", verbosity=0, stdout=StringIO())
        state_ids = set(KnowledgeState.objects.values_list("id", flat=True))

        call_command("load_curriculum", verbosity=0, stdout=StringIO())

        self.assertEqual(Topic.objects.count(), 5)
        self.assertEqual(KnowledgeItem.objects.count(), 15)
        self.assertEqual(KnowledgeState.objects.count(), 46)
        # As linhas sao reaproveitadas, e nao recriadas: referencias vindas de
        # outras tabelas continuam validas depois de recarregar o curriculo.
        self.assertEqual(
            state_ids, set(KnowledgeState.objects.values_list("id", flat=True))
        )

    def test_stored_closure_matches_computed_closure(self):
        call_command("load_curriculum", verbosity=0, stdout=StringIO())
        closure = load_curriculum().item_prerequisite_closure()

        for item in KnowledgeItem.objects.all():
            self.assertEqual(
                set(item.prerequisites.values_list("code", flat=True)),
                set(closure[item.code]),
                f"fecho divergente para {item.code}",
            )

    def test_records_the_loaded_version(self):
        call_command("load_curriculum", verbosity=0, stdout=StringIO())
        release = CurriculumRelease.objects.latest()
        self.assertEqual(release.version, load_curriculum().version)
        self.assertEqual(release.item_count, 15)
        self.assertEqual(release.state_count, 46)

    def test_dry_run_writes_nothing(self):
        call_command("load_curriculum", dry_run=True, verbosity=0, stdout=StringIO())
        self.assertEqual(Topic.objects.count(), 0)
        self.assertEqual(KnowledgeState.objects.count(), 0)

    def test_refuses_to_drop_orphans_without_prune(self):
        call_command("load_curriculum", verbosity=0, stdout=StringIO())
        path = write_curriculum(minimal_payload())

        with self.assertRaisesMessage(CommandError, "--prune"):
            call_command("load_curriculum", path=str(path), verbosity=0, stdout=StringIO())

        # A transacao foi revertida: o curriculo anterior segue intacto.
        self.assertEqual(Topic.objects.count(), 5)
        self.assertEqual(KnowledgeItem.objects.count(), 15)

    def test_prune_replaces_the_previous_curriculum(self):
        call_command("load_curriculum", verbosity=0, stdout=StringIO())
        path = write_curriculum(minimal_payload())

        call_command("load_curriculum", path=str(path), prune=True, verbosity=0, stdout=StringIO())

        self.assertEqual(
            sorted(Topic.objects.values_list("code", flat=True)), ["t1", "t2"]
        )
        self.assertEqual(KnowledgeItem.objects.count(), 3)
        # Cadeia a1 -> a2 -> b1: so os prefixos sao estados validos.
        self.assertEqual(KnowledgeState.objects.count(), 4)
