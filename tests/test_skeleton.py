"""Gabaritos, invariantes do corpus e casos de recência do esqueleto."""
import re
from collections import Counter
from pathlib import Path

import pytest

from gobr_agent.explain.glossario import (
    ALIAS, COMPOSICAO, DEFINIDA, INFERIDA, SEM_DEFINICAO, GLOSSARIO, traduzir_atomo,
)
from gobr_agent.explain.recencia import INF, analisar_arquivo
from gobr_agent.explain.skeleton import AVISO_PROSPECT, NOTA_BLOQUEIOS, gerar_esqueleto, main, renderizar_markdown
from gobr_agent.parsing import parse_dir, parse_file, parse_text
from gobr_agent.parsing.normalize import normalizar

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "gobr"
GOLD = ROOT / "data" / "processed" / "gold"
BASE = 'version 1.0\ntime "t":\n    vendedores todos\n'


def escrever(tmp_path, texto):
    p = tmp_path / "exemplo.gobr"
    p.write_text(BASE + texto, encoding="utf-8")
    return p


def regra(nome, condicao="", frequencia="de 7 dias", escopo="t"):
    return (f'\nparametros "{nome}":\n    do time("{escopo}")\n'
            + (f"    quando {condicao}\n" if condicao else "")
            + ("    nao agendar\n" if frequencia is None else f"    frequencia {frequencia}\n"))


def linhas_gold(p):
    for linha in p.read_text(encoding="utf-8").splitlines():
        if linha.startswith("|") and not linha.startswith(("| Nome", "|---")):
            yield tuple(x.strip() for x in linha.strip("|").split("|"))


def assinatura_gold(row):
    nome, condicao, frequencia, _ = row
    if not frequencia:
        return None
    dias = int(re.search(r"\d+", frequencia)[0])
    if "prospect" in normalizar(nome):
        return "prospect", dias
    numeros = [int(x) for x in re.findall(r"\d+", condicao)]
    t = normalizar(condicao)
    if "entre" in t:
        intervalo = tuple(numeros)
    elif "a mais" in t:
        intervalo = numeros[0], INF
    elif len(numeros) == 2:
        intervalo = numeros[1], numeros[0]
    else:
        assert len(numeros) == 1, row
        intervalo = 0, numeros[0]
    return intervalo, dias


def assinatura_codigo(linha, parametro):
    if any("no ciclo de vida prospect" in c.texto for c in parametro.quando):
        return "prospect", parametro.frequencia.dias
    info = linha.recencia
    if info.catch_all and info.texto_catch_all:
        intervalo = int(re.search(r"\d+", info.texto_catch_all)[0]), INF
    elif info.efetivo and len(info.efetivo) == 1:
        intervalo = info.efetivo[0]
    else:
        return None
    return intervalo, "Não agendar" if parametro.nao_agendar else parametro.frequencia.dias


def divergencias_gold(gold, arq, esqueleto):
    """Diferenças documentais, separadas da correspondência por faixa e frequência."""
    texto = normalizar(gold.read_text(encoding="utf-8"))
    resultado = []
    for p in arq.parametros:
        if any("status na receita federal" in c.texto for c in p.quando) and "baixad" not in texto:
            resultado.append((p.linha_ini, "bloqueio de baixados ausente da descrição"))
        if p.catch_all and p.nao_agendar:
            resultado.append((p.linha_ini, "fallback Não agendar ausente da descrição"))
    if "capacidade de atendimento" in texto:
        resultado.append((None, "capacidade 35 clientes/dia sem equivalente no código"))
    if any("agendar inadiplentes" in normalizar(r[0]) for r in linhas_gold(gold)):
        resultado.append((None, "agendar inadimplentes autorizados sem bloco próprio no código"))
    return resultado


@pytest.mark.parametrize("gold", sorted(GOLD.glob("*.md")), ids=lambda p: p.stem)
def test_gabarito_por_faixa_e_frequencia_sem_depender_da_posicao(gold, capsys):
    caminho = DATA / gold.with_suffix(".gobr").name
    arq = parse_file(caminho)
    e = gerar_esqueleto(caminho)
    parametros = {p.linha_ini: p for p in arq.parametros}
    esperado = Counter(a for r in linhas_gold(gold) if (a := assinatura_gold(r)) is not None)
    encontrado = Counter(a for l in e.linhas if (a := assinatura_codigo(l, parametros[l.linha])) is not None)
    assert not (esperado - encontrado), (gold.name, esperado - encontrado)
    assert [l.nome for l in e.linhas] == [p.nome for p in arq.parametros]
    bloqueado = False
    for linha, parametro in zip(e.linhas, arq.parametros):
        assert (NOTA_BLOQUEIOS in linha.observacao) is bloqueado
        assert not linha.antecedentes and "pode haver clientes já tratados" not in linha.observacao
        bloqueado = bloqueado or parametro.nao_agendar
    with capsys.disabled():
        print(f"\n[gabarito {gold.stem}] faixas/frequências: {dict(esperado)}")
        for linha, mensagem in divergencias_gold(gold, arq, e):
            print(f"[divergência documentada {caminho.name}:{linha or '-'}] {mensagem}")
    if any(p.catch_all and p.nao_agendar for p in arq.parametros):
        assert encontrado[((180, INF), "Não agendar")] == 1


def test_sombreamento_contagens_e_conjuntos_exatos(capsys):
    provados, hipotese = set(), set()
    alvos_sem_prova = {("regra_135.gobr", n) for n in (74, 111, 148, 185, 222)}
    sem_prova = set()
    for p in sorted(DATA.glob("*.gobr")):
        for l in gerar_esqueleto(p).linhas:
            alvo = p.name, l.linha
            info = l.recencia
            assert not (info.sombreamento_provado and info.sombreado_sob_hipotese)
            if info.sombreamento_provado:
                provados.add(alvo)
            if info.sombreado_sob_hipotese:
                hipotese.add(alvo)
            if alvo in alvos_sem_prova:
                assert not info.sombreamento_provado and not info.sombreado_sob_hipotese, alvo
                assert "sem clientes efetivos" not in l.observacao, alvo
                assert "nenhum cliente" not in l.condicao, alvo
                sem_prova.add(alvo)
    esperado_provado = {("regra_003.gobr", 58), ("regra_155.gobr", 77),
                       ("regra_221.gobr", 44), ("regra_226.gobr", 39)}
    esperado_hipotese = {(f"regra_{n}.gobr", l) for n in (179, 216) for l in (71, 86, 102)}
    with capsys.disabled():
        print(f"\n[sombreamento] provados={len(provados)}: {sorted(provados)}")
        print(f"[sombreamento] sob hipótese={len(hipotese)}: {sorted(hipotese)}")
        print(f"[sombreamento] não provados={len(sem_prova)}: {sorted(sem_prova)}")
    assert len(provados) == 4 and provados == esperado_provado
    assert len(hipotese) == 6 and hipotese == esperado_hipotese
    assert len(sem_prova) == 5 and sem_prova == alvos_sem_prova


def test_mesma_historia_prova_e_hipotese_so_no_sentido_permitido():
    casos = [
        ("fora da recencia de positivacao em 120 dias", "fora da recencia de positivacao global em 180 dias", False, True),
        ("fora da recencia de positivacao global em 120 dias", "fora da recencia de positivacao em 180 dias", False, False),
        ("fora da recencia de positivacao global em 120 dias", "fora da recencia de positivacao global em 180 dias", True, False),
        ("recencia de positivacao global em 60 dias", "recencia de positivacao em 30 dias", False, False),
        ("fora da recencia de positivacao em 30 dias", "recencia de positivacao global entre 30 dias e 60 dias", False, False),
    ]
    for anterior, posterior, provado, hipotese in casos:
        arq = parse_text(BASE + regra("A", anterior) + regra("B", posterior))
        info = analisar_arquivo(arq)[arq.parametros[-1].linha_ini]
        assert (info.sombreamento_provado, info.sombreado_sob_hipotese) == (provado, hipotese)
        if not (provado or hipotese):
            assert all("sem clientes efetivos" not in n for n in info.notas)


def test_adjacencia_de_um_dia_nao_e_lacuna_mas_dia_inteiro_e(tmp_path):
    for inicio, lacuna in ((31, False), (32, True)):
        p = escrever(tmp_path, regra("A", "recencia de positivacao em 30 dias")
                     + regra("B", f"recencia de positivacao entre {inicio} dias e 60 dias") + regra("Fim"))
        linha = gerar_esqueleto(p).linhas[-1]
        assert bool(linha.recencia.lacunas) is lacuna
        assert ("acima de 60 dias" in linha.condicao) is not lacuna
        assert ("também recebe clientes" in linha.observacao) is lacuna


def test_uniao_adjacente_cobre_intervalo_posterior_na_mesma_historia():
    arq = parse_text(BASE + regra("A", "recencia de positivacao em 30 dias")
                     + regra("B", "recencia de positivacao entre 31 dias e 60 dias")
                     + regra("Coberto", "recencia de positivacao em 60 dias"))
    info = analisar_arquivo(arq)[arq.parametros[-1].linha_ini]
    assert info.sombreamento_provado and not info.sombreado_sob_hipotese


def test_controle_removido_com_aviso_sem_perder_condicao(tmp_path):
    with pytest.warns(UserWarning, match="controle"):
        assert normalizar("recencia em 21 dias\x01") == "recencia em 21 dias"
    p = escrever(tmp_path, regra("A", "recencia de positivacao em 21 dias\x01"))
    arq = parse_file(p)
    assert not arq.erros and arq.parametros[0].quando[0].texto.endswith("21 dias")
    assert sum("controle" in a.mensagem for a in arq.avisos) == 1
    assert any("controle" in a.mensagem for a in gerar_esqueleto(p).avisos)


def test_glossario_consolidado_sem_venda_rota_ramo_e_alias():
    for atomo in ("sem venda", "sem vendas", "sem venda do vendedor", "sem venda da empresa"):
        t = traduzir_atomo(atomo)
        assert t.status == INFERIDA and "⚠" in t.observacao and "inferida" in t.observacao
    for atomo in ("e o cliente filial",):
        assert traduzir_atomo(normalizar(atomo)).status == ALIAS
    assert traduzir_atomo(normalizar("é o cliente filial")).status == ALIAS
    rota = traduzir_atomo("data da rota na semana")
    assert rota.status == SEM_DEFINICAO and rota.texto == "data da rota na semana"
    assert traduzir_atomo('ramo de atividade igual("12")').status == DEFINIDA
    assert traduzir_atomo('ramo de atividade igual("12")').observacao is None
    assert "⚠" in traduzir_atomo('ramo de atividade igual("distribuidor")').observacao
    venda = GLOSSARIO["nao tem venda da empresa no ano"]
    assert venda.status == COMPOSICAO and any("não tem venda <<" in f.trecho for f in venda.fontes)


@pytest.mark.parametrize("nome", ["V1Vidros-RegraComercial", "regra_049", "regra_209"])
def test_prospect_posterior_recebe_aviso_no_fora(nome):
    e = gerar_esqueleto(DATA / (nome + ".gobr"))
    alertas = [a for a in e.avisos if a.tipo == "prospect_apos_fora"]
    assert len(alertas) == 1
    assert next(l.nome for l in e.linhas if l.linha == alertas[0].linha) == (
        "não agendar clientes fora de recencia em 90 dias" if nome == "regra_209" else "Inativos"
    )
    assert all(a.mensagem == AVISO_PROSPECT for a in alertas)
    assert all(AVISO_PROSPECT in next(l.observacao for l in e.linhas if l.linha == a.linha) for a in alertas)


def test_prospect_anterior_ou_outro_escopo_nao_recebe_aviso(tmp_path):
    p = escrever(tmp_path, regra("Prospect", "no ciclo de vida prospect com a empresa")
                 + regra("Fora", "fora da recencia de positivacao em 30 dias")
                 + regra("Outro prospect", "no ciclo de vida prospect com a empresa", escopo="outro"))
    assert not any(a.tipo == "prospect_apos_fora" for a in gerar_esqueleto(p).avisos)


def test_detector_fora_entre_inclui_composto_e_puro():
    for nome, bloco, condicao in (("regra_108", 34, 36), ("regra_209", 41, 43)):
        e = gerar_esqueleto(DATA / (nome + ".gobr"))
        l = next(l for l in e.linhas if l.linha == bloco)
        assert l.recencia.fora_entre
        assert any(a.tipo == "fora_entre" and a.linha == bloco for a in e.avisos)
        assert "fora do intervalo" in l.condicao
        assert any(c.linha == condicao for p in parse_file(DATA / (nome + ".gobr")).parametros
                   if p.linha_ini == bloco for c in p.quando)


@pytest.mark.parametrize("frequencia,esperado", [
    ("quinzenal()", "Quinzenal (15 dias)"),
    ("do vendedor", "configurada pelo vendedor (padrão 7 dias)"),
    ("do govendas", "frequência padrão do Govendas"),
    ("de ativos da empresa", "frequência de ativos da empresa"),
    ("remover", "Remover frequência parametrizada"),
    ("do vendedor ou de 35 dias", "configurada pelo vendedor (padrão 7 dias) ou 35 dias"),
    ("do historico ou no minimo de 7 dias e no maximo de 30 dias", "frequência do histórico do cliente ou no mínimo de 7 dias e no máximo de 30 dias"),
])
def test_frequencias_e_cascatas(tmp_path, frequencia, esperado):
    assert gerar_esqueleto(escrever(tmp_path, regra("A", frequencia=frequencia))).linhas[0].frequencia == esperado


def test_preferencia_pesos_e_ausencia(tmp_path):
    p = escrever(tmp_path, regra("A") + regra("B")
                 + "    preferencia maior na segunda e normal na terca e menor na sexta\n")
    a, b = gerar_esqueleto(p).linhas
    assert "preferência" not in a.frequencia
    assert "segunda (peso 3), terça (peso 2), sexta (peso 1)" in b.frequencia


def test_antecedentes_truncados_so_na_tabela(tmp_path):
    texto = "".join(regra(f"A{i}", "adimplentes e recencia de positivacao em 60 dias") for i in range(5))
    texto += regra("Recente", "recencia de positivacao em 30 dias")
    l = gerar_esqueleto(escrever(tmp_path, texto)).linhas[-1]
    assert l.antecedentes == tuple(f"A{i}" for i in range(5))
    assert "A0; A1; +3" in l.observacao and "A2" not in l.observacao


def test_extras_comentarios_nomes_e_escape_markdown(tmp_path):
    p = escrever(tmp_path, '# parametros "ignorado":\n' + regra("A|B", frequencia=None)
                 + '\nalerta "Aviso":\n    texto qualquer\ntags "Marca":\n    texto qualquer\n')
    e = gerar_esqueleto(p)
    assert len(e.linhas) == 1 and e.linhas[0].nome == "A|B"
    assert e.linhas[0].frequencia == "Não agendar"
    assert [x["tipo"] for x in e.extras] == ["alerta", "tags"]
    md = renderizar_markdown(e)
    assert "A\\|B" in md and "## Alertas e tags" in md
    assert e.cabecalho["carteira_padrao"] == "carteirafixa do time"


def test_cli_pasta_descobre_arquivos_sem_lista_fixa(tmp_path):
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    for nome in ("novo", "segundo"):
        (entrada / (nome + ".gobr")).write_text(BASE + regra(nome), encoding="utf-8")
    out = tmp_path / "saida"
    assert main([str(entrada), "--out", str(out)]) == 0
    assert {p.stem for p in out.glob("*.md")} == {"novo", "segundo"}


def test_smoke_todos_os_arquivos_e_contagem_de_linhas(capsys):
    caminhos = sorted(DATA.glob("*.gobr"))
    assert len(caminhos) == 249
    total = 0
    for p in caminhos:
        e = gerar_esqueleto(p)
        arq = parse_file(p)
        assert len(e.linhas) == len(arq.parametros), p.name
        assert [l.nome for l in e.linhas] == [p.nome for p in arq.parametros]
        assert renderizar_markdown(e).count("|---|---|---|---|") == 1
        total += len(e.linhas)
    with capsys.disabled():
        print(f"\n[smoke] {len(caminhos)} arquivos; {total} linhas; uma por bloco parametros; sem exceções")


def test_precedentes_so_impuros_da_mesma_cadeia_sem_prospect_ou_bloqueio(tmp_path):
    texto = regra("Bloqueio", "inadimplentes", frequencia=None)
    texto += regra("Prospect", "no ciclo de vida prospect com a empresa e recencia de positivacao em 90 dias")
    texto += regra("Financeiro", "adimplentes")
    texto += regra("Visita", "adimplentes e recencia de visita em 90 dias")
    texto += regra("Vendedor", "adimplentes e recencia de positivacao do vendedor em 90 dias")
    texto += regra("Mesmo histórico", "adimplentes e recencia de positivacao em 90 dias")
    texto += regra("Alvo", "recencia de positivacao em 30 dias")
    e = gerar_esqueleto(escrever(tmp_path, texto))
    alvo = e.linhas[-1]
    assert alvo.antecedentes == ("Mesmo histórico",)
    assert NOTA_BLOQUEIOS in alvo.observacao
    assert "pode haver clientes já tratados pela regra Mesmo histórico" in alvo.observacao
    assert "regra Bloqueio" not in alvo.observacao and "regra Prospect" not in alvo.observacao


def test_bloqueio_em_outro_escopo_nao_gera_nota(tmp_path):
    p = escrever(tmp_path, regra("Bloqueio", "inadimplentes", frequencia=None, escopo="outro")
                 + regra("Alvo", "recencia de positivacao em 30 dias"))
    assert NOTA_BLOQUEIOS not in gerar_esqueleto(p).linhas[-1].observacao


def test_fora_entre_literal_e_aviso_em_todos_os_blocos():
    detectados = []
    for p in DATA.glob("*.gobr"):
        for l in gerar_esqueleto(p).linhas:
            if l.recencia.fora_entre:
                detectados.append((p.name, l.linha))
                assert "fora do intervalo de " in l.condicao
                assert "⚠ pelo manual, 'fora ... entre' exclui o intervalo " in l.observacao
                assert "(não confirmado)" in l.observacao
    assert len(detectados) == 30
    assert len({nome for nome, _ in detectados}) == 13


@pytest.mark.parametrize("nome,linha,trecho", [
    ("regra_188", 39, "última compra fora do intervalo de 31 a 45 dias (algum vendedor do mesmo grupo)"),
    ("regra_209", 41, "última compra fora do intervalo de 31 a 90 dias (pelo vendedor)"),
    ("regra_003", 58, "última compra fora do intervalo de 15 a 90 dias (qualquer vendedor da empresa)"),
])
def test_fora_entre_linhas_solicitadas(nome, linha, trecho):
    l = next(l for l in gerar_esqueleto(DATA / (nome + ".gobr")).linhas if l.linha == linha)
    assert trecho in l.condicao
    assert "(não confirmado)" in l.observacao


@pytest.mark.parametrize("nome,linhas", [
    ("regra_032", {521, 523}),
])
def test_banner_sintaxe_inclui_diagnosticos_e_linhas(nome, linhas):
    e = gerar_esqueleto(DATA / (nome + ".gobr"))
    assert {n for n, _ in e.cabecalho["problemas_sintaxe"]} == linhas
    md = renderizar_markdown(e)
    assert md.startswith("> ⚠ arquivo com erro de sintaxe: ")
    assert "a tabela pode estar incompleta" in md.splitlines()[0]
    assert all(f"linha {n}:" in md.splitlines()[0] for n in linhas)


def test_controle_corrigido_nao_gera_banner_sintaxe():
    e = gerar_esqueleto(DATA / "regra_140.gobr")
    assert not e.cabecalho["problemas_sintaxe"]
    assert not renderizar_markdown(e).startswith("> ⚠ arquivo com erro de sintaxe")
    assert "> ⚠ aviso: linha 131: caracteres de controle removidos" in renderizar_markdown(e)


@pytest.mark.parametrize("nome,linha", [("regra_221", 48), ("V1Vidros-RegraComercial", 1), ("regra_140", 131)])
def test_nota_leve_abaixo_do_titulo(nome, linha):
    e = gerar_esqueleto(DATA / (nome + ".gobr"))
    md = renderizar_markdown(e)
    assert e.cabecalho["nivel_diagnostico"] == "aviso"
    assert md.startswith("# " + nome + ".gobr\n\n> ⚠ aviso:")
    assert f"linha {linha}:" in md.splitlines()[2]
    assert md.count("> ⚠ aviso:") == 1 and "tabela pode estar incompleta" not in md


def test_recencia_positiva_na_mesma_cadeia_suprime_aviso(tmp_path):
    p = escrever(tmp_path, regra("Misto", "recencia de positivacao em 45 dias e fora da recencia de positivacao em 30 dias")
                 + regra("Prospect", "no ciclo de vida prospect com a empresa"))
    assert not any(a.tipo == "prospect_apos_fora" for a in gerar_esqueleto(p).avisos)


@pytest.mark.parametrize("literal", ["inatividade global maior que 149 dias", "tem venda no mes"])
def test_formas_nao_documentadas_permanecem_literais(tmp_path, literal):
    assert traduzir_atomo(literal).status is None
    assert gerar_esqueleto(escrever(tmp_path, regra("Literal", literal))).linhas[0].condicao == literal


def test_fontes_adicionadas_do_manual():
    assert [(f.pdf, f.impressa) for f in GLOSSARIO["tem venda em N dias"].fontes] == [(54, 50)]
    assert [(f.pdf, f.impressa) for f in GLOSSARIO["no ciclo de vida ativado com o vendedor"].fontes] == [(33, 29)]
    assert [(f.pdf, f.impressa) for f in GLOSSARIO["no ciclo de vida reativado com a empresa"].fontes] == [(33, 29)]
    assert [(f.pdf, f.impressa) for f in GLOSSARIO["curva a com o vendedor"].fontes] == [(32, 28)]
