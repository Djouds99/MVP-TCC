"""
Testes da ponte entre o motor e o banco.

Verificam o percurso completo de uma sessao: iniciar, responder questoes reais
gravando cada resposta, encerrar produzindo um estado de conhecimento e
alimentar com ele a recomendacao da Parte 2 — sem conversao manual no meio.
"""

from io import StringIO

from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase

from assessment.models import AssessmentSession, QuestionResponse
from assessment.services import (
    build_assessment,
    closure_from_database,
    finalize,
    next_question,
    recommendation_for,
    record_response,
    sample_question_for,
    start_session,
)
from domain.curriculum import load_curriculum
from domain.models import KnowledgeItem, KnowledgeState, Question, QuestionPurpose
from domain.recommendation import RecommendationReason
from students.models import Student, StudyGroup


def answer_as(student_knows, question) -> int:
    """Indice da alternativa que um aluno com esse conhecimento escolheria."""
    if question.item.code in student_knows:
        return question.correct_index
    # Uma alternativa errada qualquer, deterministica.
    return (question.correct_index + 1) % len(question.alternatives)


def run_session(session, student_knows) -> AssessmentSession:
    while (question := next_question(session)) is not None:
        record_response(session, question, answer_as(student_knows, question))
    finalize(session)
    session.refresh_from_db()
    return session


class ServiceLayerTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_curriculum", verbosity=0, stdout=StringIO())
        cls.student = Student.objects.create(code="ABC23", group=StudyGroup.PILOT)
        cls.goal = KnowledgeItem.objects.get(code="lg-equacao-exponencial")


class DatabaseClosureTests(ServiceLayerTestCase):
    def test_matches_the_closure_computed_from_the_file(self):
        self.assertEqual(
            closure_from_database(),
            dict(load_curriculum().item_prerequisite_closure()),
        )

    def test_every_item_has_at_least_one_adaptive_question(self):
        """
        O motor so pode sondar itens que a tela consegue perguntar. Um item sem
        questao adaptativa viraria uma pergunta impossivel no meio do teste — e
        uma questao do instrumento nao conta, porque o teste adaptativo nunca a
        serve. Antes da Parte 5 bastava "alguma questao"; depois dela, um item
        so com questao de instrumento passaria na checagem antiga e travaria o
        teste em sala.
        """
        without_adaptive = KnowledgeItem.objects.exclude(
            questions__purpose=QuestionPurpose.ADAPTIVE
        )
        self.assertFalse(
            list(without_adaptive.values_list("code", flat=True)),
            "ha item de conhecimento sem nenhuma questao adaptativa no banco",
        )


class SessionFlowTests(ServiceLayerTestCase):
    def test_a_student_who_knows_nothing_ends_at_the_empty_state(self):
        session = run_session(start_session(self.student, self.goal), set())

        self.assertTrue(session.is_finished)
        self.assertEqual(session.resulting_state.signature, "")
        self.assertEqual(session.resulting_state.size, 0)

    def test_a_student_who_knows_everything_ends_at_the_full_domain(self):
        everything = set(closure_from_database())

        session = run_session(start_session(self.student, self.goal), everything)

        self.assertEqual(session.resulting_state.size, len(everything))

    def test_a_mixed_pattern_recovers_the_branch_actually_mastered(self):
        knows = {
            "pc-par-ordenado",
            "pc-localizar-ponto",
            "pc-ler-grafico",
            "fa-lei-formacao",
            "fa-coeficientes",
            "fa-grafico-raiz",
            "pr-reconhecer-sequencia",
        }

        session = run_session(start_session(self.student, self.goal), knows)

        self.assertEqual(session.resulting_state.item_codes, knows)

    def test_responses_are_recorded_in_order_and_never_repeat(self):
        session = run_session(
            start_session(self.student, self.goal), {"pc-par-ordenado"}
        )
        responses = list(session.responses.order_by("position"))

        self.assertEqual(
            [response.position for response in responses],
            list(range(1, len(responses) + 1)),
        )
        question_ids = [response.question_id for response in responses]
        self.assertEqual(len(question_ids), len(set(question_ids)))

    def test_asks_fewer_questions_than_the_number_of_items(self):
        session = run_session(
            start_session(self.student, self.goal), {"pc-par-ordenado"}
        )

        self.assertLess(session.question_count, KnowledgeItem.objects.count())

    def test_the_session_records_which_content_version_it_ran_on(self):
        session = start_session(self.student, self.goal)
        self.assertIsNotNone(session.curriculum_release)
        self.assertEqual(session.curriculum_release.item_count, 15)
        # 15 do banco adaptativo mais 10 do instrumento de pesquisa.
        self.assertEqual(session.curriculum_release.question_count, 25)

    def test_wrong_choice_is_recorded_as_incorrect_with_the_chosen_index(self):
        session = start_session(self.student, self.goal)
        question = next_question(session)
        wrong_index = (question.correct_index + 1) % len(question.alternatives)

        response = record_response(session, question, wrong_index)

        self.assertFalse(response.is_correct)
        self.assertEqual(response.chosen_index, wrong_index)

    def test_no_answer_counts_as_incorrect(self):
        session = start_session(self.student, self.goal)
        question = next_question(session)

        response = record_response(session, question, None)

        self.assertFalse(response.is_correct)
        self.assertIsNone(response.chosen_index)


class SessionGuardTests(ServiceLayerTestCase):
    def test_cannot_finalize_before_the_test_converges(self):
        session = start_session(self.student, self.goal)
        question = next_question(session)
        record_response(session, question, question.correct_index)

        if not build_assessment(session).is_complete:
            with self.assertRaisesMessage(ValueError, "ainda nao convergiu"):
                finalize(session)

    def test_a_finished_session_refuses_new_answers(self):
        session = run_session(start_session(self.student, self.goal), set())
        leftover = Question.objects.exclude(
            id__in=session.responses.values_list("question_id", flat=True)
        ).first()

        with self.assertRaisesMessage(ValueError, "ja foi encerrada"):
            record_response(session, leftover, 0)

    def test_next_question_returns_none_once_it_converges(self):
        session = start_session(self.student, self.goal)
        while (question := next_question(session)) is not None:
            record_response(session, question, question.correct_index)

        self.assertIsNone(next_question(session))

    def test_the_same_question_cannot_be_answered_twice(self):
        session = start_session(self.student, self.goal)
        question = next_question(session)
        record_response(session, question, question.correct_index)

        with self.assertRaises(IntegrityError):
            QuestionResponse.objects.create(
                session=session, question=question, is_correct=True, position=99
            )

    def test_recommendation_requires_a_finished_session(self):
        session = start_session(self.student, self.goal)
        with self.assertRaisesMessage(ValueError, "chame `finalize`"):
            recommendation_for(session)


class FeedsPartTwoTests(ServiceLayerTestCase):
    """O encontro dos dois motores, passando pelo banco."""

    def test_the_estimated_state_produces_a_goal_directed_recommendation(self):
        session = run_session(
            start_session(self.student, self.goal),
            {"pc-par-ordenado", "pc-localizar-ponto"},
        )

        recommendation = recommendation_for(session)

        self.assertEqual(recommendation.reason, RecommendationReason.GOAL_DIRECTED)
        self.assertEqual(recommendation.item, "pc-ler-grafico")

    def test_the_goal_changes_the_recommendation_for_the_same_measured_state(self):
        knows = {
            "pc-par-ordenado",
            "pc-localizar-ponto",
            "pc-ler-grafico",
            "fa-lei-formacao",
            "fa-coeficientes",
            "fa-grafico-raiz",
        }
        towards_log = run_session(start_session(self.student, self.goal), knows)

        other_student = Student.objects.create(code="XYZ45", group=StudyGroup.PILOT)
        towards_pr = run_session(
            start_session(
                other_student, KnowledgeItem.objects.get(code="pr-termo-geral-pg")
            ),
            knows,
        )

        self.assertEqual(
            towards_log.resulting_state_id, towards_pr.resulting_state_id
        )
        self.assertEqual(recommendation_for(towards_log).item, "fe-potencias")
        self.assertEqual(
            recommendation_for(towards_pr).item, "pr-reconhecer-sequencia"
        )

    def test_a_student_who_knows_everything_gets_no_recommendation(self):
        session = run_session(
            start_session(self.student, self.goal), set(closure_from_database())
        )

        recommendation = recommendation_for(session)

        self.assertIsNone(recommendation.item)
        self.assertEqual(recommendation.reason, RecommendationReason.DOMAIN_COMPLETE)

    def test_the_resulting_state_is_an_existing_knowledge_state_row(self):
        session = run_session(
            start_session(self.student, self.goal), {"pc-par-ordenado"}
        )

        self.assertIn(
            session.resulting_state,
            KnowledgeState.objects.all(),
        )


class SampleQuestionTests(ServiceLayerTestCase):
    """
    A questao de amostra da tela de recomendacao nunca sai do instrumento — o
    teste de tela cobre `pc-par-ordenado`; este cobre todo item.
    """

    def test_the_sample_is_always_adaptive_for_every_item(self):
        # Empate forcado a favor do instrumento em todos os itens de uma vez:
        # se a protecao dependesse da ordenacao, alguma amostra sairia errada.
        Question.objects.filter(purpose=QuestionPurpose.INSTRUMENT).update(position=0)

        for item in KnowledgeItem.objects.all():
            sample = sample_question_for(item)
            with self.subTest(item=item.code):
                self.assertIsNotNone(sample)
                self.assertEqual(sample.purpose, QuestionPurpose.ADAPTIVE)
                self.assertEqual(sample.item_id, item.pk)

    def test_the_adaptive_recorder_refuses_an_instrument_question(self):
        session = start_session(self.student, self.goal)
        instrument = Question.objects.filter(
            purpose=QuestionPurpose.INSTRUMENT
        ).first()

        with self.assertRaisesMessage(ValueError, "nao pertence ao banco adaptativo"):
            record_response(session, instrument, instrument.correct_index)
        self.assertFalse(session.responses.exists())
