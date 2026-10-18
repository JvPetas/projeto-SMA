"""Recência: intervalos em dias desde a última compra e o efeito da ORDEM dos blocos.

Cada bloco `parametros` só trata clientes que os blocos anteriores ainda não trataram. Em uma
cadeia como "recencia de positivacao em 60 dias" seguida de "... em 90 dias", o segundo bloco
vale, na prática, para clientes entre 60 e 90 dias.

Convenções internas de análise, sem afirmar as bordas na explicação:
- Intervalos usam os limites numéricos do código; condições ligadas por `e` = interseção.
  Faixas adjacentes em dias inteiros não deixam lacuna.
- Uma cadeia por (escopo, time). Chave da cadeia: positivação (`global` e sem `global` JUNTOS,
  com nota quando misturados) | positivação `do vendedor` | visita. Cadeias separadas.
- Só blocos PUROS (apenas recência da mesma cadeia, sem filtro temporal, sem `ou`) entram na
  união dos intervalos já consumidos. Um bloco `nao agendar` puro de recência conta (consome
  clientes). Bloco com outra condição ou filtro temporal não entra na união, e os blocos
  seguintes ganham a nota "pode haver clientes já tratados pela regra <nome>".
- O catch-all sai "mais de N dias" só se a cadeia cobrir [0, N] sem lacuna; com lacuna, a
  lacuna vai para as notas e nada mais é afirmado.
- Bordas só como "entre a e b": o manual diz "intervalo" e não define se a borda é inclusiva.
- A redução global/grupo serve à apresentação. Prova de sombreamento exige a mesma
  história; a implicação entre histórias é registrada separadamente como hipótese.
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace

from ..parsing.models import ArquivoGobr, Parametros
from .atomos import separar_atomos

INF = float("inf")
Intervalo = tuple[float, float]
Intervalos = tuple[Intervalo, ...]  # disjuntos, ordenados, sem bordas que se tocam

CADEIAS = ("positivacao", "positivacao_vendedor", "visita")
SOMBREAMENTO_PROVADO = "sem clientes efetivos (já cobertos pelas regras anteriores)"
SOMBREAMENTO_HIPOTESE = "sem clientes efetivos (sob a hipótese de que o grupo está contido na empresa)"
AVISO_MISTURA = "mistura recência global e sem `global` na mesma cadeia (tratadas juntas)"

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
    saida: list[Intervalo] = []
    for lo, hi in normalizar_intervalos(a + b):
        if saida and lo - saida[-1][1] <= 1:
            saida[-1] = (saida[-1][0], max(saida[-1][1], hi))
        else:
            saida.append((lo, hi))
    return tuple(saida)


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
    tipo: str = "positivacao"
    qualificador: str = "grupo"
    fora_em: int | None = None
    fora_entre: bool = False

    @property
    def historia(self) -> tuple[str, str]:
        return self.tipo, self.qualificador


def interpretar_atomo(atomo: str) -> AtomoRecencia | None:
    """Condição atômica de recência (texto normalizado) -> cadeia e intervalo; None se não for recência."""
    m = _RE_RECENCIA.fullmatch(atomo)
    if not m:
        return None
    dentro = normalizar_intervalos([(0, int(m["n"]))] if m["n"] else [(int(m["a"]), int(m["b"]))])
    intervalo = complemento(dentro) if m["fora"] else dentro
    qual = {None: "grupo", "global": "global", "do vendedor": "vendedor"}[m["qual"]]
    extras = (m["tipo"], qual, int(m["n"]) if m["fora"] and m["n"] else None, bool(m["fora"] and m["a"]))
    if m["tipo"] == "visita":
        return AtomoRecencia("visita", "", intervalo, *extras)
    if m["qual"] == "do vendedor":
        return AtomoRecencia("positivacao_vendedor", "", intervalo, *extras)
    return AtomoRecencia("positivacao", "global" if m["qual"] == "global" else "simples", intervalo, *extras)


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
    sombreamento_provado: bool = False
    sombreado_sob_hipotese: bool = False
    historia: tuple[str, str] | None = None
    antecedentes: tuple[str, ...] = ()
    fora_entre: bool = False
    bloqueios_anteriores: bool = False


def _atomos(p: Parametros) -> list[AtomoRecencia]:
    return [a for c in p.quando for t in separar_atomos(c.texto) if (a := interpretar_atomo(t))]


def _historia(p: Parametros) -> tuple[str, str] | None:
    historias = {a.historia for a in _atomos(p)}
    return next(iter(historias)) if len(historias) == 1 else None


def _sob_hipotese(p: Parametros, intervalo: Intervalos, antes) -> bool:
    historia = _historia(p)
    if not historia or not intervalo:
        return False
    ordem = {"global": 0, "grupo": 1, "vendedor": 2}
    for b, classe in antes:
        if not classe:
            continue
        aa = _atomos(b)
        if len(aa) != 1 or aa[0].fora_em is None:
            continue
        a = aa[0]
        if a.tipo != historia[0] or ordem[historia[1]] >= ordem[a.qualificador]:
            continue
        n = a.fora_em
        if all(lo > n or (lo == n and any(x.fora_em is not None and x.fora_em >= n for x in _atomos(p)))
               for lo, hi in intervalo):
            return True
    return False


def _nota_precedentes(nomes: list[str]) -> str | None:
    nomes = list(dict.fromkeys(nomes))
    if not nomes:
        return None
    if len(nomes) == 1:
        return f"pode haver clientes já tratados pela regra {nomes[0]}"
    return "pode haver clientes já tratados pelas regras " + "; ".join(nomes)


def _precedentes_impuros(p: Parametros, antes) -> tuple[str, ...]:
    cadeias = {a.cadeia for a in _atomos(p)}
    if not p.quando:
        cadeias = {a.cadeia for b, _ in antes for a in _atomos(b)}
    nomes = []
    for b, classe in antes:
        prospect = any(re.match(r"(?:no ciclo de vida prospects?|prospects?)(?: |$)", t)
                       for c in b.quando for t in separar_atomos(c.texto))
        if classe is None and not b.nao_agendar and not prospect and cadeias & {a.cadeia for a in _atomos(b)}:
            nomes.append(b.nome)
    return tuple(dict.fromkeys(nomes))


def analisar_grupo(blocos: Sequence[Parametros]) -> list[InfoRecencia]:
    """Analisa, na ordem do arquivo, os blocos de UM mesmo (escopo, time)."""
    classes = [_classificar(p) for p in blocos]
    subtipos: dict[str, set[str]] = defaultdict(set)
    for c in classes:
        if c:
            subtipos[c[0]] |= c[2]
    misturadas = {cadeia for cadeia, s in subtipos.items() if {"global", "simples"} <= s}

    consumido: dict[str, Intervalos] = {}
    consumido_historia: dict[tuple[str, str], Intervalos] = {}
    infos: list[InfoRecencia] = []
    for i, (p, classe) in enumerate(zip(blocos, classes)):
        literal = " e ".join(c.texto for c in p.quando)
        antes = list(zip(blocos[:i], classes[:i]))
        antecedentes = _precedentes_impuros(p, antes)
        historia = _historia(p)
        if classe:
            cadeia, intervalo, _ = classe
            efetivo = diferenca(intervalo, consumido.get(cadeia, ()))
            notas = []
            mesmo_historico = diferenca(intervalo, consumido_historia.get(historia, ()))
            provado = bool(historia and intervalo and not mesmo_historico)
            hipotese = not provado and _sob_hipotese(p, intervalo, antes)
            if not efetivo and not (provado or hipotese):
                efetivo = mesmo_historico
            if nota := _nota_precedentes(antecedentes):
                notas.append(nota)
            if cadeia in misturadas:
                notas.append(AVISO_MISTURA)
            if provado:
                notas.append(SOMBREAMENTO_PROVADO)
            elif hipotese:
                notas.append(SOMBREAMENTO_HIPOTESE)
            consumido[cadeia] = uniao(consumido.get(cadeia, ()), intervalo)
            if historia:
                consumido_historia[historia] = uniao(consumido_historia.get(historia, ()), intervalo)
            infos.append(
                InfoRecencia(p.linha_ini, p.nome, True, cadeia, literal, intervalo, efetivo,
                             texto_intervalos(efetivo), False, None, (), tuple(notas),
                             provado, hipotese, historia, antecedentes, any(a.fora_entre for a in _atomos(p)))
            )  # fmt: skip
        elif not p.quando:
            final = _catch_all(p, antes, consumido)
            if misturadas:
                final = replace(final, notas=(AVISO_MISTURA,) + final.notas)
            infos.append(final)
        else:
            infos.append(InfoRecencia(p.linha_ini, p.nome, False, None, literal, None, None, None, False, None, (), (),
                                      historia=historia, fora_entre=any(a.fora_entre for a in _atomos(p))))
        infos[-1] = replace(infos[-1], antecedentes=antecedentes,
                            bloqueios_anteriores=any(b.nao_agendar for b, _ in antes))
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
        lacunas = tuple((lo, hi) for lo, hi in (resto[:-1] if cauda else resto) if hi - lo > 1)
        if not resto:
            notas.append("todas as recências já foram tratadas pelas regras anteriores da cadeia")
        elif lacunas:
            notas.append(f"lacuna na cadeia de recência: nenhum bloco cobre {texto_intervalos(lacunas)}")
        elif cauda:
            texto = f"mais de {_n(cauda[0])} dias"
        if nota := _nota_precedentes(_precedentes_impuros(p, antes)):
            notas.append(nota)
    antecedentes = _precedentes_impuros(p, antes)
    return InfoRecencia(p.linha_ini, p.nome, False, None, "", None, None, None, True, texto, tuple(lacunas), tuple(notas),
                        antecedentes=antecedentes)


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
