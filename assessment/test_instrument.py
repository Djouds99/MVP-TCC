"""
Testes do instrumento de pesquisa: pre-teste, pos-teste e exportacao.

O teste que fecha a Parte 5 e `ComparativeExportTests.test_pilot_and_control_
both_appear_with_pre_post_and_gain`: percorre um aluno piloto e um aluno
controle pelo HTTP, do codigo ate o pos-teste, e confere que a exportacao mostra
turma, pre, pos e ganho para os dois — inclusive para o controle, que nunca
tocou no motor de recomendacao.
"""

import csv
import io
import re
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from assessment.models import (
    AssessmentSession,
    InstrumentResponse,
    InstrumentSession,
    StudyPhase,
    StudySettings,
    StudyStage,
)
from assessment.services import (
    instrument_questions,
    instrument_results,
    next_instrument_question,
    record_instrument_response,
    start_instrument,
)
from assessment.testing import complete_instrument
from domain.models import Question, QuestionPurpose
from students.models import Student, StudyGroup


def read_csv(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


class InstrumentTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_curriculum", verbosity=0, stdout=StringIO())
        cls.pilot = Student.objects.create(code="ABC23", group=StudyGroup.PILOT)
        cls.control = Student.objects.create(code="XYZ45", group=StudyGroup.CONTROL)

    def set_stage(self, stage: str, group: str | None = None):
        """Coloca uma turma na etapa dada — ou as duas, se `group` for omitido."""
        groups = [group] if group else [choice.value for choice in StudyGroup]
        for value in groups:
            StudySettings.objects.update_or_create(
                group=value, defaults={"stage": stage}
            )

    def enter_as(self, student: Student):
        return self.client.post(reverse("assessment:identify"), {"code": student.code})

    def answer_instrument(self, correct_codes: set[str]) -> int:
        """
        Responde o instrumento inteiro pelo HTTP, acertando as questoes cujos
        codigos estao em `correct_codes`. Devolve quantas foram respondidas.
        """
        answered = 0
        while True:
            response = self.client.get(reverse("assessment:instrument"))
            if response.status_code != 200:
                return answered
            question = response.context["question"]
            chosen = (
                question.correct_index
                if question.code in correct_codes
                else (question.correct_index + 1) % len(question.alternatives)
            )
            self.client.post(
                reverse("assessment:instrument"),
                {"question": question.pk, "alternative": chosen},
            )
            answered += 1


class SeparationFromTheAdaptiveBankTests(InstrumentTestCase):
    """
    O instrumento e o banco adaptativo nao podem se cruzar: a turma piloto ve o
    banco adaptativo durante a atividade, e medi-la pelos mesmos itens
    transformaria parte do ganho em artefato do instrumento.
    """

    def test_the_two_banks_share_no_question(self):
        adaptive = set(
            Question.objects.filter(purpose=QuestionPurpose.ADAPTIVE).values_list(
                "code", flat=True
            )
        )
        instrument = {question.code for question in instrument_questions()}

        self.assertTrue(adaptive)
        self.assertTrue(instrument)
        self.assertFalse(adaptive & instrument)

    def test_the_two_banks_share_no_statement(self):
        # Codigos diferentes com o mesmo enunciado dariam na mesma exposicao.
        adaptive = set(
            Question.objects.filter(purpose=QuestionPurpose.ADAPTIVE).values_list(
                "statement", flat=True
            )
        )
        instrument = {question.statement for question in instrument_questions()}
        self.assertFalse(adaptive & instrument)

    def test_the_adaptive_test_never_serves_an_instrument_question(self):
        from assessment.services import next_question, start_session

        self.set_stage(StudyStage.ACTIVITY)
        complete_instrument(self.pilot, StudyPhase.PRE)
        session = start_session(
            self.pilot, Question.objects.first().item
        )

        served = []
        from assessment.services import record_response

        while (question := next_question(session)) is not None:
            served.append(question)
            record_response(session, question, question.correct_index)

        self.assertTrue(served)
        for question in served:
            self.assertEqual(question.purpose, QuestionPurpose.ADAPTIVE)

    def test_the_instrument_covers_every_topic(self):
        topics = {question.item.topic.code for question in instrument_questions()}
        self.assertEqual(len(topics), 5)


class InstrumentFlowTests(InstrumentTestCase):
    def test_fixed_order_is_the_same_for_every_student(self):
        """
        Nao ha adaptacao no instrumento: a ordem e identica para todo aluno, nas
        duas turmas. E o que torna os escores comparaveis.
        """
        self.set_stage(StudyStage.PRE_TEST)

        orders = []
        for student in (self.pilot, self.control):
            self.enter_as(student)
            seen = []
            while True:
                response = self.client.get(reverse("assessment:instrument"))
                if response.status_code != 200:
                    break
                question = response.context["question"]
                seen.append(question.code)
                self.client.post(
                    reverse("assessment:instrument"),
                    {"question": question.pk, "alternative": 0},
                )
            orders.append(seen)
            self.client.post(reverse("assessment:leave"))

        self.assertEqual(orders[0], orders[1])
        self.assertEqual(
            orders[0], [question.code for question in instrument_questions()]
        )

    def test_control_group_can_take_the_instrument(self):
        """
        O ponto que o roadmap alertou: o bloqueio da Parte 4 nao pode alcancar
        o instrumento, senao o grupo controle fica fora da propria comparacao.
        """
        self.set_stage(StudyStage.PRE_TEST)
        self.enter_as(self.control)

        answered = self.answer_instrument(set())

        self.assertEqual(answered, len(instrument_questions()))
        session = InstrumentSession.objects.get(
            student=self.control, phase=StudyPhase.PRE
        )
        self.assertTrue(session.is_finished)

    def test_score_counts_the_correct_answers(self):
        self.set_stage(StudyStage.PRE_TEST)
        self.enter_as(self.pilot)
        correct = {question.code for question in instrument_questions()[:4]}

        self.answer_instrument(correct)

        session = InstrumentSession.objects.get(
            student=self.pilot, phase=StudyPhase.PRE
        )
        self.assertEqual(session.score, 4)

    def test_finishing_shows_a_confirmation(self):
        self.set_stage(StudyStage.PRE_TEST)
        self.enter_as(self.pilot)
        self.answer_instrument(set())

        response = self.client.get(reverse("assessment:instrument_done"))

        self.assertContains(response, "prova inicial")

    def test_a_finished_phase_is_not_offered_again(self):
        self.set_stage(StudyStage.PRE_TEST)
        complete_instrument(self.pilot, StudyPhase.PRE)
        self.enter_as(self.pilot)

        response = self.client.get(reverse("assessment:instrument"))

        self.assertRedirects(
            response, reverse("assessment:next_step"), target_status_code=200
        )
        self.assertEqual(
            InstrumentSession.objects.filter(
                student=self.pilot, phase=StudyPhase.PRE
            ).count(),
            1,
        )

    def test_a_stale_submission_is_ignored(self):
        self.set_stage(StudyStage.PRE_TEST)
        self.enter_as(self.pilot)
        first = self.client.get(reverse("assessment:instrument")).context["question"]
        self.client.post(
            reverse("assessment:instrument"),
            {"question": first.pk, "alternative": 0},
        )

        self.client.post(
            reverse("assessment:instrument"),
            {"question": first.pk, "alternative": 0},
        )

        session = InstrumentSession.objects.get(
            student=self.pilot, phase=StudyPhase.PRE
        )
        self.assertEqual(session.responses.count(), 1)

    def test_no_markup_distinguishes_the_correct_alternative(self):
        self.set_stage(StudyStage.PRE_TEST)
        self.enter_as(self.pilot)

        response = self.client.get(reverse("assessment:instrument"))
        html = response.content.decode()

        inputs = re.findall(r'<input type="radio" name="alternative"[^>]*>', html)
        self.assertEqual(len(inputs), len(response.context["question"].alternatives))
        for tag in inputs:
            self.assertNotIn("checked", tag)
        self.assertNotIn("correct", html)

    def test_an_incomplete_application_cannot_be_finalized(self):
        from assessment.services import finalize_instrument

        session = start_instrument(self.pilot, StudyPhase.PRE)
        question = next_instrument_question(session)
        record_instrument_response(session, question, question.correct_index)

        with self.assertRaisesMessage(ValueError, "escore parcial"):
            finalize_instrument(session)

    def test_an_adaptive_question_is_refused_by_the_instrument(self):
        session = start_instrument(self.pilot, StudyPhase.PRE)
        adaptive = Question.objects.filter(purpose=QuestionPurpose.ADAPTIVE).first()

        with self.assertRaisesMessage(ValueError, "nao pertence ao instrumento"):
            record_instrument_response(session, adaptive, 0)


class StageGateTests(InstrumentTestCase):
    """
    A etapa e decidida pelo professor, nao pelo aluno. Sem isso, "antes" e
    "depois" deixariam de significar alguma coisa.
    """

    def test_each_group_starts_at_the_pre_test(self):
        self.assertEqual(StudySettings.objects.count(), 2)
        for group in StudyGroup:
            with self.subTest(turma=group.value):
                self.assertEqual(
                    StudySettings.for_group(group).stage, StudyStage.PRE_TEST
                )

    def test_the_post_test_is_not_reachable_during_the_pre_test_stage(self):
        self.set_stage(StudyStage.PRE_TEST)
        self.enter_as(self.pilot)
        self.answer_instrument(set())

        self.assertFalse(
            InstrumentSession.objects.filter(
                student=self.pilot, phase=StudyPhase.POST
            ).exists()
        )

    def test_the_pre_test_stage_does_not_open_the_app(self):
        self.set_stage(StudyStage.PRE_TEST)
        complete_instrument(self.pilot, StudyPhase.PRE)
        self.enter_as(self.pilot)

        response = self.client.get(reverse("assessment:next_step"))

        self.assertContains(response, "Tudo certo por enquanto")
        self.assertRedirects(
            self.client.get(reverse("assessment:choose_goal")),
            reverse("assessment:next_step"),
            target_status_code=200,
        )

    def test_a_late_student_still_takes_the_pre_test_during_the_activity(self):
        self.set_stage(StudyStage.ACTIVITY)
        self.enter_as(self.pilot)

        response = self.client.get(reverse("assessment:next_step"))

        self.assertRedirects(response, reverse("assessment:instrument"))
        self.answer_instrument(set())
        self.assertTrue(
            InstrumentSession.objects.filter(
                student=self.pilot, phase=StudyPhase.PRE, finished_at__isnull=False
            ).exists()
        )

    def test_the_post_test_stage_sends_everyone_to_the_post_test(self):
        complete_instrument(self.pilot, StudyPhase.PRE)
        complete_instrument(self.control, StudyPhase.PRE)
        self.set_stage(StudyStage.POST_TEST)

        for student in (self.pilot, self.control):
            with self.subTest(turma=student.group):
                self.enter_as(student)
                self.assertRedirects(
                    self.client.get(reverse("assessment:next_step")),
                    reverse("assessment:instrument"),
                )
                self.client.post(reverse("assessment:leave"))

    def test_closed_stage_ends_the_flow(self):
        self.set_stage(StudyStage.CLOSED)
        self.enter_as(self.pilot)

        response = self.client.get(reverse("assessment:next_step"))

        self.assertContains(response, "encerrada")
        self.assertFalse(InstrumentSession.objects.exists())


class ResultsTests(InstrumentTestCase):
    def test_gain_is_post_minus_pre(self):
        complete_instrument(self.pilot, StudyPhase.PRE, correct=3)
        complete_instrument(self.pilot, StudyPhase.POST, correct=7)

        results = instrument_results(self.pilot)

        self.assertEqual(results["pre_score"], 3)
        self.assertEqual(results["post_score"], 7)
        self.assertEqual(results["gain"], 4)
        self.assertEqual(results["max_score"], 10)

    def test_a_negative_gain_is_reported_as_is(self):
        complete_instrument(self.pilot, StudyPhase.PRE, correct=6)
        complete_instrument(self.pilot, StudyPhase.POST, correct=4)

        self.assertEqual(instrument_results(self.pilot)["gain"], -2)

    def test_a_missing_application_is_none_not_zero(self):
        """
        Zero significa "errou todas"; vazio significa "nao fez". Confundir os
        dois enviesaria o ganho medio do grupo para baixo.
        """
        complete_instrument(self.pilot, StudyPhase.PRE, correct=5)

        results = instrument_results(self.pilot)

        self.assertEqual(results["pre_score"], 5)
        self.assertIsNone(results["post_score"])
        self.assertIsNone(results["gain"])

    def test_zero_correct_is_zero_not_none(self):
        complete_instrument(self.pilot, StudyPhase.PRE, correct=0)
        complete_instrument(self.pilot, StudyPhase.POST, correct=0)

        results = instrument_results(self.pilot)

        self.assertEqual(results["pre_score"], 0)
        self.assertEqual(results["gain"], 0)

    def test_an_unfinished_application_does_not_count(self):
        session = start_instrument(self.pilot, StudyPhase.PRE)
        question = next_instrument_question(session)
        record_instrument_response(session, question, question.correct_index)

        self.assertIsNone(instrument_results(self.pilot)["pre_score"])


class ComparativeExportTests(InstrumentTestCase):
    def export(self, **options) -> list[dict]:
        out = StringIO()
        call_command("export_results", stdout=out, **options)
        return read_csv(out.getvalue())

    def walk_full_study(self, student: Student, pre: int, post: int, use_app: bool):
        """Percorre o estudo inteiro pelo HTTP, do codigo ao pos-teste."""
        self.set_stage(StudyStage.PRE_TEST)
        self.enter_as(student)
        correct = {question.code for question in instrument_questions()[:pre]}
        self.answer_instrument(correct)

        self.set_stage(StudyStage.ACTIVITY)
        self.client.get(reverse("assessment:next_step"))
        if use_app:
            topic = self.client.get(
                reverse("assessment:choose_goal")
            ).context["topics"][-1]
            self.client.post(reverse("assessment:choose_goal"), {"topic": topic.pk})
            while True:
                response = self.client.get(reverse("assessment:take_test"))
                if response.status_code != 200:
                    break
                question = response.context["question"]
                self.client.post(
                    reverse("assessment:take_test"),
                    {"question": question.pk, "alternative": question.correct_index},
                )
            self.client.get(reverse("assessment:recommendation"))

        self.set_stage(StudyStage.POST_TEST)
        self.client.get(reverse("assessment:next_step"))
        correct = {question.code for question in instrument_questions()[:post]}
        self.answer_instrument(correct)
        self.client.post(reverse("assessment:leave"))

    def test_pilot_and_control_both_appear_with_pre_post_and_gain(self):
        """
        Criterio de conclusao da Parte 5.

        Um aluno de cada turma percorre o estudo inteiro pelo navegador, sem
        intervencao manual no banco, e a exportacao mostra os dois — inclusive o
        do controle, que nunca tocou no motor de recomendacao.
        """
        self.walk_full_study(self.pilot, pre=3, post=8, use_app=True)
        self.walk_full_study(self.control, pre=4, post=6, use_app=False)

        rows = {row["codigo"]: row for row in self.export()}

        pilot = rows["ABC23"]
        self.assertEqual(pilot["turma"], "pilot")
        self.assertEqual(pilot["pre_acertos"], "3")
        self.assertEqual(pilot["pos_acertos"], "8")
        self.assertEqual(pilot["ganho"], "5")
        self.assertEqual(pilot["usou_o_app"], "sim")

        control = rows["XYZ45"]
        self.assertEqual(control["turma"], "control")
        self.assertEqual(control["pre_acertos"], "4")
        self.assertEqual(control["pos_acertos"], "6")
        self.assertEqual(control["ganho"], "2")
        # O controle fez as duas provas sem nunca ter tocado no motor.
        self.assertEqual(control["usou_o_app"], "nao")
        self.assertEqual(control["sessoes_no_app"], "0")
        self.assertFalse(
            AssessmentSession.objects.filter(student=self.control).exists()
        )

        for row in (pilot, control):
            self.assertEqual(row["total_questoes"], "10")
            self.assertTrue(row["pre_concluido_em"])
            self.assertTrue(row["pos_concluido_em"])

    def test_a_student_who_did_nothing_exports_with_empty_cells(self):
        rows = {row["codigo"]: row for row in self.export()}

        self.assertEqual(rows["ABC23"]["pre_acertos"], "")
        self.assertEqual(rows["ABC23"]["ganho"], "")
        self.assertEqual(rows["ABC23"]["usou_o_app"], "nao")

    def test_export_can_be_filtered_by_group(self):
        codes = {row["codigo"] for row in self.export(group="control")}
        self.assertEqual(codes, {"XYZ45"})

    def test_every_student_appears_exactly_once(self):
        rows = self.export()
        codes = [row["codigo"] for row in rows]
        self.assertEqual(len(codes), Student.objects.count())
        self.assertEqual(len(codes), len(set(codes)))

    def test_counting_the_response_export_rebuilds_the_results_export(self):
        """
        Auditabilidade travada para todo aluno e toda fase — inclusive os dois
        casos em que a igualdade poderia quebrar: aplicacao abandonada no meio e
        aluno que nao fez nada.

        Regra de reconstrucao, a mesma que um auditor aplicaria a mao: o escore
        de uma fase e o numero de linhas com `acertou=sim` entre as linhas com
        `aplicacao_concluida=sim`. Aplicacao abandonada deixa linhas no CSV de
        respostas — o abandono e dado da pesquisa — mas celula vazia no CSV de
        resultados.
        """
        nothing_done = Student.objects.create(code="QRS78", group=StudyGroup.PILOT)
        complete_instrument(self.pilot, StudyPhase.PRE, correct=3)
        complete_instrument(self.pilot, StudyPhase.POST, correct=8)
        complete_instrument(self.control, StudyPhase.PRE, correct=4)
        abandoned = start_instrument(self.control, StudyPhase.POST)
        for _ in range(2):
            question = next_instrument_question(abandoned)
            record_instrument_response(abandoned, question, question.correct_index)

        summary = {row["codigo"]: row for row in self.export()}
        out = StringIO()
        call_command("export_responses", stdout=out)
        detail = read_csv(out.getvalue())

        # Guarda contra aprovacao vazia: se tudo saisse em branco, a igualdade
        # abaixo passaria sem provar nada.
        self.assertEqual(summary["ABC23"]["pre_acertos"], "3")
        self.assertEqual(summary["ABC23"]["pos_acertos"], "8")
        self.assertEqual(summary["XYZ45"]["pre_acertos"], "4")
        self.assertEqual(summary["XYZ45"]["pos_acertos"], "")

        total = len(instrument_questions())
        for student in (self.pilot, self.control, nothing_done):
            for phase, column in (("pre", "pre_acertos"), ("post", "pos_acertos")):
                concluded = [
                    row
                    for row in detail
                    if row["codigo"] == student.code
                    and row["fase"] == phase
                    and row["aplicacao_concluida"] == "sim"
                ]
                rebuilt = sum(1 for row in concluded if row["acertou"] == "sim")
                cell = summary[student.code][column]
                with self.subTest(aluno=student.code, fase=phase):
                    if cell == "":
                        self.assertEqual(concluded, [])
                    else:
                        self.assertEqual(str(rebuilt), cell)
                        self.assertEqual(len(concluded), total)

        # O abandono continua visivel no CSV de respostas, marcado como tal.
        abandoned_rows = [
            row
            for row in detail
            if row["codigo"] == self.control.code and row["fase"] == "post"
        ]
        self.assertEqual(len(abandoned_rows), 2)
        self.assertTrue(
            all(row["aplicacao_concluida"] == "nao" for row in abandoned_rows)
        )

    def test_response_export_has_one_row_per_answer(self):
        complete_instrument(self.pilot, StudyPhase.PRE, correct=2)

        out = StringIO()
        call_command("export_responses", stdout=out)

        self.assertEqual(len(read_csv(out.getvalue())), InstrumentResponse.objects.count())


class PerGroupStageTests(InstrumentTestCase):
    """
    Cada turma segue a propria etapa (CLAUDE.md secao 11).

    O risco da reestruturacao e o fluxo ler a etapa da turma errada. Por isso
    cada teste coloca as duas turmas em etapas **diferentes** e confere que cada
    aluno obedece a da propria turma — com etapas iguais, um porteiro que lesse
    a turma errada passaria despercebido.
    """

    def finish_pre(self, *students):
        for student in students:
            complete_instrument(student, StudyPhase.PRE)

    def landing_for(self, student):
        self.client.post(reverse("assessment:leave"))
        self.enter_as(student)
        return self.client.get(reverse("assessment:next_step"))

    def test_there_is_exactly_one_row_per_group(self):
        self.assertEqual(
            sorted(StudySettings.objects.values_list("group", flat=True)),
            sorted(choice.value for choice in StudyGroup),
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudySettings.objects.create(group=StudyGroup.PILOT)

    def test_pilot_in_activity_while_control_is_still_in_pre_test(self):
        self.set_stage(StudyStage.ACTIVITY, group=StudyGroup.PILOT)
        self.set_stage(StudyStage.PRE_TEST, group=StudyGroup.CONTROL)
        self.finish_pre(self.pilot, self.control)

        self.assertRedirects(
            self.landing_for(self.pilot), reverse("assessment:choose_goal")
        )
        # Controle com pre-teste feito, mas a turma dele ainda esta no
        # pre-teste: espera, e nao a tela da atividade.
        control = self.landing_for(self.control)
        self.assertContains(control, "Tudo certo por enquanto")
        self.assertNotContains(control, "Sua turma é a de comparação")

    def test_pilot_post_test_does_not_open_the_post_test_for_control(self):
        self.set_stage(StudyStage.POST_TEST, group=StudyGroup.PILOT)
        self.set_stage(StudyStage.ACTIVITY, group=StudyGroup.CONTROL)
        self.finish_pre(self.pilot, self.control)

        self.assertRedirects(
            self.landing_for(self.pilot), reverse("assessment:instrument")
        )
        control = self.landing_for(self.control)
        self.assertContains(control, "Sua turma é a de comparação")
        self.assertRedirects(
            self.client.get(reverse("assessment:instrument")),
            reverse("assessment:next_step"),
            fetch_redirect_response=False,
        )
        self.assertFalse(
            InstrumentSession.objects.filter(
                student=self.control, phase=StudyPhase.POST
            ).exists()
        )

    def test_the_app_gate_reads_the_students_own_group(self):
        """
        Turma controle em atividade nao abre o app para o piloto cuja turma
        ainda esta no pre-teste. E o erro mais provavel da reestruturacao: ler a
        etapa de qualquer turma em vez da turma do aluno.
        """
        self.set_stage(StudyStage.PRE_TEST, group=StudyGroup.PILOT)
        self.set_stage(StudyStage.ACTIVITY, group=StudyGroup.CONTROL)
        self.finish_pre(self.pilot)
        self.enter_as(self.pilot)

        for name in ("choose_goal", "take_test", "recommendation"):
            with self.subTest(tela=name):
                self.assertRedirects(
                    self.client.get(reverse(f"assessment:{name}")),
                    reverse("assessment:next_step"),
                    fetch_redirect_response=False,
                )
        self.assertContains(
            self.client.get(reverse("assessment:next_step")),
            "Tudo certo por enquanto",
        )
        self.assertFalse(AssessmentSession.objects.filter(student=self.pilot).exists())


class StudySettingsAdminTests(InstrumentTestCase):
    """
    O professor opera as duas etapas numa tela so. O que importa e o que ele ve
    e o que acontece quando salva — nao so que a pagina abriu.
    """

    def setUp(self):
        super().setUp()
        teacher = get_user_model().objects.create_superuser(
            "professor", "professor@example.invalid", "senha-so-de-teste"
        )
        self.client.force_login(teacher)
        self.url = reverse("admin:assessment_studysettings_changelist")

    def test_both_groups_are_listed_side_by_side_with_editable_stage(self):
        response = self.client.get(self.url)

        self.assertContains(response, "Piloto (usa o aplicativo)")
        self.assertContains(response, "Controle (nao usa o aplicativo)")
        self.assertContains(response, 'name="form-0-stage"')
        self.assertContains(response, 'name="form-1-stage"')

    def test_no_row_can_be_added_or_deleted(self):
        response = self.client.get(self.url)

        self.assertNotContains(
            response, reverse("admin:assessment_studysettings_add")
        )
        self.assertEqual(
            self.client.get(reverse("admin:assessment_studysettings_add")).status_code,
            403,
        )

    def test_warns_when_the_groups_are_in_different_stages(self):
        self.set_stage(StudyStage.ACTIVITY, group=StudyGroup.PILOT)

        self.assertContains(self.client.get(self.url), "etapas diferentes")

    def test_no_warning_when_both_groups_share_the_stage(self):
        self.set_stage(StudyStage.ACTIVITY)

        self.assertNotContains(self.client.get(self.url), "etapas diferentes")

    def test_shows_how_many_students_finished_each_test(self):
        complete_instrument(self.pilot, StudyPhase.PRE)

        html = self.client.get(self.url).content.decode()

        # Uma turma por linha, um aluno em cada: so o pre-teste do piloto esta
        # concluido; as outras tres celulas mostram zero.
        self.assertEqual(html.count("1 de 1 alunos"), 1)
        self.assertEqual(html.count("0 de 1 alunos"), 3)

    def test_saving_the_list_changes_only_the_edited_group(self):
        rows = list(StudySettings.objects.order_by("group", "-pk"))
        data = {
            "form-TOTAL_FORMS": str(len(rows)),
            "form-INITIAL_FORMS": str(len(rows)),
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
            "_save": "Salvar",
        }
        for index, row in enumerate(rows):
            data[f"form-{index}-id"] = str(row.pk)
            data[f"form-{index}-stage"] = (
                StudyStage.ACTIVITY if row.group == StudyGroup.PILOT else row.stage
            )

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            StudySettings.for_group(StudyGroup.PILOT).stage, StudyStage.ACTIVITY
        )
        self.assertEqual(
            StudySettings.for_group(StudyGroup.CONTROL).stage, StudyStage.PRE_TEST
        )
