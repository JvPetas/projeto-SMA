"""Pacote temporário, conteúdo permitido e preenchimento opcional do modelo."""
import json
from pathlib import Path
import zipfile

import pytest

from scripts import empacotar_entrega1 as pacote
from scripts import gerar_explicacoes as lote


def preparar(tmp_path):
    raiz = tmp_path / "projeto"
    entrada = raiz / "data/gobr"
    entrada.mkdir(parents=True)
    base = 'version 1.0\ntime "t":\n    vendedores todos\n'
    texto = base + 'parametros "Clientes":\n    do time("t")\n    quando sem venda\n    frequencia de 7 dias\n'
    for nome in ("primeiro", "copia", "terceiro"):
        (entrada / (nome + ".gobr")).write_text(texto, encoding="utf-8")
    pares = raiz / "data/pairs.json"
    pares.write_text(json.dumps([{"gobr": "terceiro.gobr", "gabarito": True}]), encoding="utf-8")
    saida = raiz / "data/processed/explicacoes"
    lote.gerar_lote(entrada, saida, pares=pares, pasta_gold=None)
    fontes = raiz / "src/gobr_agent"
    fontes.mkdir(parents=True)
    (fontes / "__init__.py").write_text('"""Regras."""\n', encoding="utf-8")
    scripts = raiz / "scripts"
    scripts.mkdir()
    (scripts / "gerar_explicacoes.py").write_text("print('regras')\n", encoding="utf-8")
    (raiz / "pyproject.toml").write_text('[project]\nname = "regras"\n', encoding="utf-8")
    docs = raiz / "docs"
    docs.mkdir()
    (docs / "entrega1_README.template.md").write_text(
        "# Entrega\n{n_arquivos} arquivos; {n_sem_venda} sem venda; {n_falhas} falhas.\n"
        "{marcador_futuro}\n<!-- IF polimento -->\n## Revisão\n"
        "{modelo_polimento}: {n_polidas} / {n_fallback}\n<!-- ENDIF -->\n", encoding="utf-8")
    return raiz, fontes


def test_pacote_tres_origens_com_duplicado_e_exclusoes(tmp_path, capsys):
    raiz, fontes = preparar(tmp_path)
    for relativo in (".env", ".env.local", "data/oculto.gobr", "manual/copia.pdf", "__pycache__/cache.pyc"):
        p = fontes / relativo
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("excluído", encoding="utf-8")
    resultado = pacote.empacotar(raiz)
    assert resultado["n_explicacoes"] == resultado["n_gobr"] == 3
    assert all(resultado["checagens"].values())
    assert resultado["tamanho_bytes"] == Path(resultado["zip"]).stat().st_size
    assert "3 arquivos; 3 sem venda; 0 falhas." in resultado["readme"]
    assert "{marcador_futuro}" in resultado["readme"] and "## Revisão" not in resultado["readme"]
    with zipfile.ZipFile(resultado["zip"]) as z:
        assert {n for n in z.namelist() if n.startswith("explicacoes/")} == {
            "explicacoes/primeiro.md", "explicacoes/copia.md", "explicacoes/terceiro.md"}
        assert "codigo/src/gobr_agent/__init__.py" in z.namelist()
        assert "codigo/scripts/gerar_explicacoes.py" in z.namelist()
        assert "codigo/pyproject.toml" in z.namelist()
        assert "explicacoes_consolidado.md" in z.namelist()
        for nome in z.namelist():
            assert not pacote._excluido(Path(nome))
            assert z.read(nome) == (Path(resultado["pasta"]) / nome).read_bytes()
    # Uma execução nova remove apenas artefatos obsoletos da pasta gerada.
    (Path(resultado["pasta"]) / "obsoleto.txt").write_text("antigo", encoding="utf-8")
    novo = pacote.empacotar(raiz)
    assert not (Path(novo["pasta"]) / "obsoleto.txt").exists()
    assert not list((raiz / "data/processed").glob(".entrega1-*"))
    pacote.imprimir_relatorio(novo)
    saida = capsys.readouterr().out
    assert "md_igual_gobr: OK" in saida and "Tamanho:" in saida and "README preenchido:" in saida


@pytest.mark.parametrize("problema", ["falta_md", "sobra_md", "index", "cabecalho", "falha_lote"])
def test_inconsistencias_impedem_publicacao(tmp_path, problema):
    raiz, _ = preparar(tmp_path)
    saida = raiz / "data/processed/explicacoes"
    if problema == "falta_md":
        (saida / "copia.md").unlink()
    elif problema == "sobra_md":
        (saida / "antigo.md").write_text(pacote.CABECALHO, encoding="utf-8")
    elif problema == "cabecalho":
        (saida / "copia.md").write_text("# Sem tabela", encoding="utf-8")
    else:
        index = json.loads((saida / "index.json").read_text(encoding="utf-8"))
        if problema == "index":
            index["resumo"]["arquivos"] += 1
        else:
            index["resumo"]["arquivos_com_falhas"] = 1
        (saida / "index.json").write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(ValueError):
        pacote.empacotar(raiz)
    assert not (raiz / "data/processed/entrega1.zip").exists()


@pytest.mark.parametrize("termo", pacote.TERMOS_PROIBIDOS)
def test_termo_em_qualquer_codigo_rejeita_e_preserva_pacote_anterior(tmp_path, termo):
    raiz, fontes = preparar(tmp_path)
    anterior = pacote.empacotar(raiz)
    zip_antes = Path(anterior["zip"]).read_bytes()
    (fontes / "referencia.py").write_bytes(b"# " + termo.upper())
    with pytest.raises(ValueError, match="termo proibido"):
        pacote.empacotar(raiz)
    assert Path(anterior["zip"]).read_bytes() == zip_antes
    assert not (Path(anterior["pasta"]) / "codigo/src/gobr_agent/referencia.py").exists()


@pytest.mark.parametrize("nome", ["anexo.env", "dados.gobr", "manual.pdf"])
def test_verificador_inspeciona_todos_os_membros_do_zip(tmp_path, nome):
    p = tmp_path / "arbitrario.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("codigo/" + nome, "conteúdo")
    with pytest.raises(ValueError, match="arquivo proibido"):
        pacote.verificar_zip(p, set())


def test_modelo_tolerante_condicionais_e_contadores_sem_numeros_fixos():
    modelo = "{n_arquivos}; {futuro}\n<!-- IF polimento -->{modelo_polimento}: {n_polidas}, {n_fallback}<!-- ENDIF -->"
    index = {"resumo": {"arquivos": 8}}
    assert pacote.preencher_readme(modelo, index) == "8; {futuro}\n"
    index["polimento"] = {"modelo_polimento": "revisao", "n_polidas": 7}
    assert pacote.preencher_readme(modelo, index) == "8; {futuro}\n"
    index["polimento"]["n_fallback"] = 0
    assert pacote.preencher_readme(modelo, index) == "8; {futuro}\nrevisao: 7, 0"
    assert pacote.preencher_readme("<!-- IF ausente -->não entra<!-- ENDIF -->", {}) == ""
    assert pacote.preencher_readme("{n_polidas} / {n_fallback}", {}) == "{n_polidas} / {n_fallback}"
    index["resumo"].update(blocos_por_aviso={"glossario_INFERIDA": 6, "fora_entre": 3,
                                          "glossario_SEM_ENTRADA": 4},
                            blocos_sem_definicao=5, falhas_por_checagem={"frequencia": 2, "linhas": 1})
    assert pacote.preencher_readme("{n_sem_venda} {n_fora_entre} {n_sem_entrada} {n_falhas}", index) == "6 3 5 3"


def test_cli_e_falha_explicita(tmp_path, capsys):
    raiz, _ = preparar(tmp_path)
    assert pacote.main(["--root", str(raiz)]) == 0
    assert "Explicações .md: 3" in capsys.readouterr().out
    assert pacote.main(["--root", str(tmp_path / "ausente")]) == 1
    assert "FALHA:" in capsys.readouterr().err


def test_fontes_readme_segue_ordem_pares_extrai_so_tabela_e_e_idempotente(tmp_path):
    raiz, _ = preparar(tmp_path)
    (raiz / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.12"\n', encoding="utf-8")
    pares = [{"gobr": "primeiro.gobr", "gabarito": False},
             {"gobr": "terceiro.gobr", "gabarito": True}, {"gobr": "copia.gobr", "gabarito": True}]
    (raiz / "data/pairs.json").write_text(json.dumps(pares), encoding="utf-8")
    md = raiz / "data/processed/explicacoes/terceiro.md"
    md.write_text(md.read_text(encoding="utf-8").replace("# terceiro.gobr", "# terceiro.gobr\n\n> ⚠ aviso: version ausente")
                  + "\n## Extras\nfora da tabela\n", encoding="utf-8")
    modelo = raiz / "docs/entrega1_README.template.md"
    modelo.write_text("## Como ler a tabela\nTexto\n\n## Exemplo\nExplicação gerada para um dos exemplos do professor:\n\n"
                      "{exemplo_gold}\n\n## Como reproduzir\nRequer Python {python_requer}.\n", encoding="utf-8")
    antes = modelo.read_bytes()
    a, b = pacote.empacotar(raiz), pacote.empacotar(raiz)
    assert a["readme"] == b["readme"] and modelo.read_bytes() == antes
    assert a["arquivo_exemplo_gold"] == "terceiro.gobr" and a["python_requer"] == ">=3.12"
    assert "Requer Python >=3.12" in a["readme"] and a["readme"].count("## Exemplo") == 1
    assert "⚠ aviso:" not in a["readme"] and "fora da tabela" not in a["readme"]
    assert pacote.CABECALHO in a["readme"] and "provavelmente nunca compraram" in a["readme"]


def test_condicional_polimento_depende_da_pasta_e_varredura_inclui_diff(tmp_path):
    raiz, _ = preparar(tmp_path)
    modelo = raiz / "docs/entrega1_README.template.md"
    modelo.write_text("<!-- IF tem_polimento -->versão polida<!-- ENDIF -->\n"
                      "<!-- IF tem_polimento -->{modelo_polimento}: {n_polidas} de {n_linhas_polidaveis}; {n_fallback}<!-- ENDIF -->", encoding="utf-8")
    assert "versão polida" not in pacote.empacotar(raiz)["readme"]
    polidas = raiz / "data/processed/explicacoes_polidas"
    polidas.mkdir()
    (polidas / "terceiro.md").write_text(pacote.CABECALHO + "\n|---|---|---|---|\n", encoding="utf-8")
    (polidas / "index.json").write_text(json.dumps({"polimento": {"modelo_polimento": "teste",
        "n_polidas": 0, "n_linhas_polidaveis": 1, "n_fallback": 1}}), encoding="utf-8")
    diff = raiz / "data/processed/polimento_diff.md"
    diff.write_text("# Alterações", encoding="utf-8")
    r = pacote.empacotar(raiz)
    assert "versão polida" in r["readme"] and "teste: 0 de 1; 1" in r["readme"]
    assert "explicacoes_polidas/terceiro.md" in r["membros"] and "polimento_diff.md" in r["membros"]
    for p in (diff, polidas / "terceiro.md"):
        antes = p.read_bytes()
        p.write_bytes(antes + pacote.TERMOS_PROIBIDOS[0])
        with pytest.raises(ValueError, match="termo proibido"):
            pacote.empacotar(raiz)
        p.write_bytes(antes)


@pytest.mark.parametrize("conteudo", [None, " \n\t", "- Divergência de referência sintética.\n\n- Segundo item."])
def test_notas_gabarito_opcionais_no_readme(tmp_path, conteudo):
    raiz, _ = preparar(tmp_path)
    # Usa o modelo real, sem introduzir texto dos exemplos de referência no teste.
    modelo = raiz / "docs/entrega1_README.template.md"
    modelo.write_bytes((Path(__file__).resolve().parents[1] / "docs/entrega1_README.template.md").read_bytes())
    (raiz / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.10"\n', encoding="utf-8")
    notas = raiz / "data/processed/notas_gabarito.md"
    if conteudo is not None:
        notas.write_text(conteudo, encoding="utf-8")
    modelo_antes = modelo.read_bytes()
    resultado = pacote.empacotar(raiz)
    titulo = "## Divergências entre a descrição e o código nos exemplos de referência"
    esperado = bool(conteudo and conteudo.strip())
    assert resultado["readme"].count(titulo) == int(esperado)
    assert "{notas_gabarito}" not in resultado["readme"]
    if esperado:
        assert conteudo.strip() in resultado["readme"]
    assert modelo.read_bytes() == modelo_antes
    if conteudo is not None:
        assert notas.read_text(encoding="utf-8") == conteudo
    with zipfile.ZipFile(resultado["zip"]) as z:
        assert z.read("README.md").decode("utf-8").splitlines() == resultado["readme"].splitlines()
    if esperado:
        notas.unlink()
        sem_notas = pacote.empacotar(raiz)["readme"]
        assert titulo not in sem_notas and conteudo.strip() not in sem_notas
