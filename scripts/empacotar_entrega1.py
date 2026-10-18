"""Monta e verifica o pacote da Entrega 1 a partir do lote e de seu índice."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CABECALHO = "| Nome | Condição | Frequência | Observação |"
MARCADOR = re.compile(r"\{([a-zA-Z_][a-zA-Z_0-9]*)\}")
CONDICIONAL = re.compile(
    r"<!--\s*IF\s+(\w+)\s*-->((?:(?!<!--\s*IF\b).)*?)<!--\s*ENDIF\s*-->", re.S
)
TERMOS_PROIBIDOS = (b"claude", b"anthropic", b"api_key")
PARTES_EXCLUIDAS = {"__pycache__", "data", "manual", ".git", ".venv"}


def dados_readme(index: dict) -> dict:
    """Números do lote vêm somente do índice; campos opcionais continuam opcionais."""
    dados = {k: v for k, v in index.items() if not isinstance(v, (dict, list)) and v is not None}
    # Um futuro trecho pode fornecer seus marcadores em um objeto próprio.
    for valor in index.values():
        if isinstance(valor, dict):
            dados.update({k: v for k, v in valor.items() if not isinstance(v, (dict, list)) and v is not None})
    dados.update({k: v for k, v in index.items() if isinstance(v, dict) and v})
    resumo = index.get("resumo", {})
    if "arquivos" in resumo:
        dados["n_arquivos"] = resumo["arquivos"]
    contagens = resumo.get("blocos_por_aviso", resumo.get("avisos_por_tipo"))
    if contagens is not None:
        dados["n_sem_venda"] = contagens.get("glossario_INFERIDA", 0)
        dados["n_fora_entre"] = contagens.get("fora_entre", 0)
        dados["n_sem_entrada"] = resumo.get("blocos_sem_definicao", contagens.get("glossario_SEM_ENTRADA", 0))
    if "falhas_por_checagem" in resumo:
        dados["n_falhas"] = sum(resumo["falhas_por_checagem"].values())
    return dados


def preencher_readme(modelo: str, index: dict, *, dados_adicionais: dict | None = None) -> str:
    """Preserva {marcador} desconhecido. <!-- IF chave -->...<!-- ENDIF --> é opcional.

    A seção só entra se a chave for verdadeira e todos os seus marcadores tiverem
    dados. Zero é um dado válido para marcadores, inclusive em seções aninhadas.
    """
    dados = dados_readme(index)
    dados.update(dados_adicionais or {})

    def incluir(m):
        chave, trecho = m.groups()
        completo = all(nome in dados for nome in MARCADOR.findall(trecho))
        return trecho if dados.get(chave) and completo else ""

    while CONDICIONAL.search(modelo):
        modelo = CONDICIONAL.sub(incluir, modelo)
    return MARCADOR.sub(lambda m: str(dados[m[1]]) if m[1] in dados else m[0], modelo)


def fontes_readme(raiz: Path) -> dict:
    """Lê o requisito Python e a tabela do primeiro gold na ordem dos pares."""
    texto = (raiz / "pyproject.toml").read_text(encoding="utf-8")
    try:
        import tomllib
    except ImportError:  # O gerador também roda em Python 3.10.
        # O campo PEP 440 é uma string simples, dentro da seção project.
        secao = re.search(r"(?ms)^\[project\][ \t]*\n(.*?)(?=^\[|\Z)", texto)
        requisito = re.search(r'''(?m)^requires-python\s*=\s*(?:"([^"\n]+)"|'([^'\n]+)')[ \t]*(?:\#.*)?$''', secao[1]) if secao else None
        python_requer = next((v for v in requisito.groups() if v is not None), None) if requisito else None
    else:
        python_requer = tomllib.loads(texto).get("project", {}).get("requires-python")
    if not isinstance(python_requer, str) or not python_requer.strip():
        raise ValueError("project.requires-python ausente no pyproject.toml")
    pares = json.loads((raiz / "data/pairs.json").read_text(encoding="utf-8-sig"))
    if not isinstance(pares, list):
        raise ValueError("data/pairs.json: esperado um array de pares")
    primeiro = next((p for p in pares if isinstance(p, dict) and p.get("gabarito") is True), None)
    if primeiro is None:
        raise ValueError("data/pairs.json: nenhum gold marcado")
    nome = primeiro.get("gobr")
    if not isinstance(nome, str) or Path(nome).name != nome or not nome.endswith(".gobr"):
        raise ValueError("data/pairs.json: nome-base do primeiro gold inválido")
    markdown = (raiz / "data/processed/explicacoes" / Path(nome).with_suffix(".md")).read_text(encoding="utf-8")
    linhas = markdown.splitlines()
    try:
        inicio = linhas.index(CABECALHO)
    except ValueError:
        raise ValueError("primeiro gold sem cabeçalho de tabela") from None
    tabela = []
    for linha in linhas[inicio:]:
        if not linha.startswith("|"):
            break
        tabela.append(linha)
    if len(tabela) < 2 or not re.fullmatch(r"\|(?:\s*:?-+:?\s*\|){4}", tabela[1]):
        raise ValueError("primeiro gold sem separador de tabela válido")
    return {"python_requer": python_requer, "exemplo_gold": "\n".join(tabela), "arquivo_exemplo_gold": nome}


def _excluido(p: PurePosixPath) -> bool:
    partes = [x.casefold() for x in p.parts]
    return (any(x in PARTES_EXCLUIDAS or x.endswith(".env") or x.startswith(".env.") for x in partes)
            or p.suffix.casefold() in {".pdf", ".gobr", ".pyc", ".pyo"})


def _dentro(raiz: Path, caminho: Path) -> None:
    if not caminho.resolve().is_relative_to(raiz.resolve()) or caminho.resolve() == raiz.resolve():
        raise ValueError(f"caminho fora da pasta autorizada: {caminho}")


@contextmanager
def _pasta_temporaria(processado: Path):
    pasta = processado / (".entrega1-" + uuid.uuid4().hex)
    _dentro(processado, pasta)
    pasta.mkdir()
    try:
        yield pasta
    finally:
        _dentro(processado, pasta)
        shutil.rmtree(pasta)


def verificar_zip(caminho: Path, esperados: set[str]) -> dict:
    """Verifica também os bytes de cada membro, inclusive os arquivos de código."""
    falhas, explicacoes = [], set()
    with zipfile.ZipFile(caminho) as z:
        if z.testzip() is not None:
            falhas.append("ZIP com CRC inválido")
        nomes = z.namelist()
        if len(nomes) != len(set(nomes)):
            falhas.append("membros duplicados no ZIP")
        for nome in nomes:
            p = PurePosixPath(nome)
            if p.is_absolute() or ".." in p.parts or "\\" in nome or _excluido(p):
                falhas.append(f"arquivo proibido: {nome}")
            bruto = z.read(nome)
            if any(termo in bruto.lower() or termo in nome.encode("utf-8").lower() for termo in TERMOS_PROIBIDOS):
                falhas.append(f"termo proibido: {nome}")
            if p.parts[0] in {"explicacoes", "explicacoes_polidas"} and p.suffix == ".md":
                if p.parts[0] == "explicacoes":
                    explicacoes.add(p.name)
                if CABECALHO not in bruto.decode("utf-8").splitlines():
                    falhas.append(f"cabeçalho de tabela ausente: {nome}")
        if explicacoes != esperados:
            falhas.append(f"explicações diferentes das origens: faltam={sorted(esperados - explicacoes)}; sobram={sorted(explicacoes - esperados)}")
    if falhas:
        raise ValueError("\n".join(falhas))
    return {"n_explicacoes": len(explicacoes), "n_arquivos_zip": len(nomes), "membros": sorted(nomes),
            "checagens": {"md_igual_gobr": True, "cabecalhos": True, "arquivos_permitidos": True,
                          "termos_proibidos_ausentes": True, "integridade_zip": True}}


def empacotar(raiz: Path, *, modelo: Path | None = None) -> dict:
    raiz = Path(raiz).resolve()
    processado = raiz / "data/processed"
    explicacoes = processado / "explicacoes"
    index = json.loads((explicacoes / "index.json").read_text(encoding="utf-8"))
    origens = sorted((raiz / "data/gobr").glob("*.gobr"))
    esperados = {p.stem + ".md" for p in origens}
    encontrados = {p.name for p in explicacoes.glob("*.md")}
    indexados = {Path(r["arquivo"]).stem + ".md" for r in index["arquivos"]}
    if (not origens or encontrados != esperados or indexados != esperados
            or len(index["arquivos"]) != len(origens) or index["resumo"]["arquivos"] != len(origens)):
        raise ValueError("contagem ou nomes dos .md, .gobr e index.json divergem")
    if index["resumo"].get("arquivos_com_falhas"):
        raise ValueError("o índice registra falhas de geração ou verificação")
    modelo = Path(modelo) if modelo else raiz / "docs/entrega1_README.template.md"
    modelo_texto = modelo.read_text(encoding="utf-8")
    contexto = fontes_readme(raiz) if any(m in modelo_texto for m in ("{python_requer}", "{exemplo_gold}")) else {}
    contexto["tem_polimento"] = (processado / "explicacoes_polidas").is_dir()
    relatorio_polimento = processado / "explicacoes_polidas/index.json"
    if contexto["tem_polimento"] and relatorio_polimento.is_file():
        contexto.update(dados_readme(json.loads(relatorio_polimento.read_text(encoding="utf-8"))))
        contexto["tem_polimento"] = True
    notas_gabarito = processado / "notas_gabarito.md"
    contexto["notas_gabarito"] = (
        notas_gabarito.read_text(encoding="utf-8").strip() if notas_gabarito.is_file() else ""
    )
    readme = preencher_readme(modelo_texto, index, dados_adicionais=contexto)
    destino, zip_final = processado / "entrega1", processado / "entrega1.zip"
    _dentro(raiz, processado)
    # Publica só depois das verificações, mantendo o pacote anterior se houver falha.
    with _pasta_temporaria(processado) as temporario:
        stage = Path(temporario) / "entrega1"
        stage.mkdir()

        def copiar(origem, relativo):
            _dentro(raiz, origem)
            alvo = stage / relativo
            alvo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origem, alvo)

        for nome in sorted(esperados):
            copiar(explicacoes / nome, Path("explicacoes") / nome)
        copiar(processado / "explicacoes_consolidado.md", Path("explicacoes_consolidado.md"))
        if contexto["tem_polimento"]:
            for p in sorted((processado / "explicacoes_polidas").glob("*.md")):
                copiar(p, Path("explicacoes_polidas") / p.name)
            if (processado / "polimento_diff.md").is_file():
                copiar(processado / "polimento_diff.md", Path("polimento_diff.md"))
        (stage / "README.md").write_text(readme, encoding="utf-8")
        pacote = raiz / "src/gobr_agent"
        if not pacote.is_dir():
            raise ValueError(f"código ausente: {pacote}")
        for p in sorted(pacote.rglob("*")):
            relativo = p.relative_to(raiz)
            if not _excluido(PurePosixPath(relativo.as_posix())) and p.is_file():
                copiar(p, Path("codigo") / relativo)
        for relativo in (Path("scripts/gerar_explicacoes.py"), Path("pyproject.toml")):
            copiar(raiz / relativo, Path("codigo") / relativo)
        zip_stage = Path(temporario) / "entrega1.zip"
        with zipfile.ZipFile(zip_stage, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for p in sorted(stage.rglob("*")):
                if p.is_file():
                    z.write(p, p.relative_to(stage).as_posix())
        resultado = verificar_zip(zip_stage, esperados)
        resultado.update(n_gobr=len(origens), tamanho_bytes=zip_stage.stat().st_size,
                         pasta=str(destino), zip=str(zip_final), readme=readme,
                         arquivo_exemplo_gold=contexto.get("arquivo_exemplo_gold"), python_requer=contexto.get("python_requer"))
        _dentro(processado, destino)
        _dentro(processado, zip_final)
        if destino.exists():
            shutil.rmtree(destino)
        shutil.move(str(stage), str(destino))
        zip_stage.replace(zip_final)
    return resultado


def imprimir_relatorio(resultado: dict) -> None:
    print(f"Explicações .md: {resultado['n_explicacoes']}; origens .gobr: {resultado['n_gobr']}")
    if resultado.get("arquivo_exemplo_gold"):
        print("Exemplo gold (ordem de data/pairs.json): " + resultado["arquivo_exemplo_gold"])
        print("Python requerido (pyproject.toml): " + resultado["python_requer"])
    for nome, ok in resultado["checagens"].items():
        print(f"{nome}: {'OK' if ok else 'FALHA'}")
    print(f"ZIP: {resultado['zip']}")
    print(f"Tamanho: {resultado['tamanho_bytes']} bytes ({resultado['tamanho_bytes'] / 1024:.2f} KiB)")
    print("Árvore resumida do ZIP:")
    print("entrega1/")
    print(f"  explicacoes/ ({resultado['n_explicacoes']} arquivos .md)")
    for nome in resultado["membros"]:
        if not nome.startswith("explicacoes/"):
            print("  " + nome)
    print("\nREADME preenchido:\n")
    print(resultado["readme"], end="")


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--root", type=Path, default=ROOT)
    cli.add_argument("--modelo", type=Path)
    args = cli.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        resultado = empacotar(args.root, modelo=args.modelo)
    except Exception as exc:
        print(f"FALHA: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    imprimir_relatorio(resultado)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
