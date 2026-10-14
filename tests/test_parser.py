"""Testes do parser GOBR (camadas 1 e 2)."""
import re
from pathlib import Path

import pytest

from gobr_agent.parsing import (
    interpretar_filtros_temporais,
    interpretar_frequencia,
    interpretar_preferencia,
    parse_file,
    parse_text,
)
from gobr_agent.parsing.models import BlocoBruto, Escopo, LimparParametros
from gobr_agent.parsing.normalize import normalizar

DATA = Path(__file__).resolve().parents[1] / "data" / "gobr"


def carregar(nome: str):
    caminho = DATA / nome
    if not caminho.exists():
        pytest.skip(f"{nome} não está em data/gobr")
    return parse_file(caminho)


def mensagens(problemas):
    return [p.mensagem for p in problemas]


def dias_das_frequencias(arq):
    return [p.frequencia.dias if p.frequencia else None for p in arq.parametros]


# ------------------------------------------------------------------ exemplos do professor


def test_exemplo_infinitto():
    arq = carregar("RegraInfinittoDesign.gobr")
    assert arq.version == "1.0"
    assert arq.erros == [] and arq.avisos == []
    assert [t.nome for t in arq.times] == ["televendas"]
    assert arq.times[0].vendedores == "todostelevendas ativados"
    ps = arq.parametros
    assert len(ps) == 5
    assert [p.ordem for p in ps] == [0, 1, 2, 3, 4]
    assert [p.nao_agendar for p in ps] == [True, False, False, False, False]
    assert dias_das_frequencias(arq) == [None, 7, 14, 7, 28]
    assert [p.catch_all for p in ps] == [False, False, False, False, True]
    assert all(p.escopos == (Escopo("time", ("televendas",), None, p.escopos[0].linha),) for p in ps)
    ativo = ps[2]
    assert ativo.quando[0].texto == "recencia de positivacao global em 60 dias"
    assert ativo.quando[0].assinatura == "recencia de positivacao global em N dias"
    assert ps[0].quando[0].texto == "status na receita federal definido como baixada"


def test_exemplo_maxlub():
    arq = carregar("RegraMaxlub.gobr")
    assert arq.version == "1.0"
    assert arq.erros == []
    ps = arq.parametros
    assert len(ps) == 10
    assert [p.nao_agendar for p in ps] == [True, True, True] + [False] * 6 + [True]
    assert dias_das_frequencias(arq) == [None, None, None, 14, 14, 7, 14, 21, 28, None]
    assert ps[2].escopos[0].nomes == ("televendas",)  # `do time ("televendas")`, com espaço
    assert ps[7].quando[0].texto == "recencia de positivacao em 150 dias"
    assert ps[9].catch_all and ps[9].nao_agendar
    assert ps[9].nome == "Clientes que não se enquadraram nas regras padrão"


def test_exemplo_v1_vidros_sem_version_vira_aviso():
    arq = carregar("V1Vidros-RegraComercial.gobr")
    assert arq.version is None
    assert arq.erros == []
    assert "version 1.0 ausente" in mensagens(arq.avisos)
    ps = arq.parametros
    assert len(ps) == 5
    assert dias_das_frequencias(arq) == [None, 14, 7, 14, 7]
    risco = ps[2]
    assert [(c.conector, c.texto) for c in risco.quando] == [
        (None, "recencia de positivacao em 45 dias"),
        ("e", "fora da recencia de positivacao em 30 dias"),
    ]
    assert risco.escopos[0].nomes == ("televendas",)


# --------------------------------------------------------------- arquivos com casos difíceis


def contar_parametros_no_texto(caminho: Path) -> int:
    texto = caminho.read_text(encoding="utf-8-sig").lower()
    return len(re.findall(r"^\s*parametros\b", texto, re.MULTILINE))


def test_regra_032_bloco_truncado_nao_derruba_o_arquivo():
    arq = carregar("regra_032.gobr")
    # o erro aponta a linha onde o parêntese abre (523); o bloco começa na 521
    assert [(e.linha, e.mensagem) for e in arq.erros] == [(523, "parêntese aberto sem fechar")]
    truncado = next(p for p in arq.parametros if p.linha_ini == 521)
    assert truncado.incompleto
    assert truncado.frequencia is None and not truncado.nao_agendar
    assert [b.linha_ini for b in arq.blocos if b.incompleto] == [521]
    ultimo = arq.parametros[-1]
    assert ultimo.linha_ini == 525 and ultimo.nao_agendar and ultimo.catch_all
    assert len(arq.parametros) == contar_parametros_no_texto(DATA / "regra_032.gobr")
    assert any(b.rotulo == "carteira livre" for b in arq.blocos)
    assert any(p.mensagem == "parametros sem frequência nem nao agendar" and p.linha == 521 for p in arq.avisos)


def test_regra_047_cabecalho_com_recuo_irregular():
    arq = carregar("regra_047.gobr")
    bloco = next(p for p in arq.parametros if p.linha_ini == 10)
    assert bloco.nome.endswith("nao agendar CPF")
    assert bloco.nao_agendar
    assert bloco.quando[0].texto == "pessoa fisica"
    assert bloco.escopos[0].tipo == "carteira" and bloco.escopos[0].nomes == ("regra padrao",)
    assert len(arq.parametros) == contar_parametros_no_texto(DATA / "regra_047.gobr")


def test_regra_169_escopo_de_segmentacao_e_carteira():
    arq = carregar("regra_169.gobr")
    por_linha = {p.linha_ini: p for p in arq.parametros}
    for linha in (30, 37, 44, 51, 57):
        bloco = por_linha[linha]
        assert [(e.tipo, e.nomes, e.ligador) for e in bloco.escopos] == [
            ("segmentacao", ("televendas ruptura de fornecedor",), None),
            ("carteira", ("televendas consumidor",), "e"),
        ]
        assert bloco.frequencia.dias == 14
    assert por_linha[73].catch_all and por_linha[73].nao_agendar
    assert por_linha[77].escopos[0].nomes == ("televendas_2",)
    assert arq.segmentacoes and arq.carteiras


# ------------------------------------------------------------------------ casos sintéticos

BASE = 'version 1.0\n\ntime "t":\n    vendedores todos\n\n'


def test_parentese_aberto_isola_o_erro_no_bloco():
    texto = BASE + (
        'parametros "A":\n'
        '    do time("t")\n'
        '    quando ramo de atividade igual("X"\n'
        "    frequencia de 7 dias\n"
        "\n"
        'parametros "B":\n'
        '    do time("t")\n'
        "    frequencia de 14 dias\n"
    )
    arq = parse_text(texto)
    a, b = arq.parametros
    assert [(e.linha, e.mensagem) for e in arq.erros] == [(8, "parêntese aberto sem fechar")]
    assert a.incompleto and not b.incompleto
    assert a.frequencia.dias == 7  # o resto do bloco com defeito foi aproveitado
    assert b.frequencia.dias == 14


def test_parentese_fechado_sem_abrir():
    arq = parse_text(BASE + 'parametros "A":\n    do time("t")\n    quando sem venda)\n    frequencia de 7 dias\n')
    assert mensagens(arq.erros) == ["parêntese fechado sem abrir"]


def test_parenteses_dentro_de_aspas_nao_contam():
    arq = parse_text(BASE + 'parametros "A (":\n    do time("t")\n    quando nome igual("Mogi (Norte")\n    frequencia de 7 dias\n')
    assert arq.erros == []


def test_lista_entre_parenteses_em_varias_linhas_vira_uma_condicao():
    texto = BASE + (
        'carteira "c":\n'
        '    clientes carteirafixa("t")\n'
        "    quando nome da cidade igual(\n"
        '        "A","B",\n'
        '        "C"\n'
        "    )\n"
        "    e adimplentes\n"
    )
    arq = parse_text(texto)
    carteira = arq.carteiras[0]
    assert arq.erros == []
    assert carteira.tipo == "exclusiva"
    assert [(c.conector, c.texto) for c in carteira.quando] == [
        (None, 'nome da cidade igual("a","b","c")'),
        ("e", "adimplentes"),
    ]
    assert carteira.clientes == ('carteirafixa("t")',)


def test_carteira_livre():
    arq = parse_text(BASE + 'carteira livre "l":\n    clientes carteirafixa("t")\n')
    assert arq.carteiras[0].tipo == "livre"


def test_normalizacao_de_acentos_e_espacos():
    assert normalizar('do time ("X")') == normalizar('do time("X")') == 'do time("x")'
    assert normalizar("frequência  de 7 dias") == "frequencia de 7 dias"
    assert normalizar('vendedores porid ("1", "2")') == 'vendedores porid("1","2")'
    arq = parse_text(BASE + 'parametros "A":\n    do time ("Time Campo")\n    frequência de 7 dias\n    não agendar\n')
    p = arq.parametros[0]
    assert p.escopos[0].nomes == ("Time Campo",)
    assert p.frequencia.dias == 7 and p.nao_agendar


def test_clausulas_com_recuo_irregular():
    arq = parse_text(
        BASE + 'parametros "A":\n    do time("t")\n    frequencia de 21 dias\n        preferencia nos dias uteis e no sabado\n'
    )
    p = arq.parametros[0]
    assert p.frequencia.dias == 21 and p.frequencia.alternativas == ()
    assert p.preferencia.dias == {"seg": 2, "ter": 2, "qua": 2, "qui": 2, "sex": 2, "sab": 2, "dom": 0}


def test_aspa_solta_e_removida_com_aviso():
    arq = parse_text(BASE + 'parametros "A":\n    do time("t")\n    frequencia de 7 dias\n    preferencia nos dias uteis e no sabado"\n')
    assert "aspa solta removida" in mensagens(arq.avisos)
    assert arq.parametros[0].preferencia.reconhecida


def test_filtros_temporais_soltos_sem_aviso_e_sem_virar_preferencia():
    arq = parse_text(
        BASE + 'parametros "A":\n    do time("t")\n    a partir do dia 16\n    na segunda\n    frequencia de 7 dias\n'
    )
    p = arq.parametros[0]
    assert [(f.categoria, f.bruta) for f in p.filtros_temporais] == [
        ("dia_do_mes", "a partir do dia 16"),
        ("dia_da_semana", "na segunda"),
    ]
    assert [f.linha for f in p.filtros_temporais] == [8, 9]
    assert p.preferencia is None and p.depende_do_calendario
    assert arq.avisos == []


def test_linha_desconhecida_vira_aviso():
    arq = parse_text(BASE + 'parametros "A":\n    do time("t")\n    foo bar\n    frequencia de 7 dias\n')
    assert mensagens(arq.avisos) == ["linha não reconhecida"]
    assert arq.parametros[0].nao_reconhecidas == ((8, "foo bar"),)


def test_sem_choque_fixo_e_roteirizavel():
    texto = BASE + (
        'parametros "A":\n    do time("t")\n    frequencia de 7 dias\n'
        '    sem choque no time("time campo")\n    sem choque na rota com time("campo")\n'
        '    sem choque na carteira("c1","c2")\n    roteirizavel\n    fixo\n'
    )
    p = parse_text(texto).parametros[0]
    assert [(s.alvo, s.nomes) for s in p.sem_choque] == [
        ("time", ("time campo",)),
        ("time", ("campo",)),
        ("carteira", ("c1", "c2")),
    ]
    assert p.fixo and p.roteirizavel
    p2 = parse_text(BASE + 'parametros "B":\n    do time("t")\n    frequencia de 7 dias\n').parametros[0]
    assert not p2.fixo and not p2.roteirizavel


def test_avisos_de_estrutura():
    arq = parse_text('version 2.0\nparametros "A":\n    do time("t")\n    nao agendar\n')
    assert mensagens(arq.avisos) == ["version diferente de 1.0", "arquivo sem bloco time"]
    assert arq.version == "2.0"


def test_nao_agendar_exclusivo_gera_aviso():
    arq = parse_text(BASE + 'parametros "A":\n    do time("t")\n    nao agendar\n    frequencia de 7 dias\n')
    assert "nao agendar combinado com frequência/preferência" in mensagens(arq.avisos)


def test_preferencia_com_intensidade_em_varias_linhas():
    texto = BASE + (
        'parametros "A":\n    do time("t")\n    frequencia semanal()\n'
        "    preferencia\n        normal na segunda e\n        normal na quarta e\n        menor na sexta\n"
        'parametros "B":\n    do time("t")\n    frequencia diaria()\n'
        "    preferencia maior na segunda\n        e maior na terca\n        e na quinta\n"
    )
    a, b = parse_text(texto).parametros
    assert a.preferencia.dias == {"seg": 2, "ter": 0, "qua": 2, "qui": 0, "sex": 1, "sab": 0, "dom": 0}
    assert [(i.dia, i.intensidade) for i in b.preferencia.itens] == [("seg", 3), ("ter", 3), ("qui", 2)]
    assert b.preferencia.dias["seg"] == 3 and b.preferencia.dias["qui"] == 2


# ------------------------------------------------- formas que só existem no manual (7.3 a 7.5)
# As strings abaixo foram copiadas do texto do manual (govendas-rules.pdf, pp. 43-49).


@pytest.mark.parametrize(
    "texto, periodo, dias",
    [
        ("diaria()", "diaria", 1),
        ("semanal()", "semanal", 7),
        ("quinzenal()", "quinzenal", 15),
        ("mensal()", "mensal", 30),
        ("bimestral()", "bimestral", 60),
        ("trimestral()", "trimestral", 90),
        ("semestral()", "semestral", 180),
        ("anual()", "anual", 365),
    ],
)
def test_manual_frequencia_fixa_por_periodo(texto, periodo, dias):
    f = interpretar_frequencia(texto)
    assert (f.tipo, f.periodo, f.dias, f.data_pivo) == ("periodo", periodo, dias, None)


@pytest.mark.parametrize(
    "texto, periodo, dias",
    [("quinzenal('dd-mm-yyyy')", "quinzenal", 15), ("bimestral('dd-mm-yyyy')", "bimestral", 60)],
)
def test_manual_frequencia_com_data_pivo(texto, periodo, dias):
    f = interpretar_frequencia(texto)
    assert (f.tipo, f.periodo, f.dias, f.data_pivo) == ("periodo", periodo, dias, "dd-mm-yyyy")


def test_manual_frequencia_de_n_dias():
    f = interpretar_frequencia("de 10 dias")
    assert (f.tipo, f.dias) == ("dias", 10)


@pytest.mark.parametrize(
    "texto, fonte, ajuste",
    [
        ("do govendas", "govendas", 0),
        ("do vendedor", "vendedor", 0),
        ("do vendedor menos 5 dias", "vendedor", -5),
        ("do vendedor mais 5 dias", "vendedor", 5),
        ("do historico", "historico", 0),
        ("de qualquer vendedor", "qualquer_vendedor", 0),
    ],
)
def test_manual_frequencia_dinamica(texto, fonte, ajuste):
    f = interpretar_frequencia(texto)
    assert (f.tipo, f.fonte, f.ajuste_dias, f.dias) == ("dinamica", fonte, ajuste, None)


@pytest.mark.parametrize(
    "texto, estatistica",
    [
        ("de ativos da empresa", "ativos_empresa"),
        ("de inativos da empresa", "inativos_empresa"),
        ("de ativos do vendedor", "ativos_vendedor"),
        ("de inativos do vendedor", "inativos_vendedor"),
    ],
)
def test_manual_frequencia_estatistica(texto, estatistica):
    f = interpretar_frequencia(texto)
    assert (f.tipo, f.estatistica) == ("estatistica", estatistica)


def test_manual_frequencia_remover():
    assert interpretar_frequencia("remover").tipo == "remover"


def test_manual_frequencia_com_alternativas():
    f = interpretar_frequencia("frequencia do vendedor ou de 35 dias")
    assert (f.fonte, [(a.tipo, a.dias) for a in f.alternativas]) == ("vendedor", [("dias", 35)])
    g = interpretar_frequencia("frequencia do vendedor ou de qualquer vendedor ou de 35 dias")
    assert [(a.tipo, a.fonte, a.dias) for a in g.alternativas] == [
        ("dinamica", "qualquer_vendedor", None),
        ("dias", None, 35),
    ]


def test_manual_modificadores_de_limite_aceitam_periodos():
    maximo = interpretar_frequencia("do historico ou no máximo semanal()")
    assert (maximo.fonte, maximo.maximo_dias, maximo.minimo_dias, maximo.alternativas) == ("historico", 7, None, ())
    minimo = interpretar_frequencia("do historico ou no mínimo mensal()")
    assert (minimo.minimo_dias, minimo.maximo_dias) == (30, None)
    ambos = interpretar_frequencia("do historico mais 3 dias ou no minimo de 7 dias e no maximo de 30 dias")
    assert (ambos.ajuste_dias, ambos.minimo_dias, ambos.maximo_dias) == (3, 7, 30)


def test_frequencia_desconhecida_nao_levanta():
    f = interpretar_frequencia("a cada lua cheia")
    assert not f.reconhecida and f.tipo is None


def test_manual_preferencias():
    historico = interpretar_preferencia("preferência do historico ou remover")
    assert (historico.fonte, historico.dias, [a.remover for a in historico.alternativas]) == ("historico", None, [True])
    mista = interpretar_preferencia("preferência do historico ou nos dias uteis")
    assert mista.fonte == "historico" and mista.dias is None
    assert mista.alternativas[0].dias["sex"] == 2 and mista.alternativas[0].dias["sab"] == 0
    dias = interpretar_preferencia("preferencia na segunda e na terça")
    assert dias.dias == {"seg": 2, "ter": 2, "qua": 0, "qui": 0, "sex": 0, "sab": 0, "dom": 0}
    uteis = interpretar_preferencia("preferência nos dias úteis")
    assert [(i.dia, i.intensidade) for i in uteis.itens] == [("uteis", 2)]
    assert interpretar_preferencia("preferência do vendedor").fonte == "vendedor"


def test_manual_exemplo_7_3_10_roteirizavel_fixo():
    texto = (
        'parametros "campo roteirizavel fixo":\n'
        'da carteira("carteira campo")\n'
        "quando inatividade de 90 dias\n"
        "frequencia do vendedor ou de 35 dias\n"
        "preferência do historico ou nos dias uteis\n"
        "roteirizavel\n"
        "fixo\n"
    )
    p = parse_text(BASE + texto).parametros[0]
    assert p.roteirizavel and p.fixo
    assert p.escopos[0].tipo == "carteira" and p.escopos[0].nomes == ("carteira campo",)
    assert p.frequencia.fonte == "vendedor" and p.frequencia.alternativas[0].dias == 35
    assert p.preferencia.fonte == "historico" and p.preferencia.alternativas[0].dias is not None
    assert p.quando[0].texto == "inatividade de 90 dias"


def test_manual_exemplo_7_3_11_limpar_parametros():
    arq = parse_text(BASE + 'limpar parametros "remover parametrizacao":\nda carteira("carteira fixa")\n')
    limpeza = arq.blocos[-1]
    assert isinstance(limpeza, LimparParametros)
    assert limpeza.escopos[0].nomes == ("carteira fixa",)
    assert arq.erros == []


def test_manual_exemplo_8_2_alerta_fica_como_bloco_bruto():
    texto = (
        'alerta "Whatsapp: Ruptura de positivação na agenda de hoje":\n'
        '    do time("campo e televendas")\n'
        "    nos dias uteis e de hora em hora a partir de '07:00'\n"
        "    quando ativos para o vendedor\n"
    )
    arq = parse_text(BASE + texto)
    alerta = arq.blocos[-1]
    assert isinstance(alerta, BlocoBruto) and alerta.tipo == "alerta"
    assert arq.erros == []
    assert any("alerta/tags" in m for m in mensagens(arq.avisos))


# ----------------------------------- filtros temporais (manual, cap. 5, tabelas 5.2 a 5.6)
# As strings abaixo foram copiadas das tabelas do manual (govendas-rules.pdf, pp. 22-25).

TODOS_OS_DIAS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")


def um_filtro(texto):
    filtros = interpretar_filtros_temporais(texto)
    assert filtros is not None and len(filtros) == 1, texto
    return filtros[0]


@pytest.mark.parametrize(
    "texto, forma, inicio, fim",
    [
        ("no dia 10", "no_dia", 10, 10),
        ("no ultimo dia do mês", "ultimo_dia", "ultimo", "ultimo"),
        ("antes do dia 20", "antes_do_dia", 1, 19),  # "Apenas entre os dias 1 e 19 do mês"
        ("depois do dia 15", "depois_do_dia", 16, "ultimo"),  # "entre os dias 16 e o último dia do mês"
        ("a partir do dia 12", "a_partir_do_dia", 12, "ultimo"),
        ("entre os dias 12 e 30", "entre_os_dias", 12, 30),
    ],
)
def test_manual_5_2_dia_do_mes(texto, forma, inicio, fim):
    f = um_filtro(texto)
    assert f.categoria == "dia_do_mes"
    assert f.valor == {"forma": forma, "inicio": inicio, "fim": fim}


@pytest.mark.parametrize(
    "texto, dias",
    [
        ("na segunda", ("seg",)),
        ("na terça", ("ter",)),
        ("na quarta", ("qua",)),
        ("na quinta", ("qui",)),
        ("na sexta", ("sex",)),
        ("no sabado", ("sab",)),
        ("no domingo", ("dom",)),
        ("todos os dias", TODOS_OS_DIAS),
        ("nos dias uteis", ("seg", "ter", "qua", "qui", "sex")),
        ("no fim de semana", ("sab", "dom")),
    ],
)
def test_manual_5_3_dia_da_semana(texto, dias):
    f = um_filtro(texto)
    assert (f.categoria, f.valor) == ("dia_da_semana", dias)


@pytest.mark.parametrize(
    "texto, categoria, valor",
    [
        ("na primeira semana", "semana_do_mes", 1),
        ("na segunda semana", "semana_do_mes", 2),
        ("na terceira semana", "semana_do_mes", 3),
        ("na quarta semana", "semana_do_mes", 4),
        ("na ultima semana", "semana_do_mes", "ultima"),
        ("na primeira quinzena", "quinzena", 1),
        ("na segunda quinzena", "quinzena", 2),
    ],
)
def test_manual_5_4_semana_e_quinzena(texto, categoria, valor):
    f = um_filtro(texto)  # `na segunda semana` não pode virar `na segunda` + resto
    assert (f.categoria, f.valor) == (categoria, valor)


@pytest.mark.parametrize(
    "texto, meses",
    [
        ("em janeiro", (1,)),
        ("em fevereiro", (2,)),
        ("em março", (3,)),
        ("em dezembro", (12,)),
        ("no primeiro bimestre", (1, 2)),
        ("no segundo bimestre", (3, 4)),
        ("no terceiro bimestre", (5, 6)),
        ("no quarto bimestre", (7, 8)),
        ("no quinto bimestre", (9, 10)),
        ("no sexto bimestre", (11, 12)),
        ("no primeiro trimestre", (1, 2, 3)),
        ("no segundo trimestre", (4, 5, 6)),
        ("no terceiro trimestre", (7, 8, 9)),
        ("no quarto trimestre", (10, 11, 12)),
        ("no primeiro semestre", (1, 2, 3, 4, 5, 6)),
        ("no segundo semestre", (7, 8, 9, 10, 11, 12)),
    ],
)
def test_manual_5_5_mes_do_ano(texto, meses):
    f = um_filtro(texto)
    assert (f.categoria, f.valor) == ("mes_do_ano", meses)


@pytest.mark.parametrize(
    "texto, valor",
    [
        ("às '15:00'", {"forma": "as", "horarios": ("15:00",), "inicio": None, "fim": None}),
        ("de hora em hora", {"forma": "de_hora_em_hora", "horarios": (), "inicio": None, "fim": None}),
        ("de hora em hora entre '08:00' e '18:00'", {"forma": "de_hora_em_hora", "horarios": (), "inicio": "08:00", "fim": "18:00"}),
        ("de hora em hora a partir de '07:00'", {"forma": "de_hora_em_hora", "horarios": (), "inicio": "07:00", "fim": None}),
    ],
)
def test_manual_5_6_horario(texto, valor):
    f = um_filtro(texto)
    assert (f.categoria, f.valor) == ("horario", valor)


def test_manual_5_6_varios_horarios_especificos():
    filtros = interpretar_filtros_temporais("às '15:00' e às '16:30'")
    assert [(f.categoria, f.valor["horarios"]) for f in filtros] == [("horario", ("15:00",)), ("horario", ("16:30",))]


def test_filtros_combinados_na_mesma_linha_nao_quebram_no_e_interno():
    filtros = interpretar_filtros_temporais("entre os dias 12 e 30 e na segunda e na primeira quinzena")
    assert [f.categoria for f in filtros] == ["dia_do_mes", "dia_da_semana", "quinzena"]
    assert filtros[0].valor["fim"] == 30
    filtros = interpretar_filtros_temporais("nos dias uteis e de hora em hora a partir de '07:00'")  # manual 5.1
    assert [f.categoria for f in filtros] == ["dia_da_semana", "horario"]


def test_filtro_desconhecido_devolve_none():
    assert interpretar_filtros_temporais("na proxima semana") is None
    assert interpretar_filtros_temporais("na segunda e na proxima semana") is None
    assert interpretar_filtros_temporais("adimplentes") is None


def test_manual_5_1_filtros_em_varias_linhas_com_e_no_fim():
    texto = BASE + (
        'parametros "filtros":\n'
        'da carteira("televendas")\n'
        "no dia 2 e no dia 12 e\n"
        "no domingo e na segunda e\n"
        "na primeira semana e\n"
        "no segundo semestre\n"
        "frequencia semanal()\n"
    )
    arq = parse_text(texto)
    p = arq.parametros[0]
    assert [f.categoria for f in p.filtros_temporais] == [
        "dia_do_mes", "dia_do_mes", "dia_da_semana", "dia_da_semana", "semana_do_mes", "mes_do_ano",
    ]  # fmt: skip
    assert [f.valor for f in p.filtros_temporais][4:] == [1, (7, 8, 9, 10, 11, 12)]
    assert p.depende_do_calendario
    assert arq.avisos == [] and arq.erros == []


def test_manual_7_3_7_nos_dias_uteis_nao_e_preferencia():
    texto = BASE + (
        'parametros "semanal dias uteis":\n'
        'da carteira("carteira fixa")\n'
        "nos dias úteis\n"
        "quando inatividade de 90 dias\n"
        "frequencia semanal()\n"
        "preferencia na segunda e na terça\n"
    )
    p = parse_text(texto).parametros[0]
    assert [(f.categoria, f.valor) for f in p.filtros_temporais] == [("dia_da_semana", ("seg", "ter", "qua", "qui", "sex"))]
    assert p.preferencia.dias == {"seg": 2, "ter": 2, "qua": 0, "qui": 0, "sex": 0, "sab": 0, "dom": 0}


def test_fora_da_ordem_canonica_e_aviso_nao_erro():
    arq = parse_text(
        BASE + 'parametros "A":\n    do time("t")\n    na segunda\n    no dia 2\n    frequencia de 7 dias\n'
    )
    assert arq.erros == []
    assert mensagens(arq.avisos) == ["filtros temporais fora da ordem canônica"]
    assert arq.avisos[0].linha == 9
    assert [f.categoria for f in arq.parametros[0].filtros_temporais] == ["dia_da_semana", "dia_do_mes"]
    em_ordem = parse_text(BASE + 'parametros "B":\n    do time("t")\n    no dia 2 e na segunda e em maio\n    frequencia de 7 dias\n')
    assert em_ordem.avisos == []


def test_horario_em_parametros_gera_aviso():
    arq = parse_text(BASE + 'parametros "A":\n    do time("t")\n    de hora em hora\n    frequencia de 7 dias\n')
    assert mensagens(arq.avisos) == ["filtro de horário em parametros (só vale para alertas)"]


def test_filtro_desconhecido_no_bloco_vira_linha_nao_reconhecida():
    arq = parse_text(BASE + 'parametros "A":\n    do time("t")\n    na proxima semana\n    frequencia de 7 dias\n')
    assert mensagens(arq.avisos) == ["linha não reconhecida"]
    assert not arq.parametros[0].depende_do_calendario


def test_sem_filtro_nao_depende_do_calendario():
    p = parse_text(BASE + 'parametros "A":\n    do time("t")\n    frequencia de 7 dias\n').parametros[0]
    assert p.filtros_temporais == () and not p.depende_do_calendario


def test_filtros_temporais_dos_11_casos_reais():
    esperado = {
        "regra_128.gobr": {
            linha: ("dia_do_mes", {"forma": "a_partir_do_dia", "inicio": 16, "fim": "ultimo"})
            for linha in (88, 112, 136, 160, 184, 208)
        },
        "regra_151.gobr": {23: ("semana_do_mes", "ultima")},
        "regra_168.gobr": {
            86: ("dia_da_semana", ("seg",)),
            95: ("dia_da_semana", ("ter",)),
            103: ("dia_da_semana", ("qua",)),
            111: ("dia_da_semana", ("qui",)),
        },
    }
    for nome, filtros in esperado.items():
        arq = carregar(nome)
        obtidos = {f.linha: (f.categoria, f.valor) for p in arq.parametros for f in p.filtros_temporais}
        assert obtidos == filtros, nome
        assert sum(p.depende_do_calendario for p in arq.parametros) == len(filtros), nome
        assert arq.avisos == [] and arq.erros == [], nome
    # em regra_168 o dia do filtro e o dia da preferência coincidem, mas são campos separados
    arq = carregar("regra_168.gobr")
    por_linha = {p.linha_ini: p for p in arq.parametros}
    for linha, dia in ((84, "seg"), (93, "ter"), (101, "qua"), (109, "qui")):
        bloco = por_linha[linha]
        assert bloco.preferencia.dias[dia] == 3 and sum(bloco.preferencia.dias.values()) == 3
        assert bloco.frequencia.periodo == "diaria" and bloco.roteirizavel and bloco.fixo


# ------------------------------------------------------------------ todos os arquivos de data/gobr

ARQUIVOS = sorted(DATA.glob("*.gobr")) if DATA.exists() else []

PADROES = {
    "parametros": r"^\s*parametros\b",
    "time": r"^\s*time\b",
    "carteira livre": r"^\s*carteira\s+livre\b",
    "carteira exclusiva": r"^\s*carteira\b(?!\s+livre\b)",
    "segmentacao": r"^\s*segmentacao\b",
}


@pytest.mark.skipif(not ARQUIVOS, reason="data/gobr vazia")
def test_todos_os_arquivos_sem_excecao_e_com_todos_os_blocos(capsys):
    resultados = {}
    for caminho in ARQUIVOS:
        arq = parse_file(caminho)  # qualquer exceção reprovaria o teste
        resultados[caminho.name] = arq
        assert "falha interna" not in " ".join(mensagens(arq.erros)), caminho.name
        texto = caminho.read_text(encoding="utf-8-sig").lower()
        for rotulo, padrao in PADROES.items():
            esperado = len(re.findall(padrao, texto, re.MULTILINE))
            obtido = sum(1 for b in arq.blocos if b.rotulo == rotulo)
            assert obtido == esperado, f"{caminho.name}: {rotulo} {obtido} != {esperado}"

    com_filtros = {n: sum(len(p.filtros_temporais) for p in a.parametros) for n, a in resultados.items()}
    com_filtros = {n: k for n, k in com_filtros.items() if k}
    blocos_calendario = sum(p.depende_do_calendario for a in resultados.values() for p in a.parametros)
    nao_reconhecidas = {n: sum(len(b.nao_reconhecidas) for b in a.blocos) for n, a in resultados.items()}
    nao_reconhecidas = {n: k for n, k in nao_reconhecidas.items() if k}
    with capsys.disabled():
        print(f"\n[{len(resultados)} arquivos] filtros temporais: {len(com_filtros)} arquivos, {sum(com_filtros.values())} filtros, {blocos_calendario} blocos dependem do calendário")
        print(f"[{len(resultados)} arquivos] linhas não reconhecidas: {len(nao_reconhecidas)} arquivos, {sum(nao_reconhecidas.values())} linhas")
        print(f"[{len(resultados)} arquivos] com erro: {sum(1 for a in resultados.values() if a.erros)} arquivos")
    assert nao_reconhecidas == {}, nao_reconhecidas
