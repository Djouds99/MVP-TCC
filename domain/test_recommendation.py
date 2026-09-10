"""
Testes do motor KST: fronteira externa e desempate por objetivo.

A primeira classe usa o dominio de exemplo pequeno, calculado a mao, para
conferir que a implementacao bate com o que a teoria preve. As demais cobrem
bordas e propriedades sobre o curriculo real.

Nenhum destes testes toca o banco (`SimpleTestCase`) — se algum dia precisarem
tocar, e sinal de que o motor deixou de ser puro.
"""

from django.test import SimpleTestCase

from domain.curriculum import load_curriculum
from domain.knowledge_space import (
    generate_knowledge_states,
    is_knowledge_state,
    neighbour_states,
    outer_fringe,
    prerequisite_path,
    transitive_closure,
)
from domain.recommendation import (
    RecommendationReason,
    recommend_next_item,
)

# Dominio de exemplo, revisado apos a validacao pedagogica de 10/09/2026
# (CLAUDE.md secao 9). A versao anterior tinha um item por topico, o que nao
# consegue expressar acesso parcial — e acesso parcial e exatamente a regra
# nova. Funcao afim aparece aqui dividida nos dois papeis que a entrevista
# distinguiu:
#
#   PC ─→ FA1 ─┬─→ FA2 ─→ PR
#              └─→ FE ──→ LOG
#
#   FA1 = lei de formacao   -> bloqueia funcao exponencial
#   FA2 = taxa de variacao  -> desejavel, NAO bloqueia
#
# Consequencia: FE fica disponivel com FA1 apenas, enquanto PR ainda exige
# funcao afim inteira. E o que distingue esta estrutura da anterior.
EXAMPLE_EDGES = {
    "PC": [],
    "FA1": ["PC"],
    "FA2": ["FA1"],
    "FE": ["FA1"],
    "PR": ["FA2"],
    "LOG": ["FE"],
}
EXAMPLE_CLOSURE = transitive_closure(EXAMPLE_EDGES)


class RoadmapCasesTests(SimpleTestCase):
    """Os quatro casos da tabela do roadmap, com os valores calculados a mao."""

    def test_the_four_declared_cases(self):
        # Recalculados a mao contra a estrutura de 10/09/2026. Fecho usado:
        #   PC:{}  FA1:{PC}  FA2:{PC,FA1}  FE:{PC,FA1}
        #   PR:{PC,FA1,FA2}  LOG:{PC,FA1,FE}
        #
        # O caso 3 mudou de resposta: com acesso parcial, chegar a PR exige
        # antes FA2, que a estrutura antiga ja dava como dominado junto com o
        # topico inteiro.
        cases = [
            (1, set(), "LOG", {"PC"}, "PC"),
            (2, {"PC", "FA1"}, "LOG", {"FA2", "FE"}, "FE"),
            (3, {"PC", "FA1"}, "PR", {"FA2", "FE"}, "FA2"),
            (4, {"PC", "FA1", "FE"}, "LOG", {"FA2", "LOG"}, "LOG"),
        ]
        for number, state, goal, expected_fringe, expected_item in cases:
            with self.subTest(caso=number, estado=sorted(state), objetivo=goal):
                result = recommend_next_item(state, EXAMPLE_CLOSURE, goal=goal)

                self.assertEqual(set(result.fringe), expected_fringe)
                self.assertEqual(result.item, expected_item)
                self.assertEqual(result.candidates, (expected_item,))
                self.assertEqual(result.reason, RecommendationReason.GOAL_DIRECTED)

    def test_same_state_and_fringe_but_goal_changes_the_recommendation(self):
        """
        O contraste entre os casos 2 e 3, isolado.

        Mesmo estado, mesma fronteira bruta, recomendacoes diferentes. Se estas
        duas chamadas devolverem a mesma coisa, o desempate nao esta filtrando
        nada — esta so repassando a fronteira.
        """
        state = {"PC", "FA1"}

        towards_log = recommend_next_item(state, EXAMPLE_CLOSURE, goal="LOG")
        towards_pr = recommend_next_item(state, EXAMPLE_CLOSURE, goal="PR")

        self.assertEqual(towards_log.fringe, towards_pr.fringe)
        self.assertEqual(set(towards_log.fringe), {"FA2", "FE"})
        self.assertNotEqual(towards_log.item, towards_pr.item)
        self.assertEqual(towards_log.item, "FE")
        self.assertEqual(towards_pr.item, "FA2")

    def test_partial_access_state_is_legitimate(self):
        """
        Caso que so existe na estrutura nova: o aluno chegou em exponencial sem
        ter funcao afim inteira. Na estrutura antiga isto nao era estado de
        conhecimento nenhum, e a chamada teria levantado ValueError.
        """
        state = {"PC", "FA1", "FE"}

        result = recommend_next_item(state, EXAMPLE_CLOSURE, goal="LOG")

        self.assertEqual(result.item, "LOG")
        # FA2 segue em aberto e na fronteira, mas fora do caminho ate LOG.
        self.assertIn("FA2", result.fringe)
        self.assertNotIn("FA2", result.candidates)


class EmptyFringeTests(SimpleTestCase):
    """
    Caso proprio exigido pelo criterio de conclusao da Parte 2: estado que ja
    contem o dominio inteiro.

    Decisao documentada: a funcao devolve `item=None` com motivo
    `DOMAIN_COMPLETE`. Nao levanta excecao, porque "o aluno terminou" e um
    resultado legitimo e nao um erro; e nao devolve um item qualquer, porque
    nao ha nenhum que satisfaca a regra.
    """

    def test_full_domain_has_empty_fringe_and_no_recommendation(self):
        full_domain = set(EXAMPLE_CLOSURE)

        result = recommend_next_item(full_domain, EXAMPLE_CLOSURE, goal="LOG")

        self.assertEqual(result.fringe, ())
        self.assertEqual(result.candidates, ())
        self.assertIsNone(result.item)
        self.assertFalse(result.is_decisive)
        self.assertEqual(result.reason, RecommendationReason.DOMAIN_COMPLETE)

    def test_domain_complete_takes_precedence_over_goal_reached(self):
        # No dominio completo o objetivo tambem esta dominado; a precedencia
        # entre os dois motivos e fixada aqui para nao ficar implicita.
        result = recommend_next_item(
            set(EXAMPLE_CLOSURE), EXAMPLE_CLOSURE, goal="PC"
        )
        self.assertEqual(result.reason, RecommendationReason.DOMAIN_COMPLETE)

    def test_empty_fringe_happens_only_at_the_full_domain(self):
        for state in generate_knowledge_states(EXAMPLE_CLOSURE):
            with self.subTest(estado=sorted(state)):
                self.assertEqual(
                    not outer_fringe(state, EXAMPLE_CLOSURE),
                    set(state) == set(EXAMPLE_CLOSURE),
                )


class GoalEdgeCaseTests(SimpleTestCase):
    def test_goal_already_reached_returns_no_recommendation(self):
        result = recommend_next_item({"PC", "FA1"}, EXAMPLE_CLOSURE, goal="FA1")

        self.assertIsNone(result.item)
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.reason, RecommendationReason.GOAL_ALREADY_REACHED)
        # A fronteira continua sendo informada, para a interface poder pedir um
        # objetivo novo mostrando o que esta ao alcance.
        self.assertEqual(set(result.fringe), {"FA2", "FE"})

    def test_without_a_goal_the_candidates_are_the_whole_fringe(self):
        result = recommend_next_item({"PC", "FA1"}, EXAMPLE_CLOSURE)

        self.assertEqual(result.reason, RecommendationReason.NO_GOAL_DECLARED)
        self.assertEqual(set(result.candidates), {"FA2", "FE"})
        # Dois candidatos e nenhum criterio declarado para escolher entre eles:
        # o motor nao inventa um.
        self.assertIsNone(result.item)

    def test_goal_outside_the_domain_is_rejected(self):
        with self.assertRaisesMessage(ValueError, "Objetivo fora do dominio"):
            recommend_next_item({"PC"}, EXAMPLE_CLOSURE, goal="TRIGONOMETRIA")

    def test_invalid_state_is_rejected(self):
        # LOG sem FE nao e um estado de conhecimento.
        with self.assertRaisesMessage(ValueError, "nao e um estado de conhecimento"):
            recommend_next_item({"PC", "FA1", "LOG"}, EXAMPLE_CLOSURE, goal="LOG")

    def test_item_outside_the_domain_in_the_state_is_rejected(self):
        with self.assertRaisesMessage(ValueError, "Itens fora do dominio"):
            recommend_next_item({"PC", "GEOMETRIA"}, EXAMPLE_CLOSURE, goal="FA1")


class OuterFringeTests(SimpleTestCase):
    def test_fringe_items_produce_valid_neighbour_states(self):
        for state in generate_knowledge_states(EXAMPLE_CLOSURE):
            for item in outer_fringe(state, EXAMPLE_CLOSURE):
                with self.subTest(estado=sorted(state), item=item):
                    self.assertNotIn(item, state)
                    self.assertTrue(
                        is_knowledge_state(set(state) | {item}, EXAMPLE_CLOSURE)
                    )

    def test_items_outside_the_fringe_do_not_produce_valid_states(self):
        for state in generate_knowledge_states(EXAMPLE_CLOSURE):
            fringe = outer_fringe(state, EXAMPLE_CLOSURE)
            for item in set(EXAMPLE_CLOSURE) - set(state) - fringe:
                with self.subTest(estado=sorted(state), item=item):
                    self.assertFalse(
                        is_knowledge_state(set(state) | {item}, EXAMPLE_CLOSURE)
                    )

    def test_neighbour_states_matches_the_fringe(self):
        state = {"PC", "FA1"}
        self.assertEqual(
            neighbour_states(state, EXAMPLE_CLOSURE),
            [frozenset({"PC", "FA1", "FA2"}), frozenset({"PC", "FA1", "FE"})],
        )

    def test_prerequisite_path_includes_the_goal_itself(self):
        self.assertEqual(
            prerequisite_path("LOG", EXAMPLE_CLOSURE), {"PC", "FA1", "FE", "LOG"}
        )
        self.assertEqual(prerequisite_path("PC", EXAMPLE_CLOSURE), {"PC"})
        # Nem PR nem FA2 entram no caminho ate LOG: FA2 e a parte de funcao afim
        # que deixou de ser bloqueadora, e PR e o ramo paralelo.
        self.assertNotIn("PR", prerequisite_path("LOG", EXAMPLE_CLOSURE))
        self.assertNotIn("FA2", prerequisite_path("LOG", EXAMPLE_CLOSURE))


class RealCurriculumTests(SimpleTestCase):
    """Propriedades do motor sobre o curriculo que vai a campo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.closure = load_curriculum().item_prerequisite_closure()
        cls.states = generate_knowledge_states(cls.closure)

    def test_recommendation_is_always_inside_the_fringe(self):
        for state in self.states:
            for goal in self.closure:
                result = recommend_next_item(state, self.closure, goal=goal)
                with self.subTest(estado=len(state), objetivo=goal):
                    self.assertTrue(set(result.candidates) <= set(result.fringe))

    def test_recommendation_advances_towards_the_declared_goal(self):
        for state in self.states:
            for goal in self.closure:
                if goal in state:
                    continue
                result = recommend_next_item(state, self.closure, goal=goal)
                with self.subTest(estado=len(state), objetivo=goal):
                    path = prerequisite_path(goal, self.closure)
                    self.assertTrue(set(result.candidates) <= path)
                    self.assertTrue(result.candidates)

    def test_a_declared_goal_always_yields_a_single_recommendation(self):
        """
        Tripwire deliberado.

        Com a cadeia atual, o desempate por objetivo sempre resolve para um
        unico item, porque nenhum topico tem dois pre-requisitos independentes.
        Se isso mudar, este teste falha — e a decisao sobre qual criterio extra
        usar para escolher entre os candidatos restantes passa a ser consciente,
        com reflexo obrigatorio na metodologia do TCC2 (CLAUDE.md secao 2). Nao
        remover este teste sem essa conversa.
        """
        for state in self.states:
            for goal in self.closure:
                if goal in state:
                    continue
                result = recommend_next_item(state, self.closure, goal=goal)
                with self.subTest(estado=sorted(state), objetivo=goal):
                    self.assertTrue(
                        result.is_decisive,
                        "O desempate por objetivo deixou mais de um candidato "
                        f"({', '.join(result.candidates)}). A regra acordada nao "
                        "define como escolher entre eles.",
                    )

    def test_following_the_recommendation_always_reaches_the_goal(self):
        """
        Segue a recomendacao repetidamente a partir do estado vazio e confere
        que o objetivo e alcancado sem passar por item fora do caminho — que e o
        comportamento que a proposta promete ao aluno.
        """
        for goal in self.closure:
            state: set[str] = set()
            visited: list[str] = []
            while goal not in state:
                result = recommend_next_item(state, self.closure, goal=goal)
                self.assertTrue(result.is_decisive)
                visited.append(result.item)
                state.add(result.item)

            with self.subTest(objetivo=goal):
                path = prerequisite_path(goal, self.closure)
                self.assertEqual(set(visited), path)
                self.assertEqual(len(visited), len(path), "item repetido no percurso")
