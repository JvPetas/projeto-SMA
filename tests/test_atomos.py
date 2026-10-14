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
