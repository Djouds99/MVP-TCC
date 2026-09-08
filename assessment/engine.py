"""
Motor do teste de posicionamento adaptativo.

Objetivo: a partir de respostas certo/errado, convergir para o estado de
conhecimento do aluno fazendo bem menos perguntas do que sondar item por item.
Modulo puro — sem Django, sem banco, sem sessao — para poder ser exercitado com
respostas simuladas.

## Como funciona

O motor mantem o conjunto de estados de conhecimento ainda compativeis com as
respostas dadas. Comeca com todos eles e, a cada resposta, descarta os
incompativeis:

- acertou o item q  ->  ficam so os estados que contem q;
- errou o item q    ->  ficam so os estados que nao contem q.

Como os estados sao fechados para baixo, uma unica resposta carrega muito mais
informacao do que o item perguntado: acertar `logaritmo` elimina de uma vez
todos os estados que nao contenham tambem plano cartesiano, funcao afim e
funcao exponencial. Nao e preciso deduzir isso a mao — o filtro sobre os estados
ja faz.

A proxima pergunta e sobre o item que divide mais ao meio o conjunto restante:
e a pergunta cuja resposta, seja qual for, elimina mais candidatos. O teste
termina quando sobra um unico estado compativel, que e a estimativa final.

## Por que nao e uma busca binaria ao longo da cadeia

A cadeia deste MVP nao e uma fila: funcao exponencial e progressoes ficam
disponiveis em paralelo assim que funcao afim e dominada. Uma busca binaria
supoe que o dominio esta totalmente ordenado e que o conhecimento do aluno e um
prefixo dessa ordem — e 18 dos 34 estados deste curriculo nao sao prefixo de
ordem linear nenhuma.

Na pratica isso quer dizer que uma busca binaria linear classificaria errado o
aluno que avancou num ramo e nao no outro: quem domina progressoes mas nao
exponencial seria dado como nao tendo nenhum dos dois.

O que esta implementado aqui e a mesma ideia — dividir ao meio o que ainda esta
em aberto — aplicada ao conjunto de estados em vez de a uma fila de itens.
Sobre uma cadeia realmente linear, os dois procedimentos coincidem: ha teste
verificando isso.

## Suposicao que o metodo assume

O procedimento e deterministico: acerto e lido como dominio do item, erro como
ausencia de dominio. Nao ha modelo de chute nem de erro por distracao — isso
seria teoria de resposta ao item, que esta fora do escopo acordado
(CLAUDE.md secao 2).

A consequencia pratica precisa estar no texto do TCC2: num item de multipla
escolha com quatro alternativas, um chute certeiro faz o motor concluir dominio
que nao existe, e o estado estimado sai deslocado para cima. O motor nao detecta
isso — como so pergunta sobre itens ainda em aberto, qualquer sequencia de
respostas e internamente consistente e sempre converge. Mitigar isso exigiria
mais de uma questao por item, o que alonga o teste; e decisao pedagogica, nao
tecnica, e por isso nao foi tomada aqui.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from domain.knowledge_space import generate_knowledge_states


class InconsistentAnswerError(ValueError):
    """
    A resposta registrada nao e compativel com nenhum estado de conhecimento.

    Nao acontece quando as perguntas saem de `next_item`, que so oferece itens
    ainda em aberto. Aparece se respostas forem injetadas fora dessa ordem — por
    exemplo, ao reprocessar respostas antigas depois de o curriculo mudar.
    """


@dataclass(frozen=True)
class Answer:
    item: str
    correct: bool


class AdaptiveAssessment:
    """
    Uma sessao de teste adaptativo.

    Uso:

        assessment = AdaptiveAssessment(closure)
        while not assessment.is_complete:
            item = assessment.next_item
            assessment.record(item, correct=aluno_acertou(item))
        estado = assessment.knowledge_state

    O objeto e reconstruivel a partir das respostas ja dadas
    (`from_answers`), entao nao e preciso guardar nada entre requisicoes: basta
    reler as respostas gravadas e refazer o mesmo caminho.
    """

    def __init__(
        self,
        closure: Mapping[str, Iterable[str]],
        item_order: Sequence[str] | None = None,
    ) -> None:
        self._closure = {code: frozenset(prereqs) for code, prereqs in closure.items()}
        self._candidates = frozenset(generate_knowledge_states(self._closure))
        self._answers: list[Answer] = []

        # Criterio de desempate estavel quando duas perguntas dividem o conjunto
        # igualmente bem. Por padrao a ordem de leitura do curriculo, que sonda
        # o mais elementar primeiro; alfabetica so como ultimo recurso.
        order = list(item_order) if item_order else sorted(self._closure)
        self._rank = {code: index for index, code in enumerate(order)}

    @classmethod
    def from_answers(
        cls,
        closure: Mapping[str, Iterable[str]],
        answers: Iterable[Answer],
        item_order: Sequence[str] | None = None,
    ) -> "AdaptiveAssessment":
        assessment = cls(closure, item_order=item_order)
        for answer in answers:
            assessment.record(answer.item, correct=answer.correct)
        return assessment

    @property
    def answers(self) -> tuple[Answer, ...]:
        return tuple(self._answers)

    @property
    def asked_items(self) -> tuple[str, ...]:
        return tuple(answer.item for answer in self._answers)

    @property
    def candidate_states(self) -> frozenset[frozenset[str]]:
        return self._candidates

    @property
    def is_complete(self) -> bool:
        return len(self._candidates) == 1

    @property
    def open_items(self) -> frozenset[str]:
        """
        Itens ainda em aberto: os que aparecem em alguns candidatos e nao em
        outros. Sao exatamente os que vale a pena perguntar — para os demais a
        resposta ja esta determinada pelas respostas anteriores.
        """
        return frozenset(
            code
            for code in self._closure
            if any(code in state for state in self._candidates)
            and any(code not in state for state in self._candidates)
        )

    @property
    def confirmed_mastered(self) -> frozenset[str]:
        """
        Itens presentes em todos os candidatos — dominio ja estabelecido, mesmo
        com o teste incompleto.

        Num teste abandonado no meio isto e um limite inferior do que o aluno
        sabe, nao uma estimativa do estado. Usar como se fosse estado tem peso
        metodologico e nao deve ser feito em silencio.
        """
        return frozenset.intersection(*self._candidates) if self._candidates else frozenset()

    @property
    def knowledge_state(self) -> frozenset[str]:
        """
        Estimativa final. So disponivel com o teste concluido — entregar um
        estado parcial como se fosse o resultado esconderia que a medida ainda
        nao fechou.
        """
        if not self.is_complete:
            raise ValueError(
                "O teste ainda nao convergiu: "
                f"{len(self._candidates)} estados continuam compativeis. "
                "Use `confirmed_mastered` para o que ja esta estabelecido."
            )
        return next(iter(self._candidates))

    @property
    def next_item(self) -> str | None:
        """
        Proximo item a sondar, ou None se o teste ja convergiu.

        Escolhe o item que deixa os dois desfechos possiveis mais equilibrados,
        ou seja, o que elimina mais candidatos no pior caso.
        """
        if self.is_complete:
            return None

        total = len(self._candidates)
        return min(
            self.open_items,
            key=lambda code: (
                abs(2 * self._count_with(code) - total),
                self._rank.get(code, len(self._rank)),
                code,
            ),
        )

    def record(self, item: str, correct: bool) -> None:
        """Registra uma resposta e descarta os estados incompativeis com ela."""
        if item not in self._closure:
            raise ValueError(f"Item fora do dominio: {item}")

        remaining = frozenset(
            state for state in self._candidates if (item in state) is correct
        )
        if not remaining:
            raise InconsistentAnswerError(
                f"A resposta para `{item}` nao e compativel com nenhum estado "
                "de conhecimento restante."
            )

        self._candidates = remaining
        self._answers.append(Answer(item=item, correct=correct))

    def _count_with(self, item: str) -> int:
        return sum(1 for state in self._candidates if item in state)


def simulate(
    closure: Mapping[str, Iterable[str]],
    true_state: Iterable[str],
    item_order: Sequence[str] | None = None,
) -> AdaptiveAssessment:
    """
    Roda um teste completo contra um aluno ideal cujo conhecimento real e
    `true_state`: ele acerta exatamente os itens que domina.

    Serve para os testes e para medir quantas perguntas o procedimento gasta.
    """
    truth = set(true_state)
    assessment = AdaptiveAssessment(closure, item_order=item_order)
    while not assessment.is_complete:
        item = assessment.next_item
        assessment.record(item, correct=item in truth)
    return assessment
