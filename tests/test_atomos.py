"""Testes da separação de condições atômicas (`e` entre condições)."""
import pytest

from gobr_agent.explain.atomos import separar_atomos


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("inativos para o vendedor e inadimplentes", ["inativos para o vendedor", "inadimplentes"]),
        ("recencia de positivacao entre 60 dias e 90 dias", ["recencia de positivacao entre 60 dias e 90 dias"]),
        ("recencia de positivacao entre N dias e N dias", ["recencia de positivacao entre N dias e N dias"]),
        (
            "recencia de visita entre 10 dias e 90 dias e adimplentes",
            ["recencia de visita entre 10 dias e 90 dias", "adimplentes"],
        ),
        (
            "media faturada no ano com a empresa maior que r$ 100 e menor que r$ 900",
            ["media faturada no ano com a empresa maior que r$ 100 e menor que r$ 900"],
        ),
        (
            "media faturada no ano com a empresa maior que r$ 100 e adimplentes",
            ["media faturada no ano com a empresa maior que r$ 100", "adimplentes"],
        ),
        ('nome da cidade igual("rio e sao paulo") e adimplentes', ['nome da cidade igual("rio e sao paulo")', "adimplentes"]),
        ("e o cliente filial", ["e o cliente filial"]),
        ("adimplentes", ["adimplentes"]),
        # verbo "é" antes do operador (regra_131:18 e :31, regra_203:20): não é conector e some do átomo
        ('cnae e igual("8411600","8424800")', ['cnae igual("8411600","8424800")']),
        ('cnae igual("8411600")', ['cnae igual("8411600")']),
        ('ativos para o vendedor e cnae e igual("8630501","8610101")', ["ativos para o vendedor", 'cnae igual("8630501","8610101")']),
        ('id do cliente principal e diferente("36979")', ['id do cliente principal diferente("36979")']),
        # intervalo de datas (regra_175:54)
        (
            "recencia de positivacao entre '2023-12-31' e '2023-01-01'",
            ["recencia de positivacao entre '2023-12-31' e '2023-01-01'"],
        ),
        ("recencia de positivacao entre 'N-N-N' e 'N-N-N'", ["recencia de positivacao entre 'N-N-N' e 'N-N-N'"]),
    ],
)
def test_separar_atomos(texto, esperado):
    assert separar_atomos(texto) == esperado


def test_exemplo_do_manual_6_com_tres_filtros():
    # manual p.26: `quando adimplentes` / `e ativos para o vendedor` / `e recencia de visita entre 10 dias e 90 dias`
    linha = "adimplentes e ativos para o vendedor e recencia de visita entre 10 dias e 90 dias"
    assert separar_atomos(linha) == [
        "adimplentes",
        "ativos para o vendedor",
        "recencia de visita entre 10 dias e 90 dias",
    ]


BASE = 'version 1.0\n\ntime "t":\n    vendedores todos\n\n'


@pytest.mark.parametrize(
    "linha_do_corpus",
    [
        "quando e o cliente filial",  # regra_116:17 (e outras 6)
        "quando é o cliente filial",  # regra_129:17 (e outras 3, com acento)
    ],
)
def test_e_o_cliente_filial_e_um_unico_atomo(linha_do_corpus):
    from gobr_agent.parsing import parse_text

    arq = parse_text(BASE + f'parametros "Não agendar filiais":\n    do time("t")\n    {linha_do_corpus}\n    nao agendar\n')
    (condicao,) = arq.parametros[0].quando
    assert condicao.conector is None
    assert condicao.texto == "e o cliente filial"  # o "é" perde o acento na normalização
    assert separar_atomos(condicao.texto) == ["e o cliente filial"]  # um átomo, sem lado vazio
