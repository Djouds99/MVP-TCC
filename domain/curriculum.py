"""
Leitura e validacao do arquivo de curriculo versionado.

O conteudo do dominio vive em `domain/data/curriculum.json` e e revisado como
qualquer outro artefato do repositorio (CLAUDE.md secao 5). Este modulo le esse
arquivo, valida o que pode ser validado antes de tocar o banco, e deriva a
relacao de pre-requisito entre itens.

Regra de derivacao dos pre-requisitos entre itens — decisao de modelagem com
implicacao metodologica, entao explicitada aqui:

  **Cada item declara por completo os seus pre-requisitos diretos**, no campo
  `prerequisites`, inclusive os que apontam para itens de outro topico. O fecho
  transitivo dessas arestas e a relacao usada para gerar o espaco de
  conhecimento. Nao ha nenhuma heranca implicita: o que nao esta declarado nao e
  pre-requisito.

Ate 10/09/2026 valia outra regra — todo item de um topico herdava todos os itens
dos topicos pre-requisito, de modo que um topico so ficava acessivel com o
anterior inteiramente dominado. A entrevista de validacao pedagogica derrubou
isso (CLAUDE.md secao 9): o aluno pode comecar funcao exponencial com lacunas em
parte da funcao afim. Modelar acesso parcial exige justamente arestas entre itens
de topicos diferentes, que a regra antiga proibia.

O campo `prerequisites` do topico continua existindo, mas mudou de papel: nao
gera mais aresta nenhuma. Ele declara a cadeia de topicos como afirmacao
legivel, e o carregamento confere que as arestas entre itens e essa cadeia
contam a mesma historia — nenhuma aresta cruza para um topico que nao foi
declarado como pre-requisito, e nenhum topico declara pre-requisito que nenhum
item realiza.
"""

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from domain.knowledge_space import transitive_closure

DEFAULT_CURRICULUM_PATH = Path(__file__).resolve().parent / "data" / "curriculum.json"


class CurriculumError(ValueError):
    """Arquivo de curriculo mal formado ou internamente inconsistente."""


@dataclass(frozen=True)
class QuestionSpec:
    """
    Questao de multipla escolha amarrada a um item.

    As alternativas sao declaradas no arquivo como objetos com `correct`, o que
    e mais dificil de errar ao escrever conteudo do que um indice solto. Aqui
    ja chegam normalizadas em lista de textos mais o indice da correta, para que
    a resposta certa nunca acompanhe as alternativas ate a interface.
    """

    code: str
    item_code: str
    statement: str
    alternatives: tuple[str, ...]
    correct_index: int
    difficulty: int
    position: int


@dataclass(frozen=True)
class ItemSpec:
    code: str
    topic_code: str
    name: str
    description: str
    position: int
    difficulty: int
    prerequisites: tuple[str, ...]
    questions: tuple[QuestionSpec, ...] = ()


@dataclass(frozen=True)
class TopicSpec:
    code: str
    name: str
    summary: str
    position: int
    bncc_skills: tuple[str, ...]
    prerequisites: tuple[str, ...]
    items: tuple[ItemSpec, ...]


@dataclass(frozen=True)
class Curriculum:
    version: str
    subject: str
    checksum: str
    source_path: Path
    topics: tuple[TopicSpec, ...] = field(default=())

    def iter_items(self) -> Iterator[ItemSpec]:
        for topic in self.topics:
            yield from topic.items

    def iter_questions(self) -> Iterator[QuestionSpec]:
        for item in self.iter_items():
            yield from item.questions

    @property
    def item_codes(self) -> tuple[str, ...]:
        return tuple(item.code for item in self.iter_items())

    @property
    def canonical_item_order(self) -> tuple[str, ...]:
        """
        Ordem de leitura do curriculo: topicos por posicao, itens por posicao.

        Nao e a ordem de pre-requisito — serve so como criterio de desempate
        estavel onde uma escolha precisa ser deterministica.
        """
        return self.item_codes

    def direct_item_prerequisites(self) -> dict[str, set[str]]:
        """Arestas diretas declaradas em cada item, sem fecho."""
        return {item.code: set(item.prerequisites) for item in self.iter_items()}

    def topic_of(self) -> dict[str, str]:
        """Codigo do topico de cada item."""
        return {item.code: item.topic_code for item in self.iter_items()}

    def item_prerequisite_closure(self) -> dict[str, frozenset[str]]:
        return transitive_closure(self.direct_item_prerequisites())


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CurriculumError(message)


def _parse_questions(
    raw_questions, *, item_code: str, seen_codes: set[str]
) -> tuple[QuestionSpec, ...]:
    """Le e valida as questoes de um item, normalizando as alternativas."""
    questions: list[QuestionSpec] = []

    for position, raw in enumerate(raw_questions, start=1):
        question_code = raw.get("code")
        _require(bool(question_code), f"Questao sem `code` no item `{item_code}`.")
        _require(
            question_code not in seen_codes,
            f"Codigo de questao duplicado: {question_code}.",
        )
        seen_codes.add(question_code)

        statement = (raw.get("statement") or "").strip()
        _require(bool(statement), f"Questao `{question_code}` sem enunciado.")

        raw_alternatives = raw.get("alternatives") or ()
        _require(
            len(raw_alternatives) >= 2,
            f"Questao `{question_code}` precisa de pelo menos duas alternativas.",
        )

        correct_indexes = [
            index
            for index, alternative in enumerate(raw_alternatives)
            if alternative.get("correct")
        ]
        _require(
            len(correct_indexes) == 1,
            f"Questao `{question_code}` deve ter exatamente uma alternativa "
            f"correta; tem {len(correct_indexes)}.",
        )

        alternatives = tuple(
            (alternative.get("text") or "").strip() for alternative in raw_alternatives
        )
        _require(
            all(alternatives),
            f"Questao `{question_code}` tem alternativa sem texto.",
        )

        difficulty = int(raw.get("difficulty", 3))
        _require(
            1 <= difficulty <= 5,
            f"`difficulty` de `{question_code}` fora do intervalo 1..5.",
        )

        questions.append(
            QuestionSpec(
                code=question_code,
                item_code=item_code,
                statement=statement,
                alternatives=alternatives,
                correct_index=correct_indexes[0],
                difficulty=difficulty,
                position=int(raw.get("position", position)),
            )
        )

    return tuple(questions)


def _check_edges_agree_with_topic_chain(
    topics: list[TopicSpec], known_item_codes: set[str]
) -> None:
    """
    Confere que as arestas entre itens e a cadeia declarada de topicos dizem a
    mesma coisa.

    Desde que a heranca de topico deixou de existir, as duas coisas sao
    declaradas em lugares diferentes e poderiam divergir em silencio. As duas
    checagens abaixo fecham esse vao nas duas direcoes: nenhuma aresta cruza
    para um topico que a cadeia nao previu, e nenhum topico declara um
    pre-requisito que nenhuma aresta realiza.
    """
    topic_of_item = {
        item.code: topic.code for topic in topics for item in topic.items
    }
    # Levanta PrerequisiteCycleError se a cadeia de topicos tiver ciclo.
    topic_closure = transitive_closure(
        {topic.code: set(topic.prerequisites) for topic in topics}
    )

    witnessed: set[tuple[str, str]] = set()
    for topic in topics:
        for item in topic.items:
            for prerequisite in item.prerequisites:
                _require(
                    prerequisite in known_item_codes,
                    f"Item `{item.code}` referencia pre-requisito inexistente: "
                    f"{prerequisite}.",
                )
                source_topic = topic_of_item[prerequisite]
                if source_topic == topic.code:
                    continue
                _require(
                    source_topic in topic_closure[topic.code],
                    f"Item `{item.code}` (topico `{topic.code}`) depende de "
                    f"`{prerequisite}`, do topico `{source_topic}`, que nao esta "
                    f"na cadeia de pre-requisitos de `{topic.code}`. Declare "
                    f"`{source_topic}` em `topics[].prerequisites` ou corrija a "
                    f"aresta.",
                )
                witnessed.add((topic.code, source_topic))

    for topic in topics:
        for declared in topic.prerequisites:
            _require(
                (topic.code, declared) in witnessed,
                f"Topico `{topic.code}` declara `{declared}` como pre-requisito, "
                f"mas nenhum item de `{topic.code}` depende de item de "
                f"`{declared}`. A cadeia de topicos afirma uma dependencia que "
                f"a estrutura de itens nao tem.",
            )


def load_curriculum(path: Path | str | None = None) -> Curriculum:
    """Le, valida e devolve o curriculo. Levanta `CurriculumError` se invalido."""
    source = Path(path) if path else DEFAULT_CURRICULUM_PATH
    raw_bytes = source.read_bytes()
    checksum = hashlib.sha256(raw_bytes).hexdigest()

    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise CurriculumError(f"JSON invalido em {source}: {exc}") from exc

    _require(isinstance(data, dict), "A raiz do arquivo deve ser um objeto JSON.")
    _require(bool(data.get("version")), "Campo `version` ausente ou vazio.")
    _require(bool(data.get("topics")), "Campo `topics` ausente ou vazio.")

    topics: list[TopicSpec] = []
    seen_topic_codes: set[str] = set()
    seen_item_codes: set[str] = set()
    seen_question_codes: set[str] = set()

    for raw_topic in data["topics"]:
        code = raw_topic.get("code")
        _require(bool(code), "Topico sem `code`.")
        _require(code not in seen_topic_codes, f"Codigo de topico duplicado: {code}.")
        seen_topic_codes.add(code)

        raw_items = raw_topic.get("items") or []
        _require(bool(raw_items), f"Topico `{code}` nao tem itens.")

        items: list[ItemSpec] = []
        for raw_item in raw_items:
            item_code = raw_item.get("code")
            _require(bool(item_code), f"Item sem `code` no topico `{code}`.")
            _require(
                item_code not in seen_item_codes,
                f"Codigo de item duplicado: {item_code}.",
            )
            seen_item_codes.add(item_code)

            item_prerequisites = tuple(raw_item.get("prerequisites") or ())

            difficulty = int(raw_item.get("difficulty", 3))
            _require(
                1 <= difficulty <= 5,
                f"`difficulty` de `{item_code}` fora do intervalo 1..5.",
            )

            items.append(
                ItemSpec(
                    code=item_code,
                    topic_code=code,
                    name=raw_item.get("name", ""),
                    description=raw_item.get("description", ""),
                    position=int(raw_item.get("position", 0)),
                    difficulty=difficulty,
                    prerequisites=item_prerequisites,
                    questions=_parse_questions(
                        raw_item.get("questions") or (),
                        item_code=item_code,
                        seen_codes=seen_question_codes,
                    ),
                )
            )

        topics.append(
            TopicSpec(
                code=code,
                name=raw_topic.get("name", ""),
                summary=raw_topic.get("summary", ""),
                position=int(raw_topic.get("position", 0)),
                bncc_skills=tuple(raw_topic.get("bncc_skills") or ()),
                prerequisites=tuple(raw_topic.get("prerequisites") or ()),
                items=tuple(items),
            )
        )

    for topic in topics:
        unknown = set(topic.prerequisites) - seen_topic_codes
        _require(
            not unknown,
            f"Topico `{topic.code}` referencia pre-requisito inexistente: "
            f"{', '.join(sorted(unknown))}.",
        )
        _require(
            topic.code not in topic.prerequisites,
            f"Topico `{topic.code}` e pre-requisito de si mesmo.",
        )

    _check_edges_agree_with_topic_chain(topics, seen_item_codes)

    curriculum = Curriculum(
        version=str(data["version"]),
        subject=str(data.get("subject", "")),
        checksum=checksum,
        source_path=source,
        topics=tuple(topics),
    )

    # Dispara PrerequisiteCycleError se houver ciclo — melhor descobrir na
    # leitura do que ao gerar o espaco de conhecimento.
    curriculum.item_prerequisite_closure()
    return curriculum
