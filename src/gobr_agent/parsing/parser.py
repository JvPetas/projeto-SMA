"""Parser dos arquivos .gobr (camadas 1 e 2).

Camada 1: divide o arquivo em blocos (time, segmentacao, carteira, parametros, ...).
Camada 2: interpreta as cláusulas de cada bloco (escopo, frequencia, preferencia, flags...).
Os filtros `quando` ficam como texto normalizado, sem interpretar a gramática.

O erro é por bloco, nunca por arquivo: o bloco com problema fica na lista, marcado
`incompleto`, e os demais blocos seguem normalmente. Nenhuma função pública levanta exceção.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from .models import (
    ArquivoGobr,
    Bloco,
    BlocoBruto,
    Carteira,
    Condicao,
    Escopo,
    FiltroTemporal,
    Frequencia,
    ItemPreferencia,
    LimparParametros,
    Parametros,
    Preferencia,
    Problema,
    Segmentacao,
    SemChoque,
    Time,
)
from .normalize import assinatura, balanco_parenteses, normalizar, remover_controles, tem_aspa_solta

# --------------------------------------------------------------------------- frequência

PERIODOS = {
    "diaria": 1,
    "semanal": 7,
    "quinzenal": 15,
    "mensal": 30,
    "bimestral": 60,
    "trimestral": 90,
    "semestral": 180,
    "anual": 365,
}
_PER = "|".join(PERIODOS)
_RE_PERIODO = re.compile(rf"({_PER})\((?:'([^']*)'|\"([^\"]*)\")?\)")
_RE_DIAS = re.compile(r"de (\d+) dias?")
_RE_DINAMICA = re.compile(
    r"(do govendas|do vendedor|do historico|de qualquer vendedor)(?: (mais|menos) (\d+) dias?)?"
)
_RE_ESTATISTICA = re.compile(r"de (ativos|inativos) (da empresa|do vendedor)")
_RE_LIMITE = re.compile(rf"no (minimo|maximo) (?:de (\d+) dias?|({_PER})\(\))")
_FONTES = {
    "do govendas": "govendas",
    "do vendedor": "vendedor",
    "do historico": "historico",
    "de qualquer vendedor": "qualquer_vendedor",
}


def _frequencia_primaria(texto: str) -> Frequencia | None:
    if m := _RE_DIAS.fullmatch(texto):
        return Frequencia(bruta=texto, tipo="dias", dias=int(m.group(1)))
    if m := _RE_PERIODO.fullmatch(texto):
        pivo = m.group(2) or m.group(3)
        return Frequencia(
            bruta=texto, tipo="periodo", periodo=m.group(1), dias=PERIODOS[m.group(1)], data_pivo=pivo
        )
    if m := _RE_DINAMICA.fullmatch(texto):
        ajuste = int(m.group(3)) if m.group(3) else 0
        if m.group(2) == "menos":
            ajuste = -ajuste
        return Frequencia(bruta=texto, tipo="dinamica", fonte=_FONTES[m.group(1)], ajuste_dias=ajuste)
    if m := _RE_ESTATISTICA.fullmatch(texto):
        quem = "empresa" if m.group(2) == "da empresa" else "vendedor"
        return Frequencia(bruta=texto, tipo="estatistica", estatistica=f"{m.group(1)}_{quem}")
    if texto == "remover":
        return Frequencia(bruta=texto, tipo="remover")
    return None


def _limites(texto: str) -> dict[str, int] | None:
    """`no minimo de N dias e no maximo semanal()` -> {"minimo": N, "maximo": 7}; None se sobrar texto."""
    achados = {}
    for m in _RE_LIMITE.finditer(texto):
        achados[m.group(1)] = int(m.group(2)) if m.group(2) else PERIODOS[m.group(3)]
    if not achados or not re.fullmatch(r"(\s*e\s*)*", _RE_LIMITE.sub("", texto)):
        return None
    return achados


def interpretar_frequencia(texto: str) -> Frequencia:
    """Interpreta o texto de uma cláusula `frequencia` (com ou sem a palavra-chave)."""
    t = re.sub(r"^frequencia\s*", "", normalizar(texto))
    partes = t.split(" ou ")
    primaria = _frequencia_primaria(partes[0])
    if primaria is None:
        return Frequencia(bruta=t)
    limites: dict[str, int] = {}
    alternativas = []
    for parte in partes[1:]:
        if parte.startswith(("no minimo", "no maximo")):
            achados = _limites(parte)
            if achados is None:
                return Frequencia(bruta=t)
            limites.update(achados)
        else:
            alternativa = _frequencia_primaria(parte)
            if alternativa is None:
                return Frequencia(bruta=t)
            alternativas.append(alternativa)
    return replace(
        primaria,
        bruta=t,
        minimo_dias=limites.get("minimo"),
        maximo_dias=limites.get("maximo"),
        alternativas=tuple(alternativas),
    )


# ------------------------------------------------------------------------- preferência

_DIAS_ABREV = {
    "segunda": "seg",
    "terca": "ter",
    "quarta": "qua",
    "quinta": "qui",
    "sexta": "sex",
    "sabado": "sab",
    "domingo": "dom",
}
_ORDEM_DIAS = tuple(_DIAS_ABREV.values())
_UTEIS = _ORDEM_DIAS[:5]
_RE_ITEM_PREF = re.compile(
    r"(?:(maior|normal|menor) )?(?:na|no|nos) (segunda|terca|quarta|quinta|sexta|sabado|domingo|dias uteis)(?:-feira)?"
)
_INTENSIDADE = {None: 2, "normal": 2, "maior": 3, "menor": 1}


def _preferencia_primaria(texto: str) -> Preferencia:
    if texto == "remover":
        return Preferencia(bruta=texto, remover=True)
    if texto in ("do vendedor", "do historico"):
        return Preferencia(bruta=texto, fonte=texto.split(" ")[1])
    itens = []
    for pedaco in texto.split(" e "):
        m = _RE_ITEM_PREF.fullmatch(pedaco)
        if not m:
            return Preferencia(bruta=texto, reconhecida=False)
        dia = "uteis" if m.group(2) == "dias uteis" else _DIAS_ABREV[m.group(2)]
        itens.append(ItemPreferencia(dia=dia, intensidade=_INTENSIDADE[m.group(1)]))
    dias = {d: 0 for d in _ORDEM_DIAS}
    for item in itens:
        for d in _UTEIS if item.dia == "uteis" else (item.dia,):
            dias[d] = max(dias[d], item.intensidade)
    return Preferencia(bruta=texto, itens=tuple(itens), dias=dias)


def interpretar_preferencia(texto: str) -> Preferencia:
    """Interpreta o texto de uma cláusula `preferencia` (com ou sem a palavra-chave)."""
    t = re.sub(r"^preferencia\s*", "", normalizar(texto))
    partes = t.split(" ou ")
    primaria = _preferencia_primaria(partes[0])
    alternativas = tuple(_preferencia_primaria(p) for p in partes[1:])
    if not primaria.reconhecida or not all(a.reconhecida for a in alternativas):
        return Preferencia(bruta=t, reconhecida=False)
    return replace(primaria, bruta=t, alternativas=alternativas)


# -------------------------------------------------------------- filtros temporais (cap. 5)

_FIM = r"(?= e |$)"  # o filtro termina no fim do texto ou antes do conector ` e `
_MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}  # fmt: skip
_ORDINAL_F = {"primeira": 1, "segunda": 2, "terceira": 3, "quarta": 4}
_ORDINAL_M = {"primeiro": 1, "segundo": 2, "terceiro": 3, "quarto": 4, "quinto": 5, "sexto": 6}
_HORA = r"['\"](\d{1,2}:\d{2})['\"]"
_DIAS_SEMANA = "segunda|terca|quarta|quinta|sexta|sabado|domingo"


def _dia_do_mes(forma: str, inicio, fim) -> dict:
    return {"forma": forma, "inicio": inicio, "fim": fim}


def _horario(forma: str, horarios=(), inicio=None, fim=None) -> dict:
    return {"forma": forma, "horarios": tuple(horarios), "inicio": inicio, "fim": fim}


# (categoria, regex, função que monta o `valor`). Da forma mais específica para a mais geral.
_FILTROS = [
    (cat, re.compile(rx + _FIM), valor)
    for cat, rx, valor in [
        ("dia_do_mes", r"no dia (\d+)", lambda m: _dia_do_mes("no_dia", int(m[1]), int(m[1]))),
        ("dia_do_mes", r"no ultimo dia do mes", lambda m: _dia_do_mes("ultimo_dia", "ultimo", "ultimo")),
        ("dia_do_mes", r"antes do dia (\d+)", lambda m: _dia_do_mes("antes_do_dia", 1, int(m[1]) - 1)),
        ("dia_do_mes", r"depois do dia (\d+)", lambda m: _dia_do_mes("depois_do_dia", int(m[1]) + 1, "ultimo")),
        ("dia_do_mes", r"a partir do dia (\d+)", lambda m: _dia_do_mes("a_partir_do_dia", int(m[1]), "ultimo")),
        ("dia_do_mes", r"entre os dias (\d+) e (\d+)", lambda m: _dia_do_mes("entre_os_dias", int(m[1]), int(m[2]))),
        ("dia_da_semana", r"todos os dias", lambda m: _ORDEM_DIAS),
        ("dia_da_semana", r"nos dias uteis", lambda m: _UTEIS),
        ("dia_da_semana", r"no fim de semana", lambda m: ("sab", "dom")),
        ("dia_da_semana", rf"(?:na|no) ({_DIAS_SEMANA})", lambda m: (_DIAS_ABREV[m[1]],)),
        ("semana_do_mes", r"na (primeira|segunda|terceira|quarta) semana", lambda m: _ORDINAL_F[m[1]]),
        ("semana_do_mes", r"na ultima semana", lambda m: "ultima"),
        ("quinzena", r"na (primeira|segunda) quinzena", lambda m: _ORDINAL_F[m[1]]),
        ("mes_do_ano", rf"em ({'|'.join(_MESES)})", lambda m: (_MESES[m[1]],)),
        ("mes_do_ano", r"no (primeiro|segundo|terceiro|quarto|quinto|sexto) bimestre",
         lambda m: tuple(range(2 * _ORDINAL_M[m[1]] - 1, 2 * _ORDINAL_M[m[1]] + 1))),
        ("mes_do_ano", r"no (primeiro|segundo|terceiro|quarto) trimestre",
         lambda m: tuple(range(3 * _ORDINAL_M[m[1]] - 2, 3 * _ORDINAL_M[m[1]] + 1))),
        ("mes_do_ano", r"no (primeiro|segundo) semestre",
         lambda m: tuple(range(6 * _ORDINAL_M[m[1]] - 5, 6 * _ORDINAL_M[m[1]] + 1))),
        ("horario", rf"as {_HORA}", lambda m: _horario("as", [m[1]])),
        ("horario", rf"de hora em hora entre {_HORA} e {_HORA}", lambda m: _horario("de_hora_em_hora", inicio=m[1], fim=m[2])),
        ("horario", rf"de hora em hora a partir de {_HORA}", lambda m: _horario("de_hora_em_hora", inicio=m[1])),
        ("horario", r"de hora em hora", lambda m: _horario("de_hora_em_hora")),
    ]
]  # fmt: skip

# Ordem em que o manual (5.1) manda escrever os filtros; semana do mês e quinzena ficam no mesmo nível.
_ORDEM_CANONICA = {"dia_do_mes": 0, "dia_da_semana": 1, "semana_do_mes": 2, "quinzena": 2, "mes_do_ano": 3, "horario": 4}


def interpretar_filtros_temporais(texto: str, linha: int = 0) -> tuple[FiltroTemporal, ...] | None:
    """Interpreta uma linha de filtros temporais (um ou vários, ligados por `e`).

    Um `e` na ponta (`no domingo e na segunda e`) é só o conector para a linha seguinte.
    Devolve None se qualquer parte do texto não for um filtro conhecido.
    """
    resto = re.sub(r" e$", "", re.sub(r"^e ", "", normalizar(texto)))
    filtros = []
    while resto:
        for categoria, regex, valor in _FILTROS:
            if m := regex.match(resto):
                break
        else:
            return None
        filtros.append(FiltroTemporal(categoria, m.group(0), valor(m), linha))
        resto = resto[m.end() :]
        if resto.startswith(" e "):
            resto = resto[3:]
    return tuple(filtros) or None


# ------------------------------------------------------------------------------ estrutura

_RE_ESCOPO = re.compile(r"(e )?(do time|da carteira|da segmentacao)\(")
_TIPO_ESCOPO = {"do time": "time", "da carteira": "carteira", "da segmentacao": "segmentacao"}
_RE_SEM_CHOQUE = re.compile(r"sem choque (?:no|na|na rota com) (time|carteira)\(")
_PALAVRAS_BLOCO = {"time", "segmentacao", "carteira", "parametros", "alerta", "tags"}
_INICIOS_CONTINUACAO = ('"', "'", ")", ",")


@dataclass
class _Segmento:
    tipo: str
    linha: int
    cabecalho: str
    corpo: list[tuple[int, str]]

    @property
    def linha_fim(self) -> int:
        return self.corpo[-1][0] if self.corpo else self.linha


@dataclass
class _Logica:
    """Linha lógica: linhas físicas de uma lista entre parênteses vêm coladas."""

    linha: int
    bruta: str
    norm: str


class _Ctx:
    def __init__(self, arq: ArquivoGobr):
        self.arq = arq

    def aviso(self, linha: int, mensagem: str, trecho: str = "") -> None:
        self.arq.avisos.append(Problema(self.arq.caminho, linha, mensagem, trecho[:120]))

    def erro(self, linha: int, mensagem: str, trecho: str = "") -> None:
        self.arq.erros.append(Problema(self.arq.caminho, linha, mensagem, trecho[:120]))


def _tipo_cabecalho(norm: str) -> str | None:
    if re.match(r"version\b", norm):
        return "version"
    if re.match(r"limpar parametros\b", norm):
        return "limpar"
    if re.match(r"carteira livre\b", norm):
        return "carteira_livre"
    primeira = norm.split(" ")[0].rstrip(":")
    return primeira if primeira in _PALAVRAS_BLOCO else None


def _segmentar(texto: str) -> tuple[list[_Segmento], list[tuple[int, str]]]:
    segmentos: list[_Segmento] = []
    soltas: list[tuple[int, str]] = []
    atual = None
    for n, bruta in enumerate(texto.splitlines(), 1):
        s = bruta.strip()
        if not s or s.startswith("#"):
            continue
        tipo = _tipo_cabecalho(normalizar(s))
        if tipo:
            atual = _Segmento(tipo, n, s, [])
            segmentos.append(atual)
        elif atual:
            atual.corpo.append((n, s))
        else:
            soltas.append((n, s))
    return segmentos, soltas


def _agrupar(corpo: list[tuple[int, str]], ctx: _Ctx) -> list[_Logica]:
    """Cola as linhas físicas de listas entre parênteses; parêntese aberto vira erro do bloco."""
    logicas: list[_Logica] = []
    i = 0
    while i < len(corpo):
        n, texto = corpo[i]
        partes = [texto]
        saldo, minimo = balanco_parenteses(texto)
        i += 1
        while saldo > 0 and i < len(corpo) and (
            corpo[i][1].startswith(_INICIOS_CONTINUACAO) or corpo[i][1][0].isdigit()
        ):
            s, m = balanco_parenteses(corpo[i][1])
            minimo = min(minimo, saldo + m)
            saldo += s
            partes.append(corpo[i][1])
            i += 1
        if saldo > 0:
            ctx.erro(n, "parêntese aberto sem fechar", texto)
        if minimo < 0:
            ctx.erro(n, "parêntese fechado sem abrir", texto)
        bruta = " ".join(partes)
        logicas.append(_Logica(n, bruta, normalizar(bruta)))
    return logicas


def _nome(seg: _Segmento, ctx: _Ctx) -> str:
    m = re.search(r'"(.*)"', seg.cabecalho)
    if not m:
        ctx.aviso(seg.linha, "cabeçalho sem nome entre aspas", seg.cabecalho)
    if not seg.cabecalho.endswith(":"):
        ctx.aviso(seg.linha, "cabeçalho sem ':' no fim", seg.cabecalho)
    return m.group(1) if m else ""


def _resto_bruto(logica: _Logica) -> str:
    partes = logica.bruta.split(None, 1)
    return partes[1].strip() if len(partes) > 1 else ""


def _escopo(logica: _Logica, m: re.Match) -> Escopo:
    return Escopo(
        tipo=_TIPO_ESCOPO[m.group(2)],
        nomes=tuple(re.findall(r'"([^"]*)"', logica.bruta)),
        ligador="e" if m.group(1) else None,
        linha=logica.linha,
    )


def _condicao(logica: _Logica, conector: str | None, texto: str) -> Condicao:
    return Condicao(conector, texto, assinatura(texto), logica.linha, logica.bruta)


def _sem_aspa_solta(logica: _Logica, ctx: _Ctx) -> str:
    if tem_aspa_solta(logica.bruta):
        ctx.aviso(logica.linha, "aspa solta removida", logica.bruta)
        return logica.norm.rstrip().removesuffix('"').rstrip()
    return logica.norm


def _nao_reconhecida(logica: _Logica, ctx: _Ctx, acumulador: list[tuple[int, str]]) -> None:
    acumulador.append((logica.linha, logica.bruta))
    ctx.aviso(logica.linha, "linha não reconhecida", logica.bruta)


def _parametros(seg: _Segmento, ctx: _Ctx, ordem: int) -> Parametros:
    erros_antes = len(ctx.arq.erros)
    nome = _nome(seg, ctx)
    escopos, quando, sem_choque, filtros_temporais, nao_rec = [], [], [], [], []
    freq_partes: list[str] | None = None
    pref_partes: list[str] | None = None
    freq_linha = pref_linha = 0
    fixo = roteirizavel = nao_agendar = False
    clausula = None
    for logica in _agrupar(seg.corpo, ctx):
        n = logica.norm
        primeira, _, resto = n.partition(" ")
        if m := _RE_ESCOPO.match(n):
            escopos.append(_escopo(logica, m))
            clausula = None
        elif primeira == "quando":
            quando.append(_condicao(logica, None, resto))
            clausula = "quando"
        elif primeira == "frequencia":
            if freq_partes is not None:
                ctx.aviso(logica.linha, "frequência repetida no bloco", logica.bruta)
            freq_partes, freq_linha = [_sem_aspa_solta(logica, ctx).partition(" ")[2]], logica.linha
            clausula = "frequencia"
        elif primeira == "preferencia":
            if pref_partes is not None:
                ctx.aviso(logica.linha, "preferência repetida no bloco", logica.bruta)
            pref_partes, pref_linha = [_sem_aspa_solta(logica, ctx).partition(" ")[2]], logica.linha
            clausula = "preferencia"
        elif n == "nao agendar":
            nao_agendar, clausula = True, None
        elif n == "fixo":
            fixo, clausula = True, None
        elif n == "roteirizavel":
            roteirizavel, clausula = True, None
        elif primeira == "sem" and (m := _RE_SEM_CHOQUE.match(n)):
            nomes = tuple(re.findall(r'"([^"]*)"', logica.bruta))
            sem_choque.append(SemChoque(m.group(1), nomes, logica.bruta, logica.linha))
            clausula = None
        elif clausula == "quando" and primeira in ("e", "ou"):
            quando.append(_condicao(logica, primeira, resto))
        elif clausula == "frequencia" and primeira == "ou":
            freq_partes.append(_sem_aspa_solta(logica, ctx))
        elif clausula == "preferencia" and (
            not any(pref_partes) or primeira in ("e", "ou", "maior", "normal", "menor")
        ):
            pref_partes.append(_sem_aspa_solta(logica, ctx))
        elif (filtros := interpretar_filtros_temporais(n, logica.linha)) is not None:
            filtros_temporais.extend(filtros)
            clausula = None
        else:
            _nao_reconhecida(logica, ctx, nao_rec)
            clausula = None

    frequencia = preferencia = None
    if freq_partes is not None:
        frequencia = interpretar_frequencia(" ".join(freq_partes))
        if not frequencia.reconhecida:
            ctx.aviso(freq_linha, "frequência não reconhecida", frequencia.bruta)
    if pref_partes is not None:
        preferencia = interpretar_preferencia(" ".join(pref_partes))
        if not preferencia.reconhecida:
            ctx.aviso(pref_linha, "preferência não reconhecida", preferencia.bruta)
    maior_nivel = -1
    for filtro in filtros_temporais:
        nivel = _ORDEM_CANONICA[filtro.categoria]
        if nivel < maior_nivel:
            ctx.aviso(filtro.linha, "filtros temporais fora da ordem canônica", " > ".join(f.categoria for f in filtros_temporais))
            break
        maior_nivel = max(maior_nivel, nivel)
    if any(f.categoria == "horario" for f in filtros_temporais):
        ctx.aviso(seg.linha, "filtro de horário em parametros (só vale para alertas)", nome)
    if nao_agendar and (frequencia or preferencia):
        ctx.aviso(seg.linha, "nao agendar combinado com frequência/preferência", nome)
    if not nao_agendar and frequencia is None:
        ctx.aviso(seg.linha, "parametros sem frequência nem nao agendar", nome)
    return Parametros(
        nome=nome,
        linha_ini=seg.linha,
        linha_fim=seg.linha_fim,
        incompleto=len(ctx.arq.erros) > erros_antes,
        nao_reconhecidas=tuple(nao_rec),
        ordem=ordem,
        escopos=tuple(escopos),
        quando=tuple(quando),
        frequencia=frequencia,
        preferencia=preferencia,
        fixo=fixo,
        roteirizavel=roteirizavel,
        nao_agendar=nao_agendar,
        sem_choque=tuple(sem_choque),
        filtros_temporais=tuple(filtros_temporais),
    )


def _limpar(seg: _Segmento, ctx: _Ctx, ordem: int) -> LimparParametros:
    erros_antes = len(ctx.arq.erros)
    nome = _nome(seg, ctx)
    escopos, nao_rec = [], []
    for logica in _agrupar(seg.corpo, ctx):
        if m := _RE_ESCOPO.match(logica.norm):
            escopos.append(_escopo(logica, m))
        else:
            _nao_reconhecida(logica, ctx, nao_rec)
    return LimparParametros(
        nome=nome,
        linha_ini=seg.linha,
        linha_fim=seg.linha_fim,
        incompleto=len(ctx.arq.erros) > erros_antes,
        nao_reconhecidas=tuple(nao_rec),
        ordem=ordem,
        escopos=tuple(escopos),
    )


def _time(seg: _Segmento, ctx: _Ctx) -> Time:
    erros_antes = len(ctx.arq.erros)
    nome = _nome(seg, ctx)
    vendedores, nao_rec = [], []
    for logica in _agrupar(seg.corpo, ctx):
        if logica.norm.partition(" ")[0] == "vendedores":
            vendedores.append(_resto_bruto(logica))
        else:
            _nao_reconhecida(logica, ctx, nao_rec)
    return Time(
        nome=nome,
        linha_ini=seg.linha,
        linha_fim=seg.linha_fim,
        incompleto=len(ctx.arq.erros) > erros_antes,
        nao_reconhecidas=tuple(nao_rec),
        vendedores=" ".join(vendedores),
    )


def _clientes_e_quando(seg: _Segmento, ctx: _Ctx):
    """Corpo comum de carteira e segmentacao: `clientes ...` e `quando ...` (com `e`/`ou`)."""
    clientes, quando, nao_rec = [], [], []
    clausula = None
    for logica in _agrupar(seg.corpo, ctx):
        primeira, _, resto = logica.norm.partition(" ")
        if primeira == "clientes":
            clientes.append(_resto_bruto(logica))
            clausula = None
        elif primeira == "quando":
            quando.append(_condicao(logica, None, resto))
            clausula = "quando"
        elif clausula == "quando" and primeira in ("e", "ou"):
            quando.append(_condicao(logica, primeira, resto))
        else:
            _nao_reconhecida(logica, ctx, nao_rec)
            clausula = None
    return tuple(clientes), tuple(quando), tuple(nao_rec)


def _carteira(seg: _Segmento, ctx: _Ctx) -> Carteira:
    erros_antes = len(ctx.arq.erros)
    nome = _nome(seg, ctx)
    clientes, quando, nao_rec = _clientes_e_quando(seg, ctx)
    return Carteira(
        nome=nome,
        linha_ini=seg.linha,
        linha_fim=seg.linha_fim,
        incompleto=len(ctx.arq.erros) > erros_antes,
        nao_reconhecidas=nao_rec,
        tipo="livre" if seg.tipo == "carteira_livre" else "exclusiva",
        clientes=clientes,
        quando=quando,
    )


def _segmentacao(seg: _Segmento, ctx: _Ctx) -> Segmentacao:
    erros_antes = len(ctx.arq.erros)
    nome = _nome(seg, ctx)
    clientes, quando, nao_rec = _clientes_e_quando(seg, ctx)
    return Segmentacao(
        nome=nome,
        linha_ini=seg.linha,
        linha_fim=seg.linha_fim,
        incompleto=len(ctx.arq.erros) > erros_antes,
        nao_reconhecidas=nao_rec,
        clientes=clientes,
        quando=quando,
    )


def _bruto(seg: _Segmento, ctx: _Ctx) -> BlocoBruto:
    ctx.aviso(seg.linha, "bloco alerta/tags não interpretado (fora das camadas 1 e 2)", seg.cabecalho)
    return BlocoBruto(
        nome=_nome(seg, ctx),
        linha_ini=seg.linha,
        linha_fim=seg.linha_fim,
        tipo=seg.tipo,
        linhas=tuple(t for _, t in seg.corpo),
    )


def _interpretar(seg: _Segmento, ctx: _Ctx, ordem: int) -> Bloco:
    if seg.tipo == "parametros":
        return _parametros(seg, ctx, ordem)
    if seg.tipo == "limpar":
        return _limpar(seg, ctx, ordem)
    if seg.tipo == "time":
        return _time(seg, ctx)
    if seg.tipo in ("carteira", "carteira_livre"):
        return _carteira(seg, ctx)
    if seg.tipo == "segmentacao":
        return _segmentacao(seg, ctx)
    return _bruto(seg, ctx)


def _parse(texto: str, arq: ArquivoGobr) -> None:
    ctx = _Ctx(arq)
    segmentos, soltas = _segmentar(texto)
    for n, s in soltas:
        ctx.aviso(n, "linha fora de bloco", s)
    ordem = 0
    for indice, seg in enumerate(segmentos):
        if seg.tipo == "version":
            m = re.match(r"version\s+(\S+)", seg.cabecalho, re.IGNORECASE)
            if arq.version is None:
                arq.version = m.group(1) if m else ""
                if arq.version != "1.0":
                    ctx.aviso(seg.linha, "version diferente de 1.0", seg.cabecalho)
            if indice != 0:
                ctx.aviso(seg.linha, "version fora do início do arquivo", seg.cabecalho)
            continue
        try:
            bloco = _interpretar(seg, ctx, ordem)
        except Exception as exc:  # um bloco com defeito não derruba o arquivo
            ctx.erro(seg.linha, "falha interna ao interpretar o bloco", f"{type(exc).__name__}: {exc}")
            bloco = BlocoBruto(
                nome="",
                linha_ini=seg.linha,
                linha_fim=seg.linha_fim,
                incompleto=True,
                tipo=seg.tipo,
                linhas=tuple(t for _, t in seg.corpo),
            )
        if isinstance(bloco, (Parametros, LimparParametros)):
            ordem += 1
        arq.blocos.append(bloco)
    if arq.version is None:
        ctx.aviso(1, "version 1.0 ausente")
    if not arq.times:
        ctx.aviso(1, "arquivo sem bloco time")


# ------------------------------------------------------------------------ API pública


def parse_text(texto: str, caminho: str = "<texto>") -> ArquivoGobr:
    arq = ArquivoGobr(caminho=caminho)
    for linha, bruta in enumerate(texto.split("\n"), 1):
        if remover_controles(bruta) != bruta:
            arq.avisos.append(Problema(caminho, linha, "caracteres de controle removidos", repr(bruta)[:120]))
    texto = remover_controles(texto)
    try:
        _parse(texto, arq)
    except Exception as exc:
        arq.erros.append(Problema(caminho, 0, "falha interna no parser", f"{type(exc).__name__}: {exc}"))
    return arq


def parse_file(caminho: str | Path) -> ArquivoGobr:
    caminho = Path(caminho)
    try:
        dados = caminho.read_bytes()
    except OSError as exc:
        arq = ArquivoGobr(caminho=caminho.name)
        arq.erros.append(Problema(caminho.name, 0, "arquivo ilegível", str(exc)))
        return arq
    try:
        texto, aviso = dados.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        texto, aviso = dados.decode("cp1252", errors="replace"), "arquivo não está em UTF-8 (lido como cp1252)"
    arq = parse_text(texto, caminho.name)
    if aviso:
        arq.avisos.insert(0, Problema(caminho.name, 0, aviso))
    return arq


def parse_dir(pasta: str | Path) -> list[ArquivoGobr]:
    return [parse_file(p) for p in sorted(Path(pasta).glob("*.gobr"))]
