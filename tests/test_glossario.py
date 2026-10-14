"""Testes do glossário: uma entrada por caso, com átomos copiados do corpus e texto esperado escrito à mão."""
import re
from collections import Counter
from pathlib import Path

import pytest

from gobr_agent.explain.atomos import separar_atomos
from gobr_agent.explain.glossario import (
    ALIAS,
    AVISO_SEM_DEFINICAO,
    COMPOSICAO,
    DEFINIDA,
    GLOSSARIO,
    SEM_DEFINICAO,
    STATUS,
    decompor,
    traduzir_atomo,
    traduzir_condicao,
)
from gobr_agent.parsing import parse_dir, parse_text
from gobr_agent.parsing.models import Carteira, Parametros, Segmentacao

DATA = Path(__file__).resolve().parents[1] / "data" / "gobr"
BASE = 'version 1.0\n\ntime "t":\n    vendedores todos\n\n'
GRUPO = "por algum vendedor do mesmo grupo do vendedor que tem o cliente na carteira"
EMPRESA = "por qualquer vendedor da empresa"
VEND = "foi do vendedor que tem o cliente na carteira"

# (átomo do corpus, arquivo:linha de onde veio, chave esperada, status esperado, texto esperado)
CASOS = [
    ("ativos para o vendedor", "regra_001:16", "ativos para o vendedor", DEFINIDA, "clientes ativos segundo o histórico do vendedor específico"),
    ("ativos para a empresa", "regra_076", "ativos para a empresa", DEFINIDA, "clientes ativos segundo o histórico de qualquer vendedor da empresa"),
    ("inativos para o vendedor", "regra_001:11", "inativos para o vendedor", DEFINIDA, "clientes sem compra com o vendedor específico há tempo suficiente para serem inativos"),
    ("inativos para a empresa", "regra_076:24", "inativos para a empresa", DEFINIDA, "clientes sem compra com nenhum vendedor da empresa"),
    ("inatividade de 90 dias", "manual 6.1", "inatividade de N dias", DEFINIDA, "clientes sem compra há pelo menos 90 dias"),
    ("unica compra com a empresa", "regra_076:44", "unica compra com a empresa", DEFINIDA, "clientes que só compraram uma única vez com a empresa"),
    ("unica compra com o vendedor", "regra_003:40", "unica compra com o vendedor", DEFINIDA, "clientes que só compraram uma única vez com o vendedor"),
    ("atividade do vendedor de 30 dias", "regra_145:64", "atividade do vendedor de N dias", DEFINIDA, "cliente comprou do vendedor no período de 30 dias"),
    ("tem venda da empresa entre 181 dias e 360 dias", "regra_186:38", "tem venda da empresa entre N dias e N dias", DEFINIDA, "clientes que compraram de qualquer vendedor entre 181 e 360 dias"),
    ("nao tem venda em 7 dias", "regra_169:24", "nao tem venda em N dias", COMPOSICAO, "clientes sem venda de nenhum vendedor do mesmo grupo em 7 dias"),
    ("nao tem venda da empresa no ano", "regra_175:49", "nao tem venda da empresa no ano", COMPOSICAO, "clientes que não têm venda da empresa no ano atual"),
    ("recencia de visita em 10 dias", "manual 6", "recencia de visita em N dias", DEFINIDA, f"última visita nos últimos 10 dias, {GRUPO}"),
    ("recencia de visita entre 4 dias e 3000 dias", "regra_160:20", "recencia de visita entre N dias e N dias", DEFINIDA, f"última visita entre 4 e 3000 dias, {GRUPO}"),
    ("fora da recencia de visita em 5 dias", "regra_245", "fora da recencia de visita em N dias", DEFINIDA, f"última visita fora dos últimos 5 dias, {GRUPO}"),
    ("recencia de visita na semana", "regra_245:110", "recencia de visita na semana", DEFINIDA, f"última visita na semana atual, {GRUPO}"),
    ("recencia de positivacao em 150 dias", "regra_032:84", "recencia de positivacao em N dias", COMPOSICAO, f"última positivação nos últimos 150 dias, {GRUPO}"),
    ("recencia de positivacao entre 21 dias e 41 dias", "regra_140:68", "recencia de positivacao entre N dias e N dias", COMPOSICAO, f"última positivação entre 21 e 41 dias, {GRUPO}"),
    ("recencia de positivacao no mes", "regra_184:20", "recencia de positivacao no mes", COMPOSICAO, f"última positivação no mês atual, {GRUPO}"),
    ("recencia de positivacao global em 7 dias", "regra_003:29", "recencia de positivacao global em N dias", DEFINIDA, f"última positivação nos últimos 7 dias, {EMPRESA}"),
    ("recencia de positivacao global entre 7 dias e 30 dias", "regra_003:45", "recencia de positivacao global entre N dias e N dias", DEFINIDA, f"última positivação entre 7 e 30 dias, {EMPRESA}"),
    ("recencia de positivacao global entre 0 dia e 30 dias", "regra_114:37", "recencia de positivacao global entre N dias e N dias", DEFINIDA, f"última positivação entre 0 e 30 dias, {EMPRESA}"),
    ("recencia de positivacao do vendedor em 30 dias", "regra_135:58", "recencia de positivacao do vendedor em N dias", COMPOSICAO, f"última positivação nos últimos 30 dias {VEND}"),
    ("recencia de positivacao do vendedor entre 11 dias e 59 dias", "regra_132:35", "recencia de positivacao do vendedor entre N dias e N dias", COMPOSICAO, f"última positivação entre 11 e 59 dias {VEND}"),
    ("fora da recencia de positivacao em 30 dias", "regra_049:33", "fora da recencia de positivacao em N dias", COMPOSICAO, f"última positivação fora dos últimos 30 dias, {GRUPO}"),
    ("fora da recencia de positivacao entre 8 dias e 15 dias", "regra_165:52", "fora da recencia de positivacao entre N dias e N dias", COMPOSICAO, f"última positivação fora do intervalo entre 8 e 15 dias, {GRUPO}"),
    ("fora da recencia de positivacao global em 90 dias", "regra_003:66", "fora da recencia de positivacao global em N dias", COMPOSICAO, f"última positivação fora dos últimos 90 dias, {EMPRESA}"),
    ("fora da recencia de positivacao global entre 15 dias e 90 dias", "regra_003:61", "fora da recencia de positivacao global entre N dias e N dias", COMPOSICAO, f"última positivação fora do intervalo entre 15 e 90 dias, {EMPRESA}"),
    ("fora da recencia de positivacao do vendedor em 90 dias", "regra_108:51", "fora da recencia de positivacao do vendedor em N dias", DEFINIDA, f"última positivação fora dos últimos 90 dias {VEND}"),
    ("fora da recencia de positivacao do vendedor entre 60 dias e 89 dias", "regra_108:36", "fora da recencia de positivacao do vendedor entre N dias e N dias", DEFINIDA, f"última positivação fora do intervalo entre 60 e 89 dias {VEND}"),
    ("inadimplentes", "regra_008:29", "inadimplentes", DEFINIDA, "clientes com pendências financeiras em aberto"),
    ("adimplentes", "regra_008:19", "adimplentes", DEFINIDA, "clientes sem pendências financeiras em aberto"),
    ("nao tem credito", "regra_131:23", "nao tem credito", DEFINIDA, "clientes sem crédito disponível"),
    ("com 5% de credito", "regra_235:49", "com N% de credito", DEFINIDA, "clientes com a porcentagem de crédito, em relação ao limite, maior ou igual a 5%"),
    ("com menos de r$ 80 de credito disponivel", "regra_153:27", "com menos de r$ N de credito disponivel", DEFINIDA, "clientes com crédito disponível abaixo de R$ 80"),
    ("total faturado no ano com a empresa maior que r$ 30000", "regra_159:23", "total faturado no ano com a empresa maior que r$ N", DEFINIDA, "faturamento total no ano com a empresa acima de R$ 30000"),
    ("total faturado no ano com a empresa menor que r$ 10000 ou indefinido", "regra_159:18", "total faturado no ano com a empresa menor que r$ N ou indefinido", COMPOSICAO, "faturamento total no ano com a empresa abaixo de R$ 10000, ou valor indefinido"),
    ("media faturada no ano com a empresa maior que r$ 25000", "regra_032:51", "media faturada no ano com a empresa maior que r$ N", COMPOSICAO, "faturamento médio por mês no ano com a empresa maior que R$ 25000"),
    ('nome da cidade igual("aguas de sao pedro","americana","araras")', "regra_135:23", "nome da cidade igual(S)", DEFINIDA, "clientes na cidade: aguas de sao pedro, americana, araras"),
    ('nome do bairro igual("centro","pavuna")', "regra_236:20", "nome do bairro igual(S)", COMPOSICAO, "clientes no bairro: centro, pavuna"),
    ('uf do estado igual("pr","sc","rs")', "regra_032:16", "uf do estado igual(S)", COMPOSICAO, "UF do estado igual a: pr, sc, rs"),
    ('o rotulo contem("condominio")', "regra_164:18", "o rotulo contem(S)", COMPOSICAO, "rótulo de classificação contém: condominio"),
    ('cnae igual("8411600","8424800")', "regra_131:18", "cnae igual(S)", DEFINIDA, "CNAE (mapeado pelo Govendas) igual a um de 8411600, 8424800"),
    ("status na receita federal definido como baixada", "regra_032:34", "status na receita federal definido como baixada", DEFINIDA, "empresa baixada na Receita Federal"),
    ("pessoa fisica", "regra_047:12", "pessoa fisica", DEFINIDA, "clientes pessoa física (CPF)"),
    ("pessoa juridica", "regra_130:39", "pessoa juridica", DEFINIDA, "clientes pessoa jurídica (CNPJ)"),
    ("cliente filial", "regra_003:14", "cliente filial", DEFINIDA, "o registro é uma filial"),
    ("bloqueados", "regra_076:19", "bloqueados", DEFINIDA, "clientes bloqueados para atendimento"),
    ('ramo de atividade igual("matcon","ferragista","agropecuaria","home center")', "regra_032:49", "ramo de atividade igual(S)", DEFINIDA, "ramo de atividade: um de matcon, ferragista, agropecuaria, home center"),
    ('ramo de atividade igual("2")', "regra_145:39", "ramo de atividade igual(S)", DEFINIDA, "ramo de atividade: um de 2"),
    ('ramo de atividade diferente("2","3","4")', "regra_059:12", "ramo de atividade diferente(S)", COMPOSICAO, "ramo de atividade: diferente de 2, 3, 4"),
    ('codigo da rota igual("8","9","10","11")', "regra_140:14", "codigo da rota igual(S)", COMPOSICAO, "código da rota: um de 8, 9, 10, 11"),
    ('tipo de cobranca igual("dh")', "regra_153:22", "tipo de cobranca igual(S)", COMPOSICAO, "tipo de cobrança: um de dh"),
    ('id do cliente principal diferente("36979")', "regra_203:20", "id do cliente principal diferente(S)", DEFINIDA, "id do cliente principal diferente de 36979"),
    ("curva a com a empresa", "regra_135:253", "curva a com a empresa", DEFINIDA, "clientes da curva A de faturamento com a empresa"),
    ("curva b com a empresa", "regra_135:259", "curva b com a empresa", DEFINIDA, "clientes da curva B de faturamento com a empresa"),
    ("curva c com a empresa", "regra_135:265", "curva c com a empresa", DEFINIDA, "clientes da curva C de faturamento com a empresa"),
    ("no ciclo de vida prospect com o vendedor", "regra_108:16", "no ciclo de vida prospect com o vendedor", DEFINIDA, "cliente prospect no ciclo de vida do vendedor"),
    ("no ciclo de vida prospect com a empresa", "regra_003:34", "no ciclo de vida prospect com a empresa", COMPOSICAO, "cliente prospect no ciclo de vida da empresa"),
    ("no ciclo de vida ativo com a empresa", "regra_077:36", "no ciclo de vida ativo com a empresa", COMPOSICAO, "cliente ativo no ciclo de vida da empresa, fez alguma compra"),
    ("no ciclo de vida inativo com a empresa", "regra_144:53", "no ciclo de vida inativo com a empresa", DEFINIDA, "cliente inativo no ciclo de vida da empresa"),
    ("frequencia historica menor que 30 dias", "regra_076:50", "frequencia historica menor que N dias", COMPOSICAO, "frequência histórica do cliente menor que 30 dias"),
    ("frequencia historica maior que 30 dias", "regra_183:31", "frequencia historica maior que N dias", DEFINIDA, "frequência histórica do cliente maior que 30 dias"),
    ("frequencia historica entre 31 dias e 90 dias", "regra_139:42", "frequencia historica entre N dias e N dias", DEFINIDA, "frequência histórica do cliente entre 31 e 90 dias"),
    ('contido na segmentacao("ext_niteroi_rio2_para_tmk1")', "regra_128:82", "contido na segmentacao(S)", DEFINIDA, "cliente pertence às segmentações: ext_niteroi_rio2_para_tmk1"),
    ('nao contido na segmentacao("ext_niteroi_rio2_para_tmk1","ext_lagos_norte_para_tmk2")', "regra_128:244", "nao contido na segmentacao(S)", DEFINIDA, "cliente não pertence às segmentações: ext_niteroi_rio2_para_tmk1, ext_lagos_norte_para_tmk2"),
    ("cadastrado faz 60 dias", "regra_003:39", "cadastrado faz N dias", DEFINIDA, "clientes cadastrados no ERP há no mínimo 60 dias"),
    ("cadastrado a partir do dia '2023-07-18'", "regra_147:26", "cadastrado a partir do dia 'N-N-N'", DEFINIDA, "clientes cadastrados no ERP após o dia 2023-07-18"),
    ("data da rota na semana", "regra_173:26", "data da rota na semana", COMPOSICAO, "clientes com data de rota na semana atual"),
    # sem definição no manual: o literal sai sem expandir
    ("sem venda", "regra_001:21", "sem venda", SEM_DEFINICAO, "sem venda"),
    ("sem vendas", "regra_023:23", "sem vendas", SEM_DEFINICAO, "sem vendas"),
    ("sem venda do vendedor", "regra_140:58", "sem venda do vendedor", SEM_DEFINICAO, "sem venda do vendedor"),
    # alias
    ("e o cliente filial", "regra_116:17", "e o cliente filial", ALIAS, "o registro é uma filial"),
]


@pytest.mark.parametrize("atomo, origem, chave, status, esperado", CASOS, ids=[c[2] for c in CASOS])
def test_uma_entrada_por_caso(atomo, origem, chave, status, esperado):
    t = traduzir_atomo(atomo)
    assert (t.chave, t.status, t.texto) == (chave, status, esperado)
    assert t.traduzido == (status != SEM_DEFINICAO)


def test_todas_as_entradas_do_glossario_tem_caso():
    assert {c[2] for c in CASOS} == set(GLOSSARIO)


def test_sem_definicao_tem_aviso_e_nao_expande():
    for atomo in ("sem venda", "sem vendas", "sem venda do vendedor"):
        t = traduzir_atomo(atomo)
        assert t.observacao == AVISO_SEM_DEFINICAO == "⚠ condição sem definição no manual"
        assert t.texto == atomo and not t.traduzido


def test_alias_cliente_filial_com_e_sem_acento_vira_um_atomo_so():
    for linha in ("quando e o cliente filial", "quando é o cliente filial"):
        arq = parse_text(BASE + f'parametros "Não agendar filiais":\n    do time("t")\n    {linha}\n    nao agendar\n')
        (condicao,) = arq.parametros[0].quando
        (t,) = traduzir_condicao(condicao)
        assert (t.status, t.texto) == (ALIAS, "o registro é uma filial")
    entrada = GLOSSARIO["e o cliente filial"]
    assert entrada.alias_de == "cliente filial" and "12 blocos" in entrada.nota and "Não agendar filiais" in entrada.nota
    assert entrada.fontes == GLOSSARIO["cliente filial"].fontes


def test_cnae_e_igual_com_verbo_e_um_atomo_so():
    arq = parse_text(BASE + 'parametros "A":\n    do time("t")\n    quando ativos para o vendedor e cnae é igual("8630501","8610101")\n    frequencia de 7 dias\n')
    (condicao,) = arq.parametros[0].quando
    assert [(t.chave, t.texto) for t in traduzir_condicao(condicao)] == [
        ("ativos para o vendedor", "clientes ativos segundo o histórico do vendedor específico"),
        ("cnae igual(S)", "CNAE (mapeado pelo Govendas) igual a um de 8630501, 8610101"),
    ]


def test_texto_entre_aspas_mantem_a_caixa_original_na_condicao():
    arq = parse_text(BASE + 'parametros "A":\n    do time("t")\n    quando ramo de atividade igual("MATCON","Home Center")\n    frequencia de 7 dias\n')
    (condicao,) = arq.parametros[0].quando
    (t,) = traduzir_condicao(condicao)
    assert t.texto == "ramo de atividade: um de MATCON, Home Center"


def test_condicao_com_varios_atomos_traduz_cada_um():
    arq = parse_text(BASE + 'parametros "A":\n    do time("t")\n    quando inativos para o vendedor e inadimplentes\n    frequencia de 7 dias\n')
    (condicao,) = arq.parametros[0].quando
    assert [t.texto for t in traduzir_condicao(condicao)] == [
        "clientes sem compra com o vendedor específico há tempo suficiente para serem inativos",
        "clientes com pendências financeiras em aberto",
    ]


def test_atomo_fora_do_glossario_sai_como_sem_traducao():
    t = traduzir_atomo("frequencia historica de 7 dias")  # regra_146:23
    assert (t.texto, t.chave, t.status, t.traduzido) == ("[sem tradução: frequencia historica de 7 dias]", None, None, False)


def test_decompor_normaliza_numeros_textos_e_dia_no_singular():
    assert decompor('cnae igual("1","2")') == ("cnae igual(S)", [], ["1", "2"])
    assert decompor("recencia de positivacao global entre 0 dia e 30 dias") == (
        "recencia de positivacao global entre N dias e N dias",
        ["0", "30"],
        [],
    )
    assert decompor("cadastrado a partir do dia '2023-07-18'")[:2] == ("cadastrado a partir do dia 'N-N-N'", ["2023", "07", "18"])


# --------------------------------------------------------------------- integridade do glossário


@pytest.mark.parametrize("entrada", list(GLOSSARIO.values()), ids=list(GLOSSARIO))
def test_integridade_das_entradas(entrada):
    assert entrada.status in STATUS
    if entrada.status in (DEFINIDA, COMPOSICAO):
        assert entrada.fontes, "toda entrada traduzida precisa de página do manual"
        assert entrada.modelo.count("{S}") == entrada.chave.count("S)")
    if entrada.status == COMPOSICAO:
        assert len(entrada.fontes) >= 2, "composição = linha-base + nota do manual"
    if entrada.status == SEM_DEFINICAO:
        assert entrada.fontes == () and entrada.modelo == entrada.chave
    if entrada.status == ALIAS:
        assert entrada.alias_de in GLOSSARIO
    for fonte in entrada.fontes:
        assert 22 <= fonte.pdf <= 41 and fonte.impressa == fonte.pdf - 4 and fonte.trecho


def test_numero_de_placeholders_bate_com_a_chave():
    for entrada in GLOSSARIO.values():
        if entrada.status == SEM_DEFINICAO:
            continue
        n_chave = len(re.findall(r"(?<![a-z])N(?![a-z])", entrada.chave))
        assert entrada.modelo.count("{N}") == n_chave, entrada.chave


# -------------------------------------------------------------------------- cobertura no corpus


@pytest.mark.skipif(not DATA.exists() or not any(DATA.glob("*.gobr")), reason="data/gobr vazia")
def test_cobertura_nos_249_arquivos(capsys):
    total = Counter()
    nao_traduzidos = Counter()
    por_status = Counter()
    for arq in parse_dir(DATA):
        for bloco in arq.blocos:
            if not isinstance(bloco, (Parametros, Carteira, Segmentacao)):
                continue
            for condicao in bloco.quando:
                for t in traduzir_condicao(condicao):  # qualquer exceção reprova o teste
                    total["atomos"] += 1
                    por_status[t.status or "SEM_ENTRADA"] += 1
                    if t.status is None:
                        nao_traduzidos[t.texto.removeprefix("[sem tradução: ").removesuffix("]")] += 1
    n = total["atomos"]
    com_entrada = n - por_status["SEM_ENTRADA"]
    traduzidos = por_status[DEFINIDA] + por_status[COMPOSICAO] + por_status[ALIAS]
    with capsys.disabled():
        print(f"\n[glossário] {n} átomos: {traduzidos} traduzidos ({100 * traduzidos / n:.1f}%), "
              f"{por_status[SEM_DEFINICAO]} sem definição no manual ({100 * por_status[SEM_DEFINICAO] / n:.1f}%), "
              f"{por_status['SEM_ENTRADA']} sem tradução ({100 * por_status['SEM_ENTRADA'] / n:.1f}%)")
        print(f"[glossário] por status: {dict(por_status)}")
        print("[glossário] 20 átomos sem tradução mais frequentes:")
        for atomo, k in nao_traduzidos.most_common(20):
            print(f"   {k:>3}  {atomo[:100]}")
    assert com_entrada / n >= 0.90, "cobertura mínima de 90% dos átomos"
