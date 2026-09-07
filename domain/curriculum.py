"""
Leitura e validacao do arquivo de curriculo versionado.

O conteudo do dominio vive em `domain/data/curriculum.json` e e revisado como
qualquer outro artefato do repositorio (CLAUDE.md secao 5). Este modulo le esse
arquivo, valida o que pode ser validado antes de tocar o banco, e deriva a
relacao de pre-requisito entre itens.

Regra de derivacao dos pre-requisitos entre itens — decisao de modelagem com
implicacao metodologica, entao explicitada aqui:

  (a) arestas explicitas declaradas no campo `prerequisites` de cada item, que
      so podem apontar para itens do mesmo topico;
  (b) heranca de topico: todo item de um topico T tem como pre-requisito todos
      os itens de cada topico diretamente pre-requisito de T.

O fecho transitivo de (a) + (b) e a relacao usada para gerar o espaco de
conhecimento. Em outras palavras: dentro do topico a ordem e a declarada; entre
topicos, um topico so e considerado acessivel quando os anteriores estao
inteiramente dominados.
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
class ItemSpec:
    code: str
    topic_code: str
    name: str
    description: str
    position: int
    difficulty: int
    prerequisites: tuple[str, ...]


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

    @property
    def item_codes(self) -> tuple[str, ...]:
        return tuple(item.code for item in self.iter_items())

    def direct_item_prerequisites(self) -> dict[str, set[str]]:
        """Arestas (a) + (b) descritas no cabecalho do modulo, sem fecho."""
        items_by_topic = {
            topic.code: [item.code for item in topic.items] for topic in self.topics
        }

        edges: dict[str, set[str]] = {}
        for topic in self.topics:
            inherited: set[str] = set()
            for prerequisite_topic in topic.prerequisites:
                inherited.update(items_by_topic[prerequisite_topic])
            for item in topic.items:
                edges[item.code] = set(item.prerequisites) | inherited
        return edges

    def item_prerequisite_closure(self) -> dict[str, frozenset[str]]:
        return transitive_closure(self.direct_item_prerequisites())


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CurriculumError(message)


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

    for raw_topic in data["topics"]:
        code = raw_topic.get("code")
        _require(bool(code), "Topico sem `code`.")
        _require(code not in seen_topic_codes, f"Codigo de topico duplicado: {code}.")
        seen_topic_codes.add(code)

        raw_items = raw_topic.get("items") or []
        _require(bool(raw_items), f"Topico `{code}` nao tem itens.")

        topic_item_codes = {raw_item.get("code") for raw_item in raw_items}
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
            # Arestas entre itens de topicos diferentes ficariam invisiveis na
            # cadeia declarada de topicos; a dependencia entre topicos deve ser
            # declarada no nivel de topico, onde e legivel.
            outsiders = set(item_prerequisites) - topic_item_codes
            _require(
                not outsiders,
                f"Item `{item_code}` declara pre-requisito fora do proprio topico: "
                f"{', '.join(sorted(outsiders))}. Dependencia entre topicos deve "
                f"ser declarada em `topics[].prerequisites`.",
            )

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
