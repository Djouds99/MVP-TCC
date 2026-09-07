"""
Geracao dos codigos de acesso do aluno.

Sem cadastro e sem login: o professor entrega um codigo curto a cada aluno, e e
ele que amarra pre-teste, pos-teste e turma ao mesmo participante sem que o
sistema saiba quem e a pessoa (CLAUDE.md secoes 5 e 8).
"""

import secrets

# Alfabeto sem caracteres que se confundem em papel impresso ou manuscrito:
# sem I/1, sem O/0. Reduz o codigo digitado errado numa sala com 30 alunos.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

MIN_CODE_LENGTH = 4
MAX_CODE_LENGTH = 6
DEFAULT_CODE_LENGTH = 5


def generate_code(length: int = DEFAULT_CODE_LENGTH) -> str:
    """Gera um codigo aleatorio com `length` caracteres do alfabeto acima."""
    if not MIN_CODE_LENGTH <= length <= MAX_CODE_LENGTH:
        raise ValueError(
            f"Comprimento do codigo deve estar entre {MIN_CODE_LENGTH} e "
            f"{MAX_CODE_LENGTH}; recebido {length}."
        )
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def normalize_code(raw: str) -> str:
    """
    Normaliza o que o aluno digitou: descarta espacos, hifens e pontuacao, e
    converte para maiuscula.

    Nao ha mapeamento de caracteres parecidos porque `CODE_ALPHABET` ja exclui
    todos eles: um "O" ou "1" digitado nao corresponde a nenhum codigo valido, e
    o certo e responder "codigo nao encontrado" em vez de adivinhar outro codigo.
    """
    return "".join(char for char in raw.upper() if char.isalnum())
