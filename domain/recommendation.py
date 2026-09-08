"""
Motor de recomendacao: fronteira externa com desempate por objetivo.

Esta e a peca que o TCC2 descreve como contribuicao. Ela e deliberadamente pura
— recebe conjuntos de codigos de item e devolve uma decisao — sem tocar banco,
sessao ou interface, para que possa ser testada contra o que a teoria preve.

A regra, em duas etapas:

1. **Fronteira externa.** Dado o estado de conhecimento estimado do aluno, os
   candidatos brutos sao os itens ainda nao dominados cujos pre-requisitos ja
   estao todos dominados (`outer_fringe`).

2. **Desempate por objetivo.** Quando a fronteira tem mais de um candidato, a
   escolha e a intersecao entre a fronteira e o caminho de pre-requisitos ate o
   objetivo declarado pelo aluno (STEINER; NUSSBAUMER; ALBERT, 2009).

Essa e a regra acordada e citavel. Ela **nao** deve ser trocada por outro
heuristico sem sinalizacao explicita, porque a metodologia do TCC2 descreve
exatamente isto (CLAUDE.md secao 2).

Nao ha ordenacao por dificuldade, por popularidade, nem qualquer pontuacao
aprendida: a decisao e deterministica e vem inteiramente da estrutura de
pre-requisitos.

Decisoes de borda, documentadas em vez de implicitas:

- **Fronteira vazia** (o estado ja e o dominio inteiro): nao ha o que
  recomendar. A funcao devolve `item=None` com motivo `DOMAIN_COMPLETE`, em vez
  de devolver um item qualquer ou levantar excecao — "terminou" e uma resposta
  legitima, e quem chama precisa distinguir isso de "nao sei".
- **Objetivo ja dominado**: idem, `item=None` com motivo `GOAL_ALREADY_REACHED`.
  Nao ha recuo para a fronteira inteira, porque isso seria recomendar por uma
  regra diferente da declarada sem dizer. O certo e a interface pedir um novo
  objetivo.
- **Sem objetivo declarado**: nao ha desempate a aplicar, e os candidatos sao a
  fronteira inteira, com motivo `NO_GOAL_DECLARED`.
- **Mais de um candidato sobrevivendo ao desempate**: `item` fica `None` e
  `candidates` traz todos. Escolher um deles exigiria um criterio que a regra
  acordada nao tem, e inventar esse criterio aqui seria justamente a
  substituicao silenciosa que a Secao 2 do CLAUDE.md proibe. Com a cadeia atual
  isso nao acontece — ha teste exaustivo garantindo que, havendo objetivo
  declarado, a resposta e sempre unica; se um dia a cadeia ganhar um topico com
  dois pre-requisitos independentes, esse teste falha e o criterio extra passa a
  ser uma decisao consciente, com reflexo no texto do TCC2.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from domain.knowledge_space import (
    is_knowledge_state,
    outer_fringe,
    prerequisite_path,
)


class RecommendationReason(StrEnum):
    """Por que a recomendacao ficou como ficou."""

    GOAL_DIRECTED = "goal_directed"
    """Fronteira filtrada pelo caminho ate o objetivo declarado."""

    NO_GOAL_DECLARED = "no_goal_declared"
    """Sem objetivo, nao ha desempate: os candidatos sao a fronteira inteira."""

    GOAL_ALREADY_REACHED = "goal_already_reached"
    """O objetivo declarado ja esta dominado; cabe declarar um novo."""

    DOMAIN_COMPLETE = "domain_complete"
    """O estado ja e o dominio inteiro; nao ha mais o que recomendar."""


@dataclass(frozen=True)
class Recommendation:
    """
    Resultado do motor.

    `item` so vem preenchido quando a regra determina uma resposta unica. Se
    sobrarem varios candidatos, `item` e None e `candidates` traz todos — quem
    chama decide o que fazer, em vez de receber uma escolha arbitraria
    disfarcada de decisao do motor.
    """

    item: str | None
    candidates: tuple[str, ...]
    fringe: tuple[str, ...]
    reason: RecommendationReason
    goal: str | None = None

    @property
    def is_decisive(self) -> bool:
        return self.item is not None


def recommend_next_item(
    state: Iterable[str],
    closure: Mapping[str, Iterable[str]],
    goal: str | None = None,
) -> Recommendation:
    """
    Recomenda o proximo item a estudar.

    `state` e o conjunto de itens ja dominados, `closure` o fecho transitivo dos
    pre-requisitos, e `goal` o item que o aluno declarou como objetivo.

    Levanta `ValueError` se o estado nao for um estado de conhecimento valido
    (isto e, se contiver um item sem algum pre-requisito) ou se o objetivo nao
    pertencer ao dominio. Sao erros de programacao de quem chama, nao situacoes
    a contornar em silencio.
    """
    current = frozenset(state)
    if not is_knowledge_state(current, closure):
        raise ValueError(
            "O estado informado nao e um estado de conhecimento: contem item "
            "sem todos os pre-requisitos dominados."
        )
    if goal is not None and goal not in closure:
        raise ValueError(f"Objetivo fora do dominio: {goal}")

    fringe = outer_fringe(current, closure)
    ordered_fringe = tuple(sorted(fringe))

    # Fronteira vazia equivale a dominio completo (ver `outer_fringe`). Vem
    # antes das demais checagens por ser a informacao mais util nesse caso.
    if not fringe:
        return Recommendation(
            item=None,
            candidates=(),
            fringe=(),
            reason=RecommendationReason.DOMAIN_COMPLETE,
            goal=goal,
        )

    if goal is None:
        return _build(
            ordered_fringe,
            ordered_fringe,
            RecommendationReason.NO_GOAL_DECLARED,
            goal,
        )

    if goal in current:
        return Recommendation(
            item=None,
            candidates=(),
            fringe=ordered_fringe,
            reason=RecommendationReason.GOAL_ALREADY_REACHED,
            goal=goal,
        )

    # O desempate propriamente dito. A intersecao nunca e vazia aqui: o objetivo
    # nao esta dominado, entao o caminho ate ele tem algum item faltando, e o
    # menor desses itens na ordem de pre-requisito tem todos os seus
    # pre-requisitos dentro do estado — logo esta na fronteira.
    candidates = tuple(sorted(fringe & prerequisite_path(goal, closure)))
    return _build(candidates, ordered_fringe, RecommendationReason.GOAL_DIRECTED, goal)


def _build(
    candidates: tuple[str, ...],
    fringe: tuple[str, ...],
    reason: RecommendationReason,
    goal: str | None,
) -> Recommendation:
    return Recommendation(
        item=candidates[0] if len(candidates) == 1 else None,
        candidates=candidates,
        fringe=fringe,
        reason=reason,
        goal=goal,
    )
