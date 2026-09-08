"""
Testes do motor de teste adaptativo, isolados de interface e de banco.

Cobrem as tres simulacoes pedidas pelo roadmap — todas certas, todas erradas e
padroes mistos — mais as propriedades que justificam chamar o procedimento de
adaptativo.
"""

from statistics import mean

from django.test import SimpleTestCase

from assessment.engine import (
    AdaptiveAssessment,
    Answer,
    InconsistentAnswerError,
    simulate,
)
from domain.curriculum import load_curriculum
from domain.knowledge_space import generate_knowledge_states, transitive_closure
from domain.recommendation import recommend_next_item

# Cadeia estritamente linear, para conferir que o procedimento coincide com uma
# busca binaria quando o dominio de fato e uma fila.
LINEAR_CLOSURE = transitive_closure(
    {
        "a": [],
        "b": ["a"],
        "c": ["a", "b"],
        "d": ["a", "b", "c"],
        "e": ["a", "b", "c", "d"],
        "f": ["a", "b", "c", "d", "e"],
        "g": ["a", "b", "c", "d", "e", "f"],
    }
)

# Cadeia ramificada do roadmap, onde a busca binaria linear falharia.
BRANCHED_CLOSURE = transitive_closure(
    {"PC": [], "FA": ["PC"], "FE": ["FA"], "PR": ["FA"], "LOG": ["FE"]}
)


class SimulatedAnswerScriptTests(SimpleTestCase):
    """As tres simulacoes pedidas no roadmap."""

    def test_all_correct_yields_the_whole_domain(self):
        assessment = AdaptiveAssessment(BRANCHED_CLOSURE)
        while not assessment.is_complete:
            assessment.record(assessment.next_item, correct=True)

        self.assertEqual(assessment.knowledge_state, set(BRANCHED_CLOSURE))

    def test_all_wrong_yields_the_empty_state(self):
        assessment = AdaptiveAssessment(BRANCHED_CLOSURE)
        while not assessment.is_complete:
            assessment.record(assessment.next_item, correct=False)

        self.assertEqual(assessment.knowledge_state, frozenset())

    def test_mixed_pattern_recovers_the_branch_actually_mastered(self):
        """
        O aluno domina progressoes e nao domina exponencial.

        E o padrao que uma busca binaria ao longo de uma ordem linear erraria:
        esse estado nao e prefixo de ordem nenhuma.
        """
        true_state = {"PC", "FA", "PR"}

        assessment = simulate(BRANCHED_CLOSURE, true_state)

        self.assertEqual(assessment.knowledge_state, true_state)
        self.assertIn("PR", assessment.knowledge_state)
        self.assertNotIn("FE", assessment.knowledge_state)

    def test_every_state_of_the_example_domain_is_recovered(self):
        for true_state in generate_knowledge_states(BRANCHED_CLOSURE):
            with self.subTest(estado=sorted(true_state)):
                self.assertEqual(
                    simulate(BRANCHED_CLOSURE, true_state).knowledge_state, true_state
                )


class LinearChainTests(SimpleTestCase):
    def test_on_a_pure_chain_it_behaves_like_a_binary_search(self):
        """
        Numa cadeia linear de 7 itens, uma busca binaria gasta 3 perguntas
        (2**3 = 8 fronteiras possiveis). O procedimento aqui gasta o mesmo.
        """
        for true_state in generate_knowledge_states(LINEAR_CLOSURE):
            assessment = simulate(LINEAR_CLOSURE, true_state)
            with self.subTest(estado=sorted(true_state)):
                self.assertEqual(assessment.knowledge_state, true_state)
                self.assertEqual(len(assessment.asked_items), 3)

    def test_first_question_on_a_chain_is_the_middle_item(self):
        assessment = AdaptiveAssessment(LINEAR_CLOSURE)
        # Sete itens, oito estados: o item que divide ao meio e o quarto.
        self.assertEqual(assessment.next_item, "d")


class AdaptivenessTests(SimpleTestCase):
    """
    O que justifica chamar o teste de adaptativo: sondar bem menos itens do que
    o dominio tem.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        curriculum = load_curriculum()
        cls.closure = curriculum.item_prerequisite_closure()
        cls.order = curriculum.canonical_item_order
        cls.states = generate_knowledge_states(cls.closure)
        cls.runs = [
            simulate(cls.closure, state, item_order=cls.order) for state in cls.states
        ]

    def test_asks_far_fewer_questions_than_the_whole_domain(self):
        counts = [len(run.asked_items) for run in self.runs]
        domain_size = len(self.closure)

        self.assertLessEqual(max(counts), domain_size // 2)
        self.assertLess(mean(counts), domain_size / 2)

    def test_never_repeats_an_item(self):
        for run in self.runs:
            with self.subTest(perguntas=len(run.asked_items)):
                self.assertEqual(len(run.asked_items), len(set(run.asked_items)))

    def test_recovers_every_state_of_the_real_curriculum(self):
        for state, run in zip(self.states, self.runs):
            with self.subTest(estado=len(state)):
                self.assertEqual(run.knowledge_state, state)

    def test_only_asks_about_items_that_are_still_open(self):
        """
        Uma pergunta cuja resposta ja esta determinada pelas anteriores seria
        pergunta desperdicada — e e o que separa este procedimento de uma
        varredura.
        """
        for true_state in self.states:
            truth = set(true_state)
            assessment = AdaptiveAssessment(self.closure, item_order=self.order)
            while not assessment.is_complete:
                item = assessment.next_item
                with self.subTest(estado=len(true_state), item=item):
                    self.assertIn(item, assessment.open_items)
                assessment.record(item, correct=item in truth)


class EngineContractTests(SimpleTestCase):
    def test_state_is_unavailable_until_it_converges(self):
        assessment = AdaptiveAssessment(BRANCHED_CLOSURE)

        self.assertFalse(assessment.is_complete)
        with self.assertRaisesMessage(ValueError, "ainda nao convergiu"):
            _ = assessment.knowledge_state

    def test_confirmed_mastered_grows_as_answers_arrive(self):
        assessment = AdaptiveAssessment(BRANCHED_CLOSURE)
        self.assertEqual(assessment.confirmed_mastered, frozenset())

        assessment.record("FE", correct=True)

        # Acertar FE implica dominio de tudo que FE exige, sem ter perguntado.
        self.assertTrue({"PC", "FA", "FE"} <= assessment.confirmed_mastered)

    def test_a_correct_answer_carries_the_prerequisites_with_it(self):
        assessment = AdaptiveAssessment(BRANCHED_CLOSURE)
        assessment.record("LOG", correct=True)

        # LOG exige PC, FA e FE: uma pergunta confirma quatro itens.
        self.assertEqual(assessment.confirmed_mastered, {"PC", "FA", "FE", "LOG"})
        # Mas PR fica em aberto — e o ramo paralelo, que LOG nao exige. Dar o
        # teste por encerrado aqui inventaria uma informacao que nao foi medida.
        self.assertEqual(assessment.open_items, {"PR"})
        self.assertFalse(assessment.is_complete)

        assessment.record("PR", correct=False)
        self.assertEqual(assessment.knowledge_state, {"PC", "FA", "FE", "LOG"})
        self.assertEqual(len(assessment.asked_items), 2)

    def test_a_wrong_answer_rules_out_everything_above_the_item(self):
        assessment = AdaptiveAssessment(BRANCHED_CLOSURE)
        assessment.record("PC", correct=False)

        # Sem PC nao ha nada: errar a base encerra o teste na primeira pergunta.
        self.assertTrue(assessment.is_complete)
        self.assertEqual(assessment.knowledge_state, frozenset())

    def test_rebuilding_from_answers_reproduces_the_same_result(self):
        original = simulate(BRANCHED_CLOSURE, {"PC", "FA", "PR"})

        rebuilt = AdaptiveAssessment.from_answers(BRANCHED_CLOSURE, original.answers)

        self.assertEqual(rebuilt.knowledge_state, original.knowledge_state)
        self.assertEqual(rebuilt.asked_items, original.asked_items)

    def test_item_outside_the_domain_is_rejected(self):
        assessment = AdaptiveAssessment(BRANCHED_CLOSURE)
        with self.assertRaisesMessage(ValueError, "Item fora do dominio"):
            assessment.record("TRIGONOMETRIA", correct=True)

    def test_contradictory_answers_are_rejected(self):
        assessment = AdaptiveAssessment(BRANCHED_CLOSURE)
        assessment.record("FE", correct=True)

        # FE certo implica FA dominado; dizer que FA esta errado nao sobra
        # estado nenhum. Nao acontece pelo fluxo normal, so injetando respostas.
        with self.assertRaises(InconsistentAnswerError):
            assessment.record("FA", correct=False)

    def test_answers_from_next_item_never_contradict(self):
        """
        Complemento do teste anterior: seguindo `next_item`, qualquer combinacao
        de respostas converge, porque so se pergunta o que ainda esta em aberto.
        """
        for pattern in range(2**6):
            assessment = AdaptiveAssessment(BRANCHED_CLOSURE)
            step = 0
            while not assessment.is_complete:
                correct = bool(pattern >> step & 1)
                assessment.record(assessment.next_item, correct=correct)
                step += 1
            with self.subTest(padrao=pattern):
                self.assertTrue(assessment.is_complete)


class FeedsRecommendationTests(SimpleTestCase):
    """
    O resultado do motor da Parte 3 entra no motor da Parte 2 sem conversao.
    """

    def test_estimated_state_goes_straight_into_the_recommendation(self):
        closure = load_curriculum().item_prerequisite_closure()

        assessment = simulate(closure, {"pc-par-ordenado", "pc-localizar-ponto"})
        recommendation = recommend_next_item(
            assessment.knowledge_state, closure, goal="lg-equacao-exponencial"
        )

        self.assertTrue(recommendation.is_decisive)
        self.assertEqual(recommendation.item, "pc-ler-grafico")

    def test_every_estimated_state_produces_a_usable_recommendation(self):
        curriculum = load_curriculum()
        closure = curriculum.item_prerequisite_closure()
        goal = "lg-equacao-exponencial"

        for true_state in generate_knowledge_states(closure):
            assessment = simulate(
                closure, true_state, item_order=curriculum.canonical_item_order
            )
            recommendation = recommend_next_item(
                assessment.knowledge_state, closure, goal=goal
            )
            with self.subTest(estado=len(true_state)):
                if goal in true_state:
                    self.assertFalse(recommendation.is_decisive)
                else:
                    self.assertTrue(recommendation.is_decisive)
                    self.assertNotIn(recommendation.item, true_state)
