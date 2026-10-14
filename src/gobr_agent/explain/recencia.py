"""Recência: intervalos em dias desde a última compra e o efeito da ORDEM dos blocos.

Cada bloco `parametros` só trata clientes que os blocos anteriores ainda não trataram. Em uma
cadeia como "recencia de positivacao em 60 dias" seguida de "... em 90 dias", o segundo bloco
vale, na prática, para clientes entre 60 e 90 dias.

Regras (etapa 1, passo 2):
- Intervalos em dias desde a última compra: `em N` = [0, N]; `entre a e b` = [a, b];
  `fora ... em N` = (N, infinito); condições ligadas por `e` = interseção.
- Uma cadeia por (escopo, time). Chave da cadeia: positivação (`global` e sem `global` JUNTOS,
  com nota quando misturados) | positivação `do vendedor` | visita. Cadeias separadas.
- Só blocos PUROS (apenas recência da mesma cadeia, sem filtro temporal, sem `ou`) entram na
  união dos intervalos já consumidos. Um bloco `nao agendar` puro de recência conta (consome
  clientes). Bloco com outra condição ou filtro temporal não entra na união, e os blocos
  seguintes ganham a nota "pode haver clientes já tratados pela regra <nome>".
- O catch-all sai "mais de N dias" só se a cadeia cobrir [0, N] sem lacuna; com lacuna, a
  lacuna vai para as notas e nada mais é afirmado.
- Bordas só como "entre a e b": o manual diz "intervalo" e não define se a borda é inclusiva.
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from ..parsing.models import ArquivoGobr, Parametros
from .atomos import separar_atomos

INF = float("inf")
Intervalo = tuple[float, float]
Intervalos = tuple[Intervalo, ...]  # disjuntos, ordenados, sem bordas que se tocam

CADEIAS = ("positivacao", "positivacao_vendedor", "visita")

# ------------------------------------------------------------------- álgebra de intervalos


def normalizar_intervalos(itens) -> Intervalos:
    """Ordena, funde sobrepostos/encostados e descarta os de tamanho zero."""
    saida: list[Intervalo] = []
    for lo, hi in sorted((lo, hi) for lo, hi in itens if hi > lo):
        if saida and lo <= saida[-1][1]:
            saida[-1] = (saida[-1][0], max(saida[-1][1], hi))
        else:
            saida.append((lo, hi))
    return tuple(saida)


def uniao(a: Intervalos, b: Intervalos) -> Intervalos:
    return normalizar_intervalos(a + b)


def intersecao(a: Intervalos, b: Intervalos) -> Intervalos:
    return normalizar_intervalos((max(l1, l2), min(h1, h2)) for l1, h1 in a for l2, h2 in b)


def complemento(a: Intervalos) -> Intervalos:
    """O que sobra de [0, infinito) fora de `a`."""
    saida: list[Intervalo] = []
    cursor = 0.0
    for lo, hi in a:
        if lo > cursor:
            saida.append((cursor, lo))
        cursor = max(cursor, hi)
    if cursor < INF:
        saida.append((cursor, INF))
    return tuple(saida)


def diferenca(a: Intervalos, b: Intervalos) -> Intervalos:
    return intersecao(a, complemento(b))


def _n(x: float) -> str:
    return str(int(x)) if x == int(x) else str(x)


def texto_intervalos(a: Intervalos) -> str:
    """"entre 60 e 90 dias", "mais de 90 dias", várias partes ligadas por "ou"."""
    if not a:
        return "nenhum cliente"
    if a == ((0, INF),):
        return "qualquer tempo desde a última compra"
    return " ou ".join(
        f"mais de {_n(lo)} dias" if hi == INF else f"entre {_n(lo)} e {_n(hi)} dias" for lo, hi in a
    )


# ------------------------------------------------------------------------ condição de recência

_RE_RECENCIA = re.compile(
    r"(?P<fora>fora da )?recencia de (?P<tipo>positivacao|visita)(?: (?P<qual>global|do vendedor))? "
    r"(?:em (?P<n>\d+) dias?|entre (?P<a>\d+) dias? e (?P<b>\d+) dias?)"
)


@dataclass(frozen=True)
class AtomoRecencia:
    cadeia: str  # um valor de CADEIAS
    subtipo: str  # "global" | "simples" (positivação), para detectar mistura; "" nas demais
    intervalo: Intervalos


def interpretar_atomo(atomo: str) -> AtomoRecencia | None:
    """Condição atômica de recência (texto normalizado) -> cadeia e intervalo; None se não for recência."""
    m = _RE_RECENCIA.fullmatch(atomo)
    if not m:
        return None
    dentro = normalizar_intervalos([(0, int(m["n"]))] if m["n"] else [(int(m["a"]), int(m["b"]))])
    intervalo = complemento(dentro) if m["fora"] else dentro
    if m["tipo"] == "visita":
        return AtomoRecencia("visita", "", intervalo)
    if m["qual"] == "do vendedor":
        return AtomoRecencia("positivacao_vendedor", "", intervalo)
    return AtomoRecencia("positivacao", "global" if m["qual"] == "global" else "simples", intervalo)


def _classificar(p: Parametros) -> tuple[str, Intervalos, frozenset[str]] | None:
    """(cadeia, intervalo, subtipos) se o bloco for PURO de recência; None caso contrário."""
    if not p.quando or p.depende_do_calendario or any(c.conector == "ou" for c in p.quando):
        return None
    cadeia, intervalo, subtipos = None, ((0, INF),), set()
    for condicao in p.quando:
        for texto in separar_atomos(condicao.texto):
            atomo = interpretar_atomo(texto)
            if atomo is None or (cadeia not in (None, atomo.cadeia)):
                return None
            cadeia = atomo.cadeia
            intervalo = intersecao(intervalo, atomo.intervalo)
            subtipos.add(atomo.subtipo)
    return cadeia, intervalo, frozenset(subtipos)


# ------------------------------------------------------------------------- análise da cadeia


@dataclass(frozen=True)
class InfoRecencia:
    linha: int  # linha_ini do bloco
    nome: str
    puro: bool
    cadeia: str | None
    literal: str  # texto original do `quando` (linhas ligadas por " e ")
    intervalo: Intervalos | None  # intervalo do próprio bloco (só blocos puros)
    efetivo: Intervalos | None  # intervalo menos o já consumido pelos blocos puros anteriores
    texto_efetivo: str | None
    catch_all: bool
    texto_catch_all: str | None  # "mais de 90 dias"; None se houver lacuna ou não for possível afirmar
    lacunas: Intervalos
    notas: tuple[str, ...]


def _nota_precedentes(nomes: list[str]) -> str | None:
    nomes = list(dict.fromkeys(nomes))
    if not nomes:
        return None
    if len(nomes) == 1:
        return f"pode haver clientes já tratados pela regra {nomes[0]}"
    return "pode haver clientes já tratados pelas regras " + "; ".join(nomes)


def analisar_grupo(blocos: Sequence[Parametros]) -> list[InfoRecencia]:
    """Analisa, na ordem do arquivo, os blocos de UM mesmo (escopo, time)."""
    classes = [_classificar(p) for p in blocos]
    subtipos: dict[str, set[str]] = defaultdict(set)
    for c in classes:
        if c:
            subtipos[c[0]] |= c[2]
    misturadas = {cadeia for cadeia, s in subtipos.items() if {"global", "simples"} <= s}

    consumido: dict[str, Intervalos] = {}
    infos: list[InfoRecencia] = []
    for i, (p, classe) in enumerate(zip(blocos, classes)):
        literal = " e ".join(c.texto for c in p.quando)
        antes = list(zip(blocos[:i], classes[:i]))
        if classe:
            cadeia, intervalo, _ = classe
            efetivo = diferenca(intervalo, consumido.get(cadeia, ()))
            notas = []
            if nota := _nota_precedentes([b.nome for b, c in antes if not (c and c[0] == cadeia)]):
                notas.append(nota)
            if cadeia in misturadas:
                notas.append("mistura recência global e sem `global` na mesma cadeia (tratadas juntas)")
            if not efetivo:
                notas.append("sem clientes efetivos: o intervalo já foi tratado pelas regras anteriores da cadeia")
            consumido[cadeia] = uniao(consumido.get(cadeia, ()), intervalo)
            infos.append(
                InfoRecencia(p.linha_ini, p.nome, True, cadeia, literal, intervalo, efetivo,
                             texto_intervalos(efetivo), False, None, (), tuple(notas))
            )  # fmt: skip
        elif not p.quando:
            infos.append(_catch_all(p, antes, consumido))
        else:
            infos.append(InfoRecencia(p.linha_ini, p.nome, False, None, literal, None, None, None, False, None, (), ()))
    return infos


def _catch_all(p: Parametros, antes, consumido: dict[str, Intervalos]) -> InfoRecencia:
    ativas = [c for c in CADEIAS if consumido.get(c)]
    notas: list[str] = []
    texto, lacunas = None, ()
    if len(ativas) > 1:
        notas.append(f"cadeias de recência de tipos diferentes ({', '.join(ativas)}): efeito conjunto não calculado")
    elif ativas:
        cadeia = ativas[0]
        resto = complemento(consumido[cadeia])
        cauda = resto[-1] if resto and resto[-1][1] == INF else None
        lacunas = resto[:-1] if cauda else resto
        if not resto:
            notas.append("todas as recências já foram tratadas pelas regras anteriores da cadeia")
        elif lacunas:
            notas.append(f"lacuna na cadeia de recência: nenhum bloco cobre {texto_intervalos(lacunas)}")
        else:
            texto = f"mais de {_n(cauda[0])} dias"
        if nota := _nota_precedentes([b.nome for b, c in antes if not (c and c[0] == cadeia)]):
            notas.append(nota)
    return InfoRecencia(p.linha_ini, p.nome, False, None, "", None, None, None, True, texto, tuple(lacunas), tuple(notas))


# -------------------------------------------------------------------------- agrupamento


def chave_do_grupo(p: Parametros, time_da_carteira: dict[str, str] | None = None) -> tuple:
    """(escopo, time): escopo = tipos e nomes das linhas de escopo; time = nome do time, quando se sabe."""
    escopo = tuple((e.tipo, e.nomes) for e in p.escopos)
    times: list[str] = []
    for e in p.escopos:
        if e.tipo == "time":
            times.extend(e.nomes)
        elif e.tipo == "carteira" and time_da_carteira:
            times.extend(time_da_carteira[n] for n in e.nomes if n in time_da_carteira)
    return escopo, tuple(times)


def analisar_arquivo(arq: ArquivoGobr, time_da_carteira: dict[str, str] | None = None) -> dict[int, InfoRecencia]:
    """InfoRecencia de todos os blocos `parametros`, indexada pela linha_ini do bloco."""
    grupos: dict[tuple, list[Parametros]] = defaultdict(list)
    for p in arq.parametros:
        grupos[chave_do_grupo(p, time_da_carteira)].append(p)
    return {info.linha: info for blocos in grupos.values() for info in analisar_grupo(blocos)}
