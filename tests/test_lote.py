"""Lote temporário, fontes de referência e verificações independentes do Markdown."""
import json
from pathlib import Path

import pytest

from scripts import gerar_explicacoes as lote


BASE = 'version 1.0\ntime "t":\n    vendedores todos\n'


def regra(nome, condicao, dias=7):
    return f'parametros "{nome}":\n    do time("t")\n    quando {condicao}\n    frequencia de {dias} dias\n'


def preparar(tmp_path):
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    simples = BASE + regra("Mercado", 'ramo de atividade igual("atacado")')
    cadeia = BASE + regra("Recente", "recencia de positivacao em 60 dias", 14)
    cadeia += regra("Anterior", "recencia de positivacao em 90 dias", 7)
    for nome, texto in (("origem", simples), ("referencia", cadeia), ("replica", simples)):
        (entrada / (nome + ".gobr")).write_text(texto, encoding="utf-8")
    pares = tmp_path / "pairs.json"
    pares.write_text(json.dumps([{"gobr": "referencia.gobr", "gabarito": True}]), encoding="utf-8")
    return entrada, tmp_path / "saida", pares


def test_tres_arquivos_duas_geracoes_index_e_consolidado(tmp_path, monkeypatch):
    entrada, saida, pares = preparar(tmp_path)
    original = lote.gerar_esqueleto
    chamadas = []

    def contar(p):
        chamadas.append(p.name)
        return original(p)

    monkeypatch.setattr(lote, "gerar_esqueleto", contar)
    index, textos = lote.gerar_lote(entrada, saida, pares=pares, pasta_gold=None)
    assert len(chamadas) == 2
    assert index == json.loads((saida / "index.json").read_text(encoding="utf-8"))
    assert index["fonte_gold"] == str(pares)
    assert index["gold"] == ["referencia.gobr"]
    assert index["resumo"]["arquivos"] == 3 and index["resumo"]["conteudos_distintos"] == 2
    assert not index["resumo"]["arquivos_com_falhas"]
    registros = {r["arquivo"]: r for r in index["arquivos"]}
    assert registros["replica.gobr"]["duplicata_de"] == "origem.gobr"
    assert registros["replica.gobr"]["hash"] == registros["origem.gobr"]["hash"]
    assert len(registros["origem.gobr"]["hash"]) == 64
    assert registros["referencia.gobr"]["papel"] == "gold"
    assert index["para_indexar"] == ["origem.gobr"]
    for r in registros.values():
        assert r["n_blocos"] == r["n_linhas"]
        assert all(c["ok"] for c in r["checagens"].values())
        assert r["nivel_diagnostico"] == "nenhum"
        assert (saida / Path(r["arquivo"]).with_suffix(".md")).exists()
    assert registros["origem.gobr"]["ramo_atividade_texto"]
    assert registros["replica.gobr"]["atomos_ramo_texto"][0]["ramo_atividade_texto"]
    assert not registros["referencia.gobr"]["ramo_atividade_texto"]
    assert textos["replica.gobr"].startswith("# replica.gobr\n")
    assert textos["origem.gobr"].splitlines()[1:] == textos["replica.gobr"].splitlines()[1:]
    doc = (saida.parent / "explicacoes_consolidado.md").read_text(encoding="utf-8")
    assert "## Sumário" in doc
    assert doc.index("[origem.gobr]") < doc.index("[referencia.gobr]") < doc.index("[replica.gobr]")
    assert all(texto.strip() in doc for texto in textos.values())


def test_fonte_pares_tem_prioridade_e_fallback_usa_nome_base(tmp_path):
    entrada, saida, pares = preparar(tmp_path)
    gold = tmp_path / "gold"
    gold.mkdir()
    (gold / "origem.md").write_text("# Referência", encoding="utf-8")
    index, _ = lote.gerar_lote(entrada, saida, pares=pares, pasta_gold=gold)
    assert index["gold"] == ["referencia.gobr"] and index["fonte_gold"] == str(pares)
    pares.write_text("[]", encoding="utf-8")
    index, _ = lote.gerar_lote(entrada, saida, pares=pares, pasta_gold=gold)
    assert index["gold"] == ["origem.gobr"] and index["fonte_gold"] == str(gold)
    assert "replica.gobr" not in index["para_indexar"]
    assert all(not r["indexar"] for r in index["arquivos"] if r["hash"] == index["arquivos"][0]["hash"])


def test_sem_fonte_gold_para_antes_de_escrever(tmp_path):
    entrada, saida, pares = preparar(tmp_path)
    pares.write_text("[]", encoding="utf-8")
    with pytest.raises(lote.FonteGoldAusente, match="Fonte gold ausente"):
        lote.gerar_lote(entrada, saida, pares=pares, pasta_gold=tmp_path / "ausente")
    assert not saida.exists()


def test_pares_invalidos_nao_sao_substituidos_silenciosamente(tmp_path):
    entrada, saida, pares = preparar(tmp_path)
    pares.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="esperado um array"):
        lote.gerar_lote(entrada, saida, pares=pares, pasta_gold=None)
    assert not saida.exists()


def test_verificacao_detecta_frequencia_numero_e_linha_adulterados(tmp_path):
    entrada, _, _ = preparar(tmp_path)
    caminho = entrada / "referencia.gobr"
    md = lote.renderizar_markdown(lote.gerar_esqueleto(caminho))
    checks, _, _, _ = lote.verificar(caminho, md)
    assert all(c["ok"] for c in checks.values())
    alterado = md.replace("| 14 dias |", "| 999 dias |", 1)
    checks, _, _, _ = lote.verificar(caminho, alterado)
    assert not checks["frequencia"]["ok"] and checks["numeros_condicao"]["ok"]
    alterado = md.replace("última compra até 60 dias", "última compra até 999 dias", 1)
    checks, _, _, _ = lote.verificar(caminho, alterado)
    assert not checks["numeros_condicao"]["ok"] and checks["frequencia"]["ok"]
    linha = next(l for l in md.splitlines() if l.startswith("| Recente |"))
    checks, _, _, _ = lote.verificar(caminho, md.replace(linha + "\n", ""))
    assert not checks["linhas_parametros"]["ok"]


def test_excecao_fica_no_indice_inclusive_para_duplicados(tmp_path, monkeypatch, capsys):
    entrada, saida, pares = preparar(tmp_path)
    original = lote.gerar_esqueleto
    chamadas = []

    def falhar(p):
        chamadas.append(p.name)
        if p.name == "origem.gobr":
            raise ValueError("falha de verificação explícita")
        return original(p)

    monkeypatch.setattr(lote, "gerar_esqueleto", falhar)
    index, textos = lote.gerar_lote(entrada, saida, pares=pares, pasta_gold=None)
    assert len(chamadas) == 2 and index["resumo"]["arquivos_com_falhas"] == 2
    assert index["resumo"]["falhas_por_checagem"]["sem_excecao"] == 2
    assert len(index["arquivos"]) == 3
    assert all(not r["indexar"] for r in index["arquivos"])
    lote.imprimir_relatorio(index, textos)
    assert "FALHA origem.gobr" in capsys.readouterr().out


def test_meses_pivo_e_preferencia_verificados_sem_renderer_como_expectativa(tmp_path):
    p = tmp_path / "arbitrario.gobr"
    texto = BASE + regra("Agenda", "adimplentes")
    texto = texto.replace("de 7 dias", "quinzenal('2026-01-01')")
    texto += "    preferencia maior na segunda e menor no sabado\n"
    p.write_text(texto, encoding="utf-8")
    md = lote.renderizar_markdown(lote.gerar_esqueleto(p))
    checks, _, _, _ = lote.verificar(p, md)
    assert checks["frequencia"]["ok"]
    checks, _, _, _ = lote.verificar(p, md.replace("peso 3", "peso 2"))
    assert not checks["frequencia"]["ok"]
