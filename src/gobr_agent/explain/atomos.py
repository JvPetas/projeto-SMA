"""Separa uma linha de `quando` em condições atômicas (o conector `e` na mesma linha).

`inativos para o vendedor e inadimplentes` vira duas condições. O `e` que faz parte de uma
condição NÃO separa: `entre 10 dias e 90 dias`, `entre '2023-12-31' e '2023-01-01'`,
`maior que R$ 100 e menor que R$ 900` (manual 6.3) e qualquer `e` dentro de texto entre aspas.

O verbo "é" (`cnae é igual("1")`) vira "e" sem o acento. Antes de um operador (`igual`,
`diferente`, `contem`, `inicia com`) ele não é conector: some, e o átomo fica `cnae igual("1")`.
"""
from __future__ import annotations

import re

_NUM = r"(?:\d+|N)"  # aceita o texto com números e a assinatura (números trocados por N)
_TERMINA_EM_ENTRE = re.compile(rf"\bentre (?:{_NUM}(?: [a-z]+)?|'[^']*')$")
_COMECA_COM_NUMERO = re.compile(rf"^(?:{_NUM}\b|')")
_COMECA_COM_OPERADOR = re.compile(r"^(?:igual|diferente|contem|inicia com)\b")
_TERMINA_EM_VALOR = re.compile(rf"(?:(?:maior|menor) que|igual a) r\$\s*{_NUM}$")
_COMECA_COM_COMPARACAO = re.compile(r"^(?:(?:maior|menor) que|igual a) ")
_ENTRE_ASPAS = re.compile(r'"[^"]*"')


def _continua_a_mesma_condicao(anterior: str, seguinte: str) -> bool:
    if _TERMINA_EM_ENTRE.search(anterior) and _COMECA_COM_NUMERO.match(seguinte):
        return True
    return bool(_TERMINA_EM_VALOR.search(anterior) and _COMECA_COM_COMPARACAO.match(seguinte))


def separar_atomos(texto: str) -> list[str]:
    """Condições atômicas de um texto de `quando` já normalizado (sem a palavra `quando`)."""
    protegidos: list[str] = []

    def proteger(m: re.Match) -> str:
        protegidos.append(m.group(0))
        return f"\x00{len(protegidos) - 1}\x00"

    def restaurar(parte: str) -> str:
        return re.sub(r"\x00(\d+)\x00", lambda m: protegidos[int(m.group(1))], parte)

    pedacos = _ENTRE_ASPAS.sub(proteger, texto).split(" e ")
    atomos = [pedacos[0]]
    for pedaco in pedacos[1:]:
        if _COMECA_COM_OPERADOR.match(pedaco):
            atomos[-1] += " " + pedaco  # "cnae é igual(...)": o "é" é verbo, não conector
        elif _continua_a_mesma_condicao(restaurar(atomos[-1]), pedaco):
            atomos[-1] += " e " + pedaco
        else:
            atomos.append(pedaco)
    return [restaurar(a).strip() for a in atomos if a.strip()]
