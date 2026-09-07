"""
Geracao do espaco de conhecimento a partir da relacao de pre-requisito.

Funcoes puras, sem dependencia do Django, para que possam ser testadas e
inspecionadas isoladamente da persistencia.

Fundamento: pela representacao de Birkhoff usada em KST, uma quase-ordem sobre
os itens do dominio determina um espaco de conhecimento quase ordinal, cujos
estados sao exatamente os subconjuntos fechados para baixo — todo item presente
no estado tem tambem seus pre-requisitos presentes. E isso que
`generate_knowledge_states` enumera.
"""

from collections.abc import Iterable, Mapping


class PrerequisiteCycleError(ValueError):
    """A relacao de pre-requisito contem ciclo e nao define uma ordem."""


def transitive_closure(
    direct: Mapping[str, Iterable[str]],
) -> dict[str, frozenset[str]]:
    """
    Devolve, para cada item, o conjunto de todos os seus pre-requisitos diretos e
    indiretos. Levanta `PrerequisiteCycleError` se a relacao tiver ciclo.
    """
    edges = {code: set(prereqs) for code, prereqs in direct.items()}

    unknown = {p for prereqs in edges.values() for p in prereqs} - edges.keys()
    if unknown:
        raise ValueError(
            "Pre-requisitos referenciam itens inexistentes: "
            + ", ".join(sorted(unknown))
        )

    closure: dict[str, frozenset[str]] = {}
    # 0 = nao visitado, 1 = em processamento (detecta ciclo), 2 = resolvido.
    mark: dict[str, int] = dict.fromkeys(edges, 0)

    def resolve(code: str, trail: list[str]) -> frozenset[str]:
        state = mark[code]
        if state == 2:
            return closure[code]
        if state == 1:
            cycle = trail[trail.index(code) :] + [code]
            raise PrerequisiteCycleError(
                "Ciclo na relacao de pre-requisito: " + " -> ".join(cycle)
            )

        mark[code] = 1
        trail.append(code)
        accumulated: set[str] = set()
        for parent in edges[code]:
            accumulated.add(parent)
            accumulated |= resolve(parent, trail)
        trail.pop()
        mark[code] = 2
        closure[code] = frozenset(accumulated)
        return closure[code]

    for code in edges:
        resolve(code, [])
    return closure


def generate_knowledge_states(
    closure: Mapping[str, Iterable[str]],
) -> list[frozenset[str]]:
    """
    Enumera todos os estados de conhecimento: os subconjuntos de itens fechados
    para baixo sob a relacao de pre-requisito.

    A busca parte do estado vazio e, a cada passo, acrescenta um item cujos
    pre-requisitos ja estao no estado. Todo estado fechado para baixo pode ser
    construido assim (basta adicionar os itens em ordem topologica), entao a
    enumeracao e completa.

    Devolve a lista ordenada por tamanho e depois por assinatura, de modo que o
    estado vazio e sempre o primeiro e o dominio completo o ultimo.
    """
    requirements = {code: frozenset(prereqs) for code, prereqs in closure.items()}

    empty: frozenset[str] = frozenset()
    found: set[frozenset[str]] = {empty}
    frontier = [empty]

    while frontier:
        current = frontier.pop()
        for code, needed in requirements.items():
            if code in current or not needed <= current:
                continue
            candidate = current | {code}
            if candidate not in found:
                found.add(candidate)
                frontier.append(candidate)

    return sorted(found, key=lambda state: (len(state), "|".join(sorted(state))))


def is_knowledge_state(
    items: Iterable[str], closure: Mapping[str, Iterable[str]]
) -> bool:
    """Verifica se um conjunto de itens e fechado para baixo (estado valido)."""
    selected = set(items)
    return all(set(closure[code]) <= selected for code in selected)
