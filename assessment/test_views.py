"""
Testes do fluxo do aluno pelo HTTP.

O teste que importa aqui e `CriticalPathTests`: percorre identificacao ->
objetivo -> teste adaptativo -> recomendacao usando so o cliente HTTP, sem tocar
o banco no meio do caminho. E o criterio de conclusao da Parte 4, e e tambem o
fluxo que roda em sala sem segunda chance (CLAUDE.md secao 8).
"""

import re
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from assessment.models import AssessmentSession
from assessment.services import closure_from_database
from domain.models import KnowledgeItem, Question, Topic
from domain.recommendation import RecommendationReason, recommend_next_item
from students.models import Student, StudyGroup


class FlowTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_curriculum", verbosity=0, stdout=StringIO())
        cls.pilot = Student.objects.create(code="ABC23", group=StudyGroup.PILOT)
        cls.control = Student.objects.create(code="XYZ45", group=StudyGroup.CONTROL)
        cls.goal_topic = Topic.objects.get(code="logaritmo")

    def enter_as(self, student: Student):
        return self.client.post(reverse("assessment:identify"), {"code": student.code})

    def declare_goal(self, topic: Topic | None = None):
        return self.client.post(
            reverse("assessment:choose_goal"),
            {"topic": (topic or self.goal_topic).pk},
        )

    def answer_current_question(self, knows: set[str]):
        """
        Responde a questao que esta na tela como faria um aluno que domina
        exatamente `knows`. Devolve False quando nao ha mais pergunta.
        """
        response = self.client.get(reverse("assessment:take_test"))
        if response.status_code == 302:
            return False

        question = response.context["question"]
        correct = question.item.code in knows
        chosen = (
            question.correct_index
            if correct
            else (question.correct_index + 1) % len(question.alternatives)
        )
        self.client.post(
            reverse("assessment:take_test"),
            {"question": question.pk, "alternative": chosen},
        )
        return True

    def walk_through(self, knows: set[str], topic: Topic | None = None):
        self.enter_as(self.pilot)
        self.declare_goal(topic)
        while self.answer_current_question(knows):
            pass
        return self.client.get(reverse("assessment:recommendation"))


class IdentifyTests(FlowTestCase):
    def test_entry_screen_loads(self):
        response = self.client.get(reverse("assessment:identify"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vamos começar")

    def test_valid_code_goes_to_the_goal_screen(self):
        response = self.enter_as(self.pilot)
        self.assertRedirects(response, reverse("assessment:choose_goal"))

    def test_code_is_accepted_in_lowercase_and_with_spaces(self):
        response = self.client.post(
            reverse("assessment:identify"), {"code": " abc 23 "}
        )
        self.assertRedirects(response, reverse("assessment:choose_goal"))

    def test_unknown_code_shows_an_explanation(self):
        response = self.client.post(reverse("assessment:identify"), {"code": "ZZZZZ"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Não encontramos esse código")

    def test_empty_code_keeps_the_student_on_the_entry_screen(self):
        response = self.client.post(reverse("assessment:identify"), {"code": "   "})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vamos começar")
        self.assertIn("code", response.context["form"].errors)
        self.assertFalse(AssessmentSession.objects.exists())

    def test_control_group_is_not_let_into_the_app(self):
        """
        O grupo controle nao usa o aplicativo — e essa a definicao do desenho
        comparativo. Deixar entrar contaminaria a comparacao de ganho.
        """
        response = self.enter_as(self.control)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "turma de comparação")
        self.assertNotIn("student_id", self.client.session)

        # E nao da para pular a identificacao indo direto na proxima tela.
        self.assertRedirects(
            self.client.get(reverse("assessment:choose_goal")),
            reverse("assessment:identify"),
        )


class GoalTests(FlowTestCase):
    def test_requires_identification_first(self):
        self.assertRedirects(
            self.client.get(reverse("assessment:choose_goal")),
            reverse("assessment:identify"),
        )

    def test_lists_every_topic_of_the_chain(self):
        self.enter_as(self.pilot)
        response = self.client.get(reverse("assessment:choose_goal"))

        for topic in Topic.objects.all():
            self.assertContains(response, topic.name)

    def test_choosing_a_topic_starts_a_session_aimed_at_its_last_item(self):
        self.enter_as(self.pilot)

        response = self.declare_goal()

        self.assertRedirects(response, reverse("assessment:take_test"))
        session = AssessmentSession.objects.get()
        self.assertEqual(session.student, self.pilot)
        # "Dominar logaritmo" vira o ultimo item do topico, cujo caminho de
        # pre-requisitos contem os demais itens de logaritmo.
        self.assertEqual(session.goal_item.code, "lg-equacao-exponencial")

    def test_goal_item_covers_its_whole_topic(self):
        """
        Tripwire da traducao topico -> item. Vale enquanto os itens de um topico
        formarem uma cadeia; se um topico ganhar dois itens finais
        independentes, o objetivo deixa de significar "topico inteiro" e este
        teste falha em vez de escolher um deles em silencio.
        """
        closure = closure_from_database()
        for topic in Topic.objects.prefetch_related("items"):
            goal = topic.items.order_by("-position", "-code").first()
            reachable = set(closure[goal.code]) | {goal.code}
            with self.subTest(topico=topic.code):
                self.assertTrue(
                    set(topic.items.values_list("code", flat=True)) <= reachable,
                    f"o objetivo `{goal.code}` nao cobre o topico inteiro",
                )


class TakeTestTests(FlowTestCase):
    def test_requires_a_session(self):
        self.assertRedirects(
            self.client.get(reverse("assessment:take_test")),
            reverse("assessment:identify"),
        )

    def test_shows_a_question_with_its_alternatives(self):
        self.enter_as(self.pilot)
        self.declare_goal()

        response = self.client.get(reverse("assessment:take_test"))

        self.assertEqual(response.status_code, 200)
        question = response.context["question"]
        self.assertContains(response, question.statement)
        for alternative in question.alternatives:
            self.assertContains(response, alternative)

    def test_no_markup_distinguishes_the_correct_alternative(self):
        """
        As alternativas tem que sair indistinguiveis entre si no HTML — nada de
        atributo, ordem marcada ou opcao ja selecionada entregando a resposta.
        """
        self.enter_as(self.pilot)
        self.declare_goal()

        response = self.client.get(reverse("assessment:take_test"))
        html = response.content.decode()
        question = response.context["question"]

        inputs = re.findall(r'<input type="radio" name="alternative"[^>]*>', html)
        self.assertEqual(len(inputs), len(question.alternatives))
        for tag in inputs:
            self.assertNotIn("checked", tag)
            self.assertNotIn("data-", tag)
        self.assertNotIn("correct", html)

    def test_answering_records_the_response_and_redirects(self):
        self.enter_as(self.pilot)
        self.declare_goal()
        question = self.client.get(reverse("assessment:take_test")).context["question"]

        response = self.client.post(
            reverse("assessment:take_test"),
            {"question": question.pk, "alternative": question.correct_index},
        )

        self.assertRedirects(response, reverse("assessment:take_test"))
        recorded = AssessmentSession.objects.get().responses.get()
        self.assertEqual(recorded.question, question)
        self.assertTrue(recorded.is_correct)

    def test_submitting_without_choosing_does_not_record_anything(self):
        self.enter_as(self.pilot)
        self.declare_goal()
        question = self.client.get(reverse("assessment:take_test")).context["question"]

        self.client.post(reverse("assessment:take_test"), {"question": question.pk})

        self.assertEqual(AssessmentSession.objects.get().responses.count(), 0)

    def test_a_stale_submission_is_ignored(self):
        """
        Aluno volta pelo botao do navegador e responde de novo uma questao ja
        respondida. Sem essa guarda, a gravacao estouraria na restricao de
        unicidade e derrubaria a tela no meio da aula.
        """
        self.enter_as(self.pilot)
        self.declare_goal()
        first = self.client.get(reverse("assessment:take_test")).context["question"]
        self.client.post(
            reverse("assessment:take_test"),
            {"question": first.pk, "alternative": first.correct_index},
        )

        response = self.client.post(
            reverse("assessment:take_test"),
            {"question": first.pk, "alternative": first.correct_index},
        )

        self.assertRedirects(response, reverse("assessment:take_test"))
        self.assertEqual(AssessmentSession.objects.get().responses.count(), 1)

    def test_progress_advances_with_each_answer(self):
        self.enter_as(self.pilot)
        self.declare_goal()

        seen = []
        while True:
            response = self.client.get(reverse("assessment:take_test"))
            if response.status_code == 302:
                break
            seen.append(response.context["progress"])
            question = response.context["question"]
            self.client.post(
                reverse("assessment:take_test"),
                {"question": question.pk, "alternative": question.correct_index},
            )

        self.assertEqual(seen, sorted(seen))
        self.assertEqual(seen[0], 0)

    def test_a_finished_session_goes_to_the_recommendation(self):
        self.walk_through(set())

        self.assertRedirects(
            self.client.get(reverse("assessment:take_test")),
            reverse("assessment:recommendation"),
        )


class RecommendationTests(FlowTestCase):
    def test_requires_a_finished_session(self):
        self.enter_as(self.pilot)
        self.declare_goal()

        self.assertRedirects(
            self.client.get(reverse("assessment:recommendation")),
            reverse("assessment:take_test"),
        )

    def test_shows_the_recommended_item_and_its_topic(self):
        response = self.walk_through(set())

        self.assertEqual(response.status_code, 200)
        item = response.context["item"]
        self.assertIsNotNone(item)
        self.assertContains(response, item.name)
        self.assertContains(response, item.topic.name)

    def test_explains_the_choice_in_terms_of_the_declared_goal(self):
        response = self.walk_through(set())

        self.assertEqual(
            response.context["result"].reason, RecommendationReason.GOAL_DIRECTED
        )
        self.assertContains(response, "objetivo que você escolheu")

    def test_lists_what_the_test_confirmed(self):
        knows = {"pc-par-ordenado", "pc-localizar-ponto"}

        response = self.walk_through(knows)

        self.assertEqual(response.context["mastered_count"], len(knows))
        for code in knows:
            self.assertContains(response, KnowledgeItem.objects.get(code=code).name)

    def test_a_student_who_knows_everything_sees_the_completed_message(self):
        response = self.walk_through(set(closure_from_database()))

        self.assertIsNone(response.context["item"])
        self.assertEqual(
            response.context["result"].reason, RecommendationReason.DOMAIN_COMPLETE
        )
        self.assertContains(response, "toda a trilha")

    def test_goal_already_reached_asks_for_a_new_goal(self):
        plane = Topic.objects.get(code="plano-cartesiano")
        knows = set(plane.items.values_list("code", flat=True))

        response = self.walk_through(knows, topic=plane)

        self.assertEqual(
            response.context["result"].reason,
            RecommendationReason.GOAL_ALREADY_REACHED,
        )
        self.assertContains(response, "Escolher outro objetivo")

    def test_the_sample_question_shows_only_its_statement(self):
        """
        A amostra na tela de recomendacao existe para dar contexto, nao para
        entregar exercicio resolvido: nenhuma alternativa vai junto.
        """
        response = self.walk_through(set())

        sample = re.search(
            r'<div class="sample">(.*?)</div>', response.content.decode(), re.S
        )
        self.assertIsNotNone(sample)
        self.assertEqual(
            sample.group(1).strip(), response.context["sample_question"].statement
        )


class CriticalPathTests(FlowTestCase):
    """
    O criterio de conclusao da Parte 4: o percurso inteiro pelo navegador, sem
    nenhuma intervencao manual no banco.
    """

    def test_a_student_goes_from_code_to_recommendation(self):
        knows = {
            "pc-par-ordenado",
            "pc-localizar-ponto",
            "pc-ler-grafico",
            "fa-lei-formacao",
        }

        entry = self.enter_as(self.pilot)
        self.assertRedirects(entry, reverse("assessment:choose_goal"))

        goal = self.declare_goal()
        self.assertRedirects(goal, reverse("assessment:take_test"))

        answered = 0
        while self.answer_current_question(knows):
            answered += 1

        response = self.client.get(reverse("assessment:recommendation"))
        self.assertEqual(response.status_code, 200)

        # O que o aluno ve, e nao so o que o banco guardou: status 200 provaria
        # apenas que o servidor respondeu (CLAUDE.md secao 8).
        recommended = response.context["item"]
        self.assertIsNotNone(recommended)
        self.assertContains(response, recommended.name)
        self.assertContains(response, "objetivo que você escolheu")
        self.assertContains(response, "Seu próximo passo")

        session = AssessmentSession.objects.get()
        self.assertTrue(session.is_finished)
        self.assertEqual(session.resulting_state.item_codes, knows)
        self.assertEqual(session.responses.count(), answered)
        self.assertLess(answered, KnowledgeItem.objects.count())

    def test_the_screen_agrees_with_the_part_two_engine(self):
        """
        A tela nao pode recomendar uma coisa e o motor outra. Confere a
        recomendacao exibida contra `recommend_next_item` chamado diretamente
        com o mesmo estado e o mesmo objetivo.
        """
        knows = {"pc-par-ordenado", "pc-localizar-ponto"}

        response = self.walk_through(knows)

        session = AssessmentSession.objects.get()
        expected = recommend_next_item(
            session.resulting_state.item_codes,
            closure_from_database(),
            goal=session.goal_item.code,
        )
        self.assertEqual(response.context["item"].code, expected.item)
        self.assertContains(response, expected.item and KnowledgeItem.objects.get(
            code=expected.item
        ).name)

    def test_the_goal_changes_what_the_screen_recommends(self):
        knows = {
            "pc-par-ordenado",
            "pc-localizar-ponto",
            "pc-ler-grafico",
            "fa-lei-formacao",
        }

        towards_log = self.walk_through(knows, Topic.objects.get(code="logaritmo"))
        item_for_log = towards_log.context["item"].code

        self.client.post(reverse("assessment:leave"))
        towards_pr = self.walk_through(knows, Topic.objects.get(code="progressoes"))
        item_for_pr = towards_pr.context["item"].code

        # Mesmo estado medido, objetivos diferentes, proximos passos diferentes.
        self.assertNotEqual(item_for_log, item_for_pr)
        self.assertEqual(item_for_log, "fe-potencias")
        self.assertEqual(item_for_pr, "fa-coeficientes")

    def test_leaving_clears_the_session(self):
        self.enter_as(self.pilot)
        self.declare_goal()

        self.client.post(reverse("assessment:leave"))

        self.assertNotIn("student_id", self.client.session)
        self.assertRedirects(
            self.client.get(reverse("assessment:take_test")),
            reverse("assessment:identify"),
        )

    def test_two_students_on_the_same_browser_do_not_mix(self):
        """
        Na sala o aparelho pode ser passado de mao em mao. Entrar com outro
        codigo tem que comecar do zero, nao continuar a sessao anterior.
        """
        other = Student.objects.create(code="QRS78", group=StudyGroup.PILOT)
        self.enter_as(self.pilot)
        self.declare_goal()
        first_session = AssessmentSession.objects.get()

        self.enter_as(other)
        self.declare_goal()

        sessions = AssessmentSession.objects.order_by("pk")
        self.assertEqual(sessions.count(), 2)
        self.assertEqual(sessions.last().student, other)
        self.assertNotEqual(
            self.client.session["assessment_session_id"], first_session.pk
        )
