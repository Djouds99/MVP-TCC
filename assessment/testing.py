"""
Auxiliares para exercitar o instrumento em testes.

Ficam fora do modulo de teste porque sao usados por mais de um arquivo — o
percurso do app (Parte 4) precisa do pre-teste concluido antes de qualquer
coisa, e o percurso do instrumento (Parte 5) precisa do mesmo mecanismo.
"""

from assessment.services import (
    finalize_instrument,
    instrument_questions,
    next_instrument_question,
    record_instrument_response,
    start_instrument,
)


def complete_instrument(student, phase: str, correct: int = 0):
    """
    Responde o instrumento inteiro por um aluno simulado, acertando as `correct`
    primeiras questoes e errando o resto, e encerra a aplicacao.

    Devolve a `InstrumentSession` concluida.
    """
    total = len(instrument_questions())
    if not 0 <= correct <= total:
        raise ValueError(f"`correct` deve estar entre 0 e {total}; recebido {correct}.")

    session = start_instrument(student, phase)
    answered = 0
    while (question := next_instrument_question(session)) is not None:
        chosen = (
            question.correct_index
            if answered < correct
            else (question.correct_index + 1) % len(question.alternatives)
        )
        record_instrument_response(session, question, chosen)
        answered += 1

    return finalize_instrument(session)
