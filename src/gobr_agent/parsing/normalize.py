"""Normalização de texto da DSL GOBR: acentos, caixa, espaços e parênteses."""
from __future__ import annotations

import re
import unicodedata
import warnings

_ENTRE_ASPAS = re.compile(r'("[^"]*")')


def remover_controles(texto: str) -> str:
    return "".join(c for c in texto if unicodedata.category(c) != "Cc" or c in "\t\n\r")


def sem_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def normalizar(texto: str) -> str:
    """Minúsculas, sem acentos, espaços colapsados.

    Fora de aspas também some o espaço antes de `(` e em volta de vírgulas e parênteses,
    para que `do time ("x")` e `porid ("1", "2")` fiquem iguais a `do time("x")` e
    `porid("1","2")`.
    """
    limpo = remover_controles(texto)
    if limpo != texto:
        warnings.warn("caracteres de controle removidos", UserWarning, stacklevel=2)
    partes = _ENTRE_ASPAS.split(sem_acentos(limpo).lower())
    for i, parte in enumerate(partes):
        parte = re.sub(r"\s+", " ", parte)
        if i % 2 == 0:
            parte = re.sub(r"\s*\(\s*", "(", parte)
            parte = re.sub(r"\s*\)", ")", parte)
            parte = re.sub(r"\s*,\s*", ",", parte)
        partes[i] = parte
    return re.sub(r"\s+", " ", "".join(partes)).strip()


def assinatura(texto_normalizado: str) -> str:
    """Texto normalizado com todos os números trocados por N."""
    return re.sub(r"\d+", "N", texto_normalizado)


def balanco_parenteses(texto: str) -> tuple[int, int]:
    """(saldo final, saldo mínimo) dos parênteses, ignorando o que está entre aspas."""
    saldo = minimo = 0
    em_texto = False
    for c in texto:
        if c == '"':
            em_texto = not em_texto
        elif not em_texto:
            if c == "(":
                saldo += 1
            elif c == ")":
                saldo -= 1
                minimo = min(minimo, saldo)
    return saldo, minimo


def tem_aspa_solta(texto: str) -> bool:
    """Número ímpar de aspas e a última é a do fim da linha (ex.: `... no sabado"`)."""
    return texto.count('"') % 2 == 1 and texto.rstrip().endswith('"')
