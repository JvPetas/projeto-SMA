"""Testes de recencia.py: intervalos e o efeito da ordem dos blocos."""
from pathlib import Path

import pytest

from gobr_agent.explain.recencia import (
    INF,
    analisar_arquivo,
    chave_do_grupo,
    complemento,
    diferenca,
    intersecao,
    interpretar_atomo,
    texto_intervalos,
    uniao,
)
from gobr_agent.parsing import parse_file, parse_text

DATA = Path(__file__).resolve().parents[1] / "data" / "gobr"
BASE = 'version 1.0\n\ntime "t":\n    vendedores todos\n\n'


def bloco(nome, *condicoes, corpo="frequencia de 7 dias", escopo='do time("t")', depois_do_escopo=""):
    linhas = [f'parametros "{nome}":', f"    {escopo}"]
    if depois_do_escopo:
        linhas.append(f"    {depois_do_escopo}")
    for i, c in enumerate(condicoes):
        linhas.append(f"    {'quando' if i == 0 else 'e'} {c}")
    linhas.append(f"    {corpo}")
    return "\n".join(linhas) + "\n"


def infos(*blocos):
    arq = parse_text(BASE + "\n".join(blocos))
    assert arq.erros == []
    mapa = analisar_arquivo(arq)
    return [mapa[p.linha_ini] for p in arq.parametros]


# ----------------------------------------------------------------------- álgebra de intervalos


def test_uniao_funde_intervalos_que_se_tocam():
    assert uniao(((0, 60),), ((60, 90),)) == ((0, 90),)
    assert uniao(((0, 30),), ((60, 90),)) == ((0, 30), (60, 90))
    assert uniao(((0, 60),), ((30, 90),)) == ((0, 90),)


def test_intersecao_diferenca_e_complemento():
    assert intersecao(((0, 45),), ((30, INF),)) == ((30, 45),)
    assert intersecao(((0, 30),), ((60, 90),)) == ()
    assert complemento(((0, 60),)) == ((60, INF),)
    assert complemento(((60, INF),)) == ((0, 60),)
    assert complemento(((30, 60),)) == ((0, 30), (60, INF))
    assert complemento(()) == ((0, INF),)
    assert diferenca(((0, 90),), ((0, 60),)) == ((60, 90),)
    assert diferenca(((0, 60),), ((0, 90),)) == ()


def test_texto_dos_intervalos_so_com_entre_e_mais_de():
    assert texto_intervalos(((60, 90),)) == "entre 60 e 90 dias"
    assert texto_intervalos(((0, 60),)) == "entre 0 e 60 dias"
    assert texto_intervalos(((90, INF),)) == "mais de 90 dias"
    assert texto_intervalos(((0, 30), (60, INF))) == "entre 0 e 30 dias ou mais de 60 dias"
    assert texto_intervalos(()) == "nenhum cliente"
    assert texto_intervalos(((0, INF),)) == "qualquer tempo desde a última compra"


# ------------------------------------------------------------------------- condição atômica


@pytest.mark.parametrize(
    "texto, cadeia, subtipo, intervalo",
    [
        ("recencia de positivacao em 60 dias", "positivacao", "simples", ((0, 60),)),
        ("recencia de positivacao global em 60 dias", "positivacao", "global", ((0, 60),)),
        ("recencia de positivacao do vendedor entre 30 dias e 60 dias", "positivacao_vendedor", "", ((30, 60),)),
        ("fora da recencia de positivacao em 45 dias", "positivacao", "simples", ((45, INF),)),
        ("fora da recencia de positivacao global entre 30 dias e 60 dias", "positivacao", "global", ((0, 30), (60, INF))),
        ("recencia de visita em 10 dias", "visita", "", ((0, 10),)),
        ("recencia de visita entre 4 dias e 3000 dias", "visita", "", ((4, 3000),)),
        ("fora da recencia de visita global em 5 dias", "visita", "", ((5, INF),)),
        ("recencia de positivacao global entre 0 dia e 30 dias", "positivacao", "global", ((0, 30),)),  # regra_114:37
        ("recencia de visita em 1 dia", "visita", "", ((0, 1),)),
    ],
)
def test_interpretar_atomo(texto, cadeia, subtipo, intervalo):
    atomo = interpretar_atomo(texto)
    assert (atomo.cadeia, atomo.subtipo, atomo.intervalo) == (cadeia, subtipo, intervalo)


@pytest.mark.parametrize("texto", ["inadimplentes", "inatividade de 90 dias", "recencia de positivacao em 3 meses", "sem venda"])
def test_atomo_que_nao_e_recencia(texto):
    assert interpretar_atomo(texto) is None


# --------------------------------------------------------------------------- cadeia de blocos


def test_cadeia_basica_estreita_cada_bloco_pelo_anterior():
    a, b, c, d = infos(
        bloco("Baixados", "status na receita federal definido como baixada", corpo="nao agendar"),
        bloco("Ativo", "recencia de positivacao global em 60 dias", corpo="frequencia de 14 dias"),
        bloco("Risco", "recencia de positivacao em 90 dias"),
        bloco("Inativo"),
    )
    assert not a.puro and a.efetivo is None
    assert (b.puro, b.efetivo, b.texto_efetivo) == (True, ((0, 60),), "entre 0 e 60 dias")
    assert (c.efetivo, c.texto_efetivo) == (((60, 90),), "entre 60 e 90 dias")
    assert c.literal == "recencia de positivacao em 90 dias"
    assert d.catch_all and d.texto_catch_all == "mais de 90 dias" and d.lacunas == ()
    assert b.bloqueios_anteriores and d.bloqueios_anteriores
    assert not b.antecedentes and not d.antecedentes


def test_global_e_sem_global_formam_uma_cadeia_com_aviso():
    a, b = infos(
        bloco("A", "recencia de positivacao global em 60 dias"),
        bloco("B", "recencia de positivacao em 90 dias"),
    )
    assert b.efetivo == ((60, 90),)
    aviso = "mistura recência global e sem `global` na mesma cadeia (tratadas juntas)"
    assert aviso in a.notas and aviso in b.notas
    sem_mistura = infos(bloco("A", "recencia de positivacao em 60 dias"), bloco("B", "recencia de positivacao em 90 dias"))
    assert all(not any("mistura" in n for n in i.notas) for i in sem_mistura)


def test_nao_agendar_puro_de_recencia_consome_clientes():
    bloqueio, resto, final = infos(
        bloco("Bloqueio", "recencia de positivacao em 30 dias", corpo="nao agendar"),
        bloco("Resto", "recencia de positivacao em 60 dias"),
        bloco("Final", corpo="nao agendar"),
    )
    assert bloqueio.puro and bloqueio.efetivo == ((0, 30),)
    assert resto.efetivo == ((30, 60),)
    assert final.texto_catch_all == "mais de 60 dias"


def test_bloco_com_outra_condicao_nao_entra_na_uniao_e_gera_nota():
    prospects, a, adimplentes, c = infos(
        bloco("Prospects", "no ciclo de vida prospect com a empresa"),
        bloco("A", "recencia de positivacao em 30 dias"),
        bloco("Com adimplentes", "recencia de positivacao em 60 dias", "adimplentes"),
        bloco("C", "recencia de positivacao em 90 dias"),
    )
    assert not adimplentes.puro
    assert c.efetivo == ((30, 90),)  # o bloco impuro não consumiu (30, 60)
    assert "pode haver clientes já tratados pela regra Com adimplentes" in c.notas
    assert c.antecedentes == ("Com adimplentes",)


def test_filtro_temporal_torna_o_bloco_impuro():
    a, b = infos(
        bloco("Na segunda", "recencia de positivacao em 30 dias", depois_do_escopo="na segunda"),
        bloco("B", "recencia de positivacao em 60 dias"),
    )
    assert not a.puro
    assert b.efetivo == ((0, 60),)
    assert "pode haver clientes já tratados pela regra Na segunda" in b.notas


def test_ou_entre_condicoes_torna_o_bloco_impuro():
    texto_ou = (
        'parametros "Com ou":\n    do time("t")\n    quando recencia de positivacao em 30 dias\n'
        "    ou recencia de positivacao em 60 dias\n    frequencia de 7 dias\n"
    )
    arq = parse_text(BASE + texto_ou)
    assert not analisar_arquivo(arq)[arq.parametros[0].linha_ini].puro


def test_cadeias_de_tipos_diferentes_sao_independentes():
    p1, v, pv, p2 = infos(
        bloco("P", "recencia de positivacao em 30 dias"),
        bloco("V", "recencia de visita em 45 dias"),
        bloco("PV", "recencia de positivacao do vendedor em 20 dias"),
        bloco("P2", "recencia de positivacao em 60 dias"),
    )
    assert v.efetivo == ((0, 45),) and pv.efetivo == ((0, 20),)
    assert p2.efetivo == ((30, 60),)
    assert not v.antecedentes


def test_catch_all_com_lacuna_nao_afirma_nada():
    a, b, final = infos(
        bloco("A", "recencia de positivacao em 30 dias"),
        bloco("B", "recencia de positivacao entre 60 dias e 90 dias"),
        bloco("Final", corpo="nao agendar"),
    )
    assert b.efetivo == ((60, 90),)
    assert final.texto_catch_all is None
    assert final.lacunas == ((30, 60),)
    assert "lacuna na cadeia de recência: nenhum bloco cobre entre 30 e 60 dias" in final.notas


def test_catch_all_com_cadeias_diferentes_nao_afirma_nada():
    *_, final = infos(
        bloco("P", "recencia de positivacao em 30 dias"),
        bloco("V", "recencia de visita em 45 dias"),
        bloco("Final", corpo="nao agendar"),
    )
    assert final.texto_catch_all is None
    assert any("cadeias de recência de tipos diferentes" in n for n in final.notas)


def test_catch_all_sem_nenhuma_cadeia():
    prospects, final = infos(bloco("Prospects", "no ciclo de vida prospect com a empresa"), bloco("Final"))
    assert final.catch_all and final.texto_catch_all is None and final.notas == ()


def test_intervalo_ja_tratado_fica_sem_clientes_efetivos():
    a, b = infos(bloco("A", "recencia de positivacao em 90 dias"), bloco("B", "recencia de positivacao em 60 dias"))
    assert b.efetivo == () and b.texto_efetivo == "nenhum cliente"
    assert any("sem clientes efetivos" in n for n in b.notas)


def test_recencia_com_e_e_fora_vira_interseccao():
    (info,) = infos(bloco("A", "recencia de positivacao em 45 dias", "fora da recencia de positivacao em 30 dias"))
    assert info.efetivo == ((30, 45),)
    assert info.literal == "recencia de positivacao em 45 dias e fora da recencia de positivacao em 30 dias"
    (info,) = infos(bloco("B", "fora da recencia de positivacao global entre 30 dias e 60 dias"))
    assert info.texto_efetivo == "entre 0 e 30 dias ou mais de 60 dias"


def test_inline_e_na_mesma_linha_tambem_e_interseccao():
    texto = 'parametros "A":\n    do time("t")\n    quando recencia de positivacao em 45 dias e fora da recencia de positivacao em 30 dias\n    frequencia de 7 dias\n'
    arq = parse_text(BASE + texto)
    assert analisar_arquivo(arq)[arq.parametros[0].linha_ini].efetivo == ((30, 45),)


def test_escopos_diferentes_formam_cadeias_diferentes():
    a1, b1, a2, b2 = infos(
        bloco("A1", "recencia de positivacao em 30 dias", escopo='do time("a")'),
        bloco("B1", "recencia de positivacao em 30 dias", escopo='do time("b")'),
        bloco("A2", "recencia de positivacao em 60 dias", escopo='do time("a")'),
        bloco("B2", "recencia de positivacao em 90 dias", escopo='do time("b")'),
    )
    assert a2.efetivo == ((30, 60),)
    assert b2.efetivo == ((30, 90),)
    assert not any("pode haver" in n for n in a2.notas)  # os blocos do outro escopo não contam


def test_chave_do_grupo_resolve_o_time_da_carteira():
    arq = parse_text(
        BASE
        + bloco("C1", "adimplentes", escopo='da carteira("c1")')
        + bloco("C2", "adimplentes", escopo='da carteira("c2")')
    )
    p1, p2 = arq.parametros
    mapa = {"c1": "televendas", "c2": "televendas"}
    k1, k2 = chave_do_grupo(p1, mapa), chave_do_grupo(p2, mapa)
    assert k1 != k2 and k1[1] == k2[1] == ("televendas",)


# ------------------------------------------------------------------------ exemplos reais


def carregar(nome):
    caminho = DATA / nome
    if not caminho.exists():
        pytest.skip(f"{nome} não está em data/gobr")
    arq = parse_file(caminho)
    mapa = analisar_arquivo(arq)
    return {p.nome: mapa[p.linha_ini] for p in arq.parametros}


def test_exemplo_infinitto():
    info = carregar("RegraInfinittoDesign.gobr")
    assert info["Ativo (Com último pedido em até 60d atrás)"].efetivo == ((0, 60),)
    assert info["Risco de Inatividade (Com pedido entre 60 e 90d atrás)"].efetivo == ((60, 90),)
    inativo = info["Inativo (Com último pedido há mais de 90d atrás)"]
    assert inativo.catch_all and inativo.texto_catch_all == "mais de 90 dias"
    assert not info["Baixados na Receita Federal"].puro and not info["Prospects (Nunca tirou pedido)"].puro


def test_exemplo_maxlub():
    info = carregar("RegraMaxlub.gobr")
    esperado = {
        "Clientes ativos": (0, 60),
        "Risco de inatividade": (60, 90),
        "Inativos (90 dias)": (90, 120),
        "Inativos (120 dias)": (120, 150),
        "Inativos (150 dias)": (150, 180),
    }
    for nome, par in esperado.items():
        assert info[nome].efetivo == (par,), nome
    fallback = info["Clientes que não se enquadraram nas regras padrão"]
    assert fallback.texto_catch_all == "mais de 180 dias"


def test_exemplo_v1_vidros():
    info = carregar("V1Vidros-RegraComercial.gobr")
    assert info["Clientes Ativos"].efetivo == ((0, 30),)
    assert info["Risco de Inatividade"].efetivo == ((30, 45),)
    assert info["Inativos"].efetivo == ((45, INF),)
    assert info["Inativos"].texto_efetivo == "mais de 45 dias"
    assert not info["Clientes Prospects"].puro
