"""
Ordenacao deterministica das consultas.

SQLite e Postgres nao prometem ordem estavel entre linhas empatadas, e desempatam
de jeitos diferentes. Uma consulta cuja ordenacao nao inclui uma chave unica pode
dar um resultado nos testes, que rodam em SQLite, e outro em producao, que roda
em Postgres. Foi assim que a amostra da tela de recomendacao escondeu, ate a
Parte 5, uma questao do instrumento empatada com a adaptativa.

Os testes daqui verificam a estrutura da ordenacao, e nao o resultado de uma
execucao: ver uma consulta devolver a ordem certa no SQLite nao prova nada sobre
o Postgres.
"""

from io import StringIO

from django.apps import apps
from django.core.management import call_command
from django.db.models import UniqueConstraint
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from assessment.models import InstrumentResponse, StudyPhase, StudySettings, StudyStage
from assessment.services import (
    finalize,
    next_question,
    record_response,
    start_instrument,
    start_session,
)
from assessment.testing import complete_instrument
from domain.models import CurriculumRelease, KnowledgeItem, Topic
from students.models import Student, StudyGroup

PROJECT_APPS = ("domain", "students", "assessment")


def is_total(model, ordering) -> bool:
    """
    A ordenacao distingue qualquer par de linhas de `model`?

    So conta o que o banco garante: `pk`, campo unico do proprio modelo, ou um
    conjunto de campos coberto por restricao de unicidade. Campo de outro modelo
    (`topic__position`) nao garante nada sobre as linhas deste.
    """
    local = []
    for entry in ordering:
        name = str(entry).lstrip("-")
        if name == "pk":
            return True
        if "__" not in name:
            local.append(model._meta.get_field(name))
    if any(field.unique or field.primary_key for field in local):
        return True
    present = {field.name for field in local} | {field.attname for field in local}
    unique_sets = [
        set(constraint.fields)
        for constraint in model._meta.constraints
        if isinstance(constraint, UniqueConstraint)
    ] + [set(fields) for fields in model._meta.unique_together]
    return any(fields <= present for fields in unique_sets)


class OrderingCheckerTests(SimpleTestCase):
    """
    O verificador precisa reprovar o que deve reprovar; se aprovasse tudo, os
    testes abaixo passariam sem provar nada.
    """

    def test_rejects_orderings_without_a_unique_key(self):
        self.assertFalse(is_total(Topic, ["position"]))
        self.assertFalse(is_total(KnowledgeItem, ["topic__position", "position"]))
        self.assertFalse(is_total(CurriculumRelease, ["-loaded_at"]))

    def test_accepts_orderings_with_a_unique_key(self):
        self.assertTrue(is_total(Topic, ["position", "code"]))
        self.assertTrue(is_total(CurriculumRelease, ["-loaded_at", "-pk"]))
        # Coberto pela restricao de unicidade (session, question).
        self.assertTrue(is_total(InstrumentResponse, ["session", "question"]))


class DefaultOrderingTests(SimpleTestCase):
    def test_every_model_default_ordering_is_total(self):
        """
        Toda consulta sem `order_by` herda o `Meta.ordering`. Uma ordenacao
        padrao sem chave unica e um empate esperando a proxima consulta que
        confiar nela.
        """
        for label in PROJECT_APPS:
            for model in apps.get_app_config(label).get_models():
                ordering = model._meta.ordering
                if not ordering:
                    continue
                with self.subTest(modelo=model.__name__):
                    self.assertTrue(
                        is_total(model, ordering),
                        f"{model.__name__}.Meta.ordering = {list(ordering)} "
                        "nao tem chave unica",
                    )


class QueryOrderingTests(TestCase):
    """
    As consultas explicitas que decidem ordem de tela, carimbo de versao de
    conteudo e ordem da exportacao de auditoria.
    """

    @classmethod
    def setUpTestData(cls):
        call_command("load_curriculum", verbosity=0, stdout=StringIO())
        cls.student = Student.objects.create(code="ARD23", group=StudyGroup.PILOT)
        cls.goal = KnowledgeItem.objects.get(code="lg-equacao-exponencial")

    def open_finished_recommendation(self):
        StudySettings.objects.filter(group=StudyGroup.PILOT).update(
            stage=StudyStage.ACTIVITY
        )
        complete_instrument(self.student, StudyPhase.PRE)
        session = start_session(self.student, self.goal)
        while (question := next_question(session)) is not None:
            record_response(session, question, question.correct_index)
        finalize(session)

        client_session = self.client.session
        client_session["student_id"] = self.student.pk
        client_session["assessment_session_id"] = session.pk
        client_session.save()
        return self.client.get(reverse("assessment:recommendation"))

    def test_mastered_items_on_the_recommendation_screen(self):
        response = self.open_finished_recommendation()

        queryset = response.context["mastered_items"]
        self.assertTrue(queryset.exists())
        self.assertTrue(is_total(KnowledgeItem, queryset.query.order_by))

    def test_topics_on_the_status_page(self):
        response = self.client.get(reverse("status"))

        self.assertTrue(is_total(Topic, response.context["topics"].query.order_by))

    def test_response_export_order(self):
        from assessment.management.commands.export_responses import (
            responses_in_export_order,
        )

        self.assertTrue(
            is_total(InstrumentResponse, responses_in_export_order().query.order_by)
        )

    def test_sessions_are_stamped_with_an_unambiguous_release(self):
        """
        Duas cargas com o mesmo `loaded_at` sao improvaveis, mas o carimbo de
        versao e o que permite afirmar no TCC2 sobre qual conteudo cada medida
        foi feita. Com empate, vale a carga mais recente: a de maior `pk`.
        """
        older = CurriculumRelease.objects.order_by("-pk").first()
        newer = CurriculumRelease.objects.create(
            version=older.version, checksum=older.checksum
        )
        CurriculumRelease.objects.filter(pk=newer.pk).update(loaded_at=older.loaded_at)

        self.assertEqual(
            start_session(self.student, self.goal).curriculum_release_id, newer.pk
        )
        self.assertEqual(
            start_instrument(self.student, StudyPhase.PRE).curriculum_release_id,
            newer.pk,
        )
        self.assertEqual(
            self.client.get(reverse("status")).context["release"].pk, newer.pk
        )
