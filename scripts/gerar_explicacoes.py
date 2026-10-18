"""Gera e verifica explicações por conteúdo distinto, preservando a origem de cada arquivo."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from math import isfinite
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gobr_agent.explain.atomos import separar_atomos
from gobr_agent.explain.glossario import traduzir_condicao
from gobr_agent.explain.recencia import analisar_arquivo
from gobr_agent.explain.skeleton import gerar_esqueleto, renderizar_markdown
from gobr_agent.parsing import interpretar_frequencia, parse_file
from gobr_agent.parsing.models import Carteira, Parametros, Segmentacao
from gobr_agent.parsing.normalize import normalizar


class FonteGoldAusente(ValueError):
    pass


def carregar_gold(pares: Path | None, pasta_gold: Path | None) -> tuple[set[str], str]:
    if pares is not None and pares.is_file() and pares.read_text(encoding="utf-8-sig").strip():
        dados = json.loads(pares.read_text(encoding="utf-8-sig"))
        if not isinstance(dados, list):
            raise ValueError(f"{pares}: esperado um array de pares")
        if dados:
            if not all(isinstance(p, dict) and isinstance(p.get("gobr"), str) for p in dados):
                raise ValueError(f"{pares}: par sem nome de arquivo gobr")
            nomes = {p["gobr"] for p in dados if p.get("gabarito") is True}
            if not nomes:
                raise FonteGoldAusente(f"{pares} está preenchido, mas não marca nenhum gabarito")
            if any(Path(n).name != n or not n.lower().endswith(".gobr") for n in nomes):
                raise ValueError(f"{pares}: nomes de gold devem ser nomes-base .gobr")
            return {Path(n).stem.casefold() for n in nomes}, str(pares)
    if pasta_gold is not None and pasta_gold.is_dir():
        nomes = {p.stem.casefold() for p in pasta_gold.glob("*.md") if p.is_file()}
        if nomes:
            return nomes, str(pasta_gold)
    raise FonteGoldAusente(f"Fonte gold ausente ou vazia: pares={pares}; pasta_gold={pasta_gold}")


def _primaria_esperada(f):
    if f.tipo == "dias":
        return "dias", f.dias
    if f.tipo == "periodo":
        return "periodo", f.periodo, f.dias, f.data_pivo
    if f.tipo == "dinamica":
        return "dinamica", f.fonte, f.ajuste_dias
    if f.tipo == "estatistica":
        return "estatistica", f.estatistica
    if f.tipo == "remover":
        return ("remover",)
    return "literal", normalizar(f.bruta)


def _primaria_escrita(texto):
    t = normalizar(texto)
    if m := re.fullmatch(r"(\d+) dias", t):
        return "dias", int(m[1])
    if m := re.fullmatch(r"([a-z]+)\((\d+) dias\)(?:,referencia (.+))?", t):
        return "periodo", m[1], int(m[2]), m[3]
    if t == "remover frequencia parametrizada":
        return ("remover",)
    if m := re.fullmatch(r"frequencia de (ativos|inativos) (da empresa|do vendedor)", t):
        return "estatistica", m[1] + ("_empresa" if m[2] == "da empresa" else "_vendedor")
    ajuste = 0
    if m := re.search(r" (mais|menos) (\d+) dias$", t):
        ajuste = int(m[2]) * (-1 if m[1] == "menos" else 1)
        t = t[:m.start()]
    fontes = {
        "configurada pelo vendedor(padrao 7 dias)": "vendedor",
        "frequencia padrao do govendas": "govendas",
        "frequencia do historico do cliente": "historico",
        "frequencia de qualquer vendedor": "qualquer_vendedor",
    }
    if t in fontes:
        return "dinamica", fontes[t], ajuste
    raise ValueError(f"frequência escrita não reconhecida: {texto}")


def _frequencia_esperada(p):
    if p.nao_agendar:
        return ("nao_agendar",)
    if p.frequencia is None:
        return ("ausente",)
    f = p.frequencia
    if not f.reconhecida:
        return ("literal", normalizar(f.bruta))
    partes = [_primaria_esperada(f)]
    alternativas = iter(f.alternativas)
    for trecho in f.bruta.split(" ou ")[1:]:
        if trecho.startswith(("no minimo", "no maximo")):
            limite = interpretar_frequencia("de 1 dias ou " + trecho)
            partes.append(("limites", tuple((m[1], getattr(limite, m[1] + "_dias"))
                          for m in re.finditer(r"no (minimo|maximo)", trecho))))
        else:
            partes.append(_primaria_esperada(next(alternativas)))
    return tuple(partes)


def _frequencia_escrita(texto, p):
    t = normalizar(texto)
    if t == "nao agendar":
        return ("nao_agendar",)
    if t == "frequencia nao informada":
        return ("ausente",)
    if p.frequencia is not None and not p.frequencia.reconhecida:
        return "literal", t
    partes = []
    for trecho in t.split(" ou "):
        if trecho.startswith(("no minimo", "no maximo")):
            limites = []
            for pedaco in trecho.split(" e "):
                m = re.fullmatch(r"no (minimo|maximo) (?:de (\d+) dias|[a-z]+\((\d+) dias\))", pedaco)
                if not m:
                    raise ValueError(f"limite escrito não reconhecido: {pedaco}")
                limites.append((m[1], int(m[2] or m[3])))
            partes.append(("limites", tuple(limites)))
        else:
            partes.append(_primaria_escrita(trecho))
    return tuple(partes)


_DIAS = {"segunda": "seg", "terca": "ter", "quarta": "qua", "quinta": "qui", "sexta": "sex",
         "sabado": "sab", "domingo": "dom", "dias uteis": "uteis"}


def _preferencia_esperada(p):
    if p is None:
        return None
    if p.remover:
        base = ("remover",)
    elif p.fonte:
        base = ("fonte", p.fonte)
    elif p.reconhecida:
        base = ("dias", tuple((i.dia, i.intensidade) for i in p.itens))
    else:
        base = ("literal", normalizar(p.bruta))
    return base, tuple(_preferencia_esperada(a) for a in p.alternativas)


def _preferencia_escrita(texto):
    if texto is None:
        return None
    partes = normalizar(texto).split(" ou ")
    t = partes[0]
    if t == "remover preferencia parametrizada":
        base = ("remover",)
    elif t in ("preferencia do vendedor", "preferencia do historico"):
        base = ("fonte", "vendedor" if t.endswith("vendedor") else "historico")
    else:
        dias = []
        for pedaco in t.split(","):
            m = re.fullmatch(r"([a-z ]+)\(peso ([123])\)", pedaco.strip())
            if not m or m[1] not in _DIAS:
                base = ("literal", t)
                break
            dias.append((_DIAS[m[1]], int(m[2])))
        else:
            base = ("dias", tuple(dias))
    return base, tuple(_preferencia_escrita(a) for a in partes[1:])


def _linhas_tabela(markdown):
    linhas = []
    for linha in markdown.splitlines():
        if not linha.startswith("|") or linha.startswith(("| Nome |", "|---")):
            continue
        celulas = [c.strip().replace(r"\|", "|") for c in re.split(r"(?<!\\)\|", linha)[1:-1]]
        if len(celulas) != 4:
            raise ValueError(f"linha de tabela com {len(celulas)} células")
        linhas.append(celulas)
    return linhas


def _ramo_textual(arq):
    atributos = []
    for bloco in arq.blocos:
        if not isinstance(bloco, (Carteira, Segmentacao, Parametros)):
            continue
        for c in bloco.quando:
            for atomo, traducao in zip(separar_atomos(c.texto), traduzir_condicao(c)):
                if traducao.ramo_atividade_texto:
                    atributos.append({"linha": c.linha, "bloco": bloco.nome, "atomo": atomo,
                                      "ramo_atividade_texto": True})
    return atributos


def verificar(caminho: Path, markdown: str):
    """Relê a origem e interpreta as células sem usar os textos do esqueleto como expectativa."""
    arq = parse_file(caminho)
    linhas = _linhas_tabela(markdown)
    parametros = arq.parametros
    nomes = [l[0] for l in linhas]
    checks = {"linhas_parametros": {"ok": len(linhas) == len(parametros) and nomes == [p.nome for p in parametros],
                                   "blocos": len(parametros), "linhas": len(linhas)}}
    falhas_frequencia, falhas_numeros = [], []
    infos = analisar_arquivo(arq)
    for linha, p in zip(linhas, parametros):
        frequencia, *preferencia = linha[2].split("; preferência: ", 1)
        try:
            if _frequencia_escrita(frequencia, p) != _frequencia_esperada(p):
                raise ValueError("frequência escrita difere da frequência parseada")
            if _preferencia_escrita(preferencia[0] if preferencia else None) != _preferencia_esperada(p.preferencia):
                raise ValueError("preferência escrita difere da preferência parseada")
        except (ValueError, StopIteration) as exc:
            falhas_frequencia.append({"linha": p.linha_ini, "mensagem": str(exc), "escrita": linha[2]})
        origem = {n for c in p.quando for a in separar_atomos(c.texto) for n in re.findall(r"\d+", a)}
        origem |= {n for f in p.filtros_temporais for n in re.findall(r"\d+", f.bruta)}
        derivados = set()
        info = infos[p.linha_ini]
        for intervalos in (info.intervalo, info.efetivo, info.lacunas):
            for a, b in intervalos or ():
                derivados.update(str(int(n)) for n in (a, b) if isfinite(n))
        if info.texto_catch_all:
            derivados.update(re.findall(r"\d+", info.texto_catch_all))
        inventados = set(re.findall(r"\d+", linha[1])) - origem - derivados
        if inventados:
            falhas_numeros.append({"linha": p.linha_ini, "numeros": sorted(inventados), "condicao": linha[1]})
    atributos = _ramo_textual(arq)
    checks["frequencia"] = {"ok": not falhas_frequencia and len(linhas) == len(parametros), "falhas": falhas_frequencia}
    checks["numeros_condicao"] = {"ok": not falhas_numeros and len(linhas) == len(parametros), "falhas": falhas_numeros}
    checks["ramo_texto"] = {"ok": True, "sinalizado": bool(atributos), "atomos": atributos}
    internas = [{"linha": p.linha, "mensagem": p.mensagem, "trecho": p.trecho} for p in arq.erros
                if p.mensagem.startswith("falha interna")]
    checks["sem_excecao"] = {"ok": not internas, "falhas": internas}
    return checks, arq, len(linhas), atributos


def _escolher_exemplos(esqueletos, registros):
    candidatos = [r for r in registros if r["arquivo"] in esqueletos and r["papel"] == "corpus"
                  and r["nivel_diagnostico"] != "erro" and not r["falhas"]]
    usados, exemplos = set(), []
    criterios = [
        ("simples", "menor tabela sem recência e sem avisos de glossário; desempate por avisos e nome",
         lambda e: bool(e.linhas) and not any(l.recencia.historia for l in e.linhas)
         and not any(a.tipo.startswith("glossario_") for a in e.avisos)),
        ("cadeia de recência", "menor tabela com faixa efetiva reduzida por blocos puros anteriores; desempate por avisos e nome",
         lambda e: any(l.recencia.puro and l.recencia.efetivo and l.recencia.efetivo != l.recencia.intervalo for l in e.linhas)),
        ("avisos de glossário", "menor tabela com aviso de glossário; desempate por avisos e nome",
         lambda e: any(a.tipo.startswith("glossario_") for a in e.avisos)),
    ]
    for tipo, criterio, aceita in criterios:
        elegiveis = [r for r in candidatos if r["arquivo"] not in usados and aceita(esqueletos[r["arquivo"]])]
        escolhido = min(elegiveis, key=lambda r: (r["n_linhas"], sum(r["avisos_por_tipo"].values()), r["arquivo"].casefold())) if elegiveis else None
        if escolhido:
            usados.add(escolhido["arquivo"])
        exemplos.append({"tipo": tipo, "criterio": criterio, "arquivo": escolhido["arquivo"] if escolhido else None})
    return exemplos


def gerar_lote(entrada: Path, saida: Path, *, pares: Path | None, pasta_gold: Path | None,
               consolidado: Path | None = None):
    entrada, saida = Path(entrada), Path(saida)
    gold, fonte = carregar_gold(pares, pasta_gold)
    caminhos = sorted(entrada.glob("*.gobr"), key=lambda p: (p.name.casefold(), p.name))
    if not caminhos:
        raise ValueError(f"nenhum .gobr em {entrada}")
    gold_presentes = [p.name for p in caminhos if p.stem.casefold() in gold]
    if not gold_presentes:
        raise FonteGoldAusente(f"Fonte {fonte} não identifica nenhum gold na entrada {entrada}")
    saida.mkdir(parents=True, exist_ok=True)
    hashes, erros_leitura = {}, {}
    for p in caminhos:
        try:
            hashes[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError as exc:
            erros_leitura[p.name] = f"{type(exc).__name__}: {exc}"
    hashes_gold = {hashes[n] for n in gold_presentes if n in hashes}
    cache, canonicos, registros, textos, esqueletos = {}, {}, [], {}, {}
    for p in caminhos:
        h = hashes.get(p.name)
        duplicata = canonicos.get(h) if h else None
        if h and not duplicata:
            canonicos[h] = p.name
        papel = "gold" if p.stem.casefold() in gold else "corpus"
        registro = {"arquivo": p.name, "hash": h, "duplicata_de": duplicata, "n_blocos": None,
                    "n_linhas": None, "avisos_por_tipo": {}, "nivel_diagnostico": "nenhum", "papel": papel,
                    "indexar": False, "ramo_atividade_texto": False, "checagens": {}, "falhas": []}
        try:
            if p.name in erros_leitura:
                raise OSError(erros_leitura[p.name])
            if h not in cache:
                try:
                    cache[h] = gerar_esqueleto(p)
                except Exception as exc:
                    cache[h] = {"excecao": f"{type(exc).__name__}: {exc}"}
            if isinstance(cache[h], dict):
                raise RuntimeError(cache[h]["excecao"])
            e = deepcopy(cache[h])
            e.cabecalho["arquivo"] = p.name
            texto = renderizar_markdown(e)
            checks, arq, n_linhas, atributos = verificar(p, texto)
            registro.update(n_blocos=len(arq.parametros), n_blocos_total=len(arq.blocos), n_linhas=n_linhas,
                            avisos_por_tipo=dict(Counter(a.tipo for a in e.avisos)),
                            nivel_diagnostico=e.cabecalho["nivel_diagnostico"], checagens=checks,
                            ramo_atividade_texto=bool(atributos), atomos_ramo_texto=atributos)
            registro["falhas"] = [{"checagem": k, "detalhes": v} for k, v in checks.items() if v["ok"] is False]
            registro["indexar"] = papel == "corpus" and h not in hashes_gold and not duplicata and not registro["falhas"]
            (saida / (p.stem + ".md")).write_text(texto, encoding="utf-8")
            textos[p.name], esqueletos[p.name] = texto, e
        except Exception as exc:
            falha = {"ok": False, "falhas": [{"tipo": type(exc).__name__, "mensagem": str(exc)}]}
            registro["checagens"]["sem_excecao"] = falha
            for k in ("linhas_parametros", "frequencia", "numeros_condicao", "ramo_texto"):
                registro["checagens"].setdefault(k, {"ok": None, "estado": "não verificada devido à exceção"})
            registro["falhas"].append({"checagem": "sem_excecao", "detalhes": falha})
            registro["nivel_diagnostico"] = "erro"
            registro["indexar"] = False
            texto = f"# {p.name}\n\n> ⚠ falha ao gerar ou verificar: {type(exc).__name__}: {exc}\n"
            textos[p.name] = texto
            try:
                (saida / (p.stem + ".md")).write_text(texto, encoding="utf-8")
            except OSError as escrita:
                registro["falhas"].append({"checagem": "escrita", "mensagem": f"{type(escrita).__name__}: {escrita}"})
        registros.append(registro)
    avisos = Counter()
    falhas = Counter({k: 0 for k in ("linhas_parametros", "frequencia", "numeros_condicao", "ramo_texto", "sem_excecao")})
    for r in registros:
        avisos.update(r["avisos_por_tipo"])
        falhas.update(x["checagem"] for x in r["falhas"])
    index = {"versao": 1, "fonte_gold": fonte, "gold": gold_presentes, "arquivos": registros,
             "para_indexar": [r["arquivo"] for r in registros if r["indexar"]],
             "resumo": {"arquivos": len(registros), "conteudos_distintos": len(canonicos),
                        "arquivos_com_falhas": sum(bool(r["falhas"]) for r in registros),
                        "falhas_por_checagem": dict(falhas), "avisos_por_tipo": dict(avisos)},
             "exemplos": _escolher_exemplos(esqueletos, registros)}
    (saida / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    consolidado = Path(consolidado) if consolidado else saida.parent / "explicacoes_consolidado.md"
    consolidado.parent.mkdir(parents=True, exist_ok=True)
    doc = ["# Explicações GOBR", "", "## Sumário", ""]
    doc += [f"- [{r['arquivo']}](#arquivo-{i:04d}) — {r['papel']}" for i, r in enumerate(registros, 1)]
    for i, r in enumerate(registros, 1):
        doc += ["", f'<a id="arquivo-{i:04d}"></a>', "", textos[r["arquivo"]].rstrip()]
    consolidado.write_text("\n".join(doc) + "\n", encoding="utf-8")
    return index, textos


def imprimir_relatorio(index, textos):
    s = index["resumo"]
    print(f"Arquivos processados: {s['arquivos']}")
    print(f"Conteúdos distintos SHA-256: {s['conteudos_distintos']}")
    print(f"Fonte gold: {index['fonte_gold']}")
    print("Gold: " + ", ".join(index["gold"]))
    print(f"Arquivos com falhas: {s['arquivos_com_falhas']}")
    print("Falhas por checagem: " + json.dumps(s["falhas_por_checagem"], ensure_ascii=False, sort_keys=True))
    print("Avisos por tipo: " + json.dumps(s["avisos_por_tipo"], ensure_ascii=False, sort_keys=True))
    print("Níveis de diagnóstico de sintaxe: " + json.dumps(dict(Counter(r["nivel_diagnostico"] for r in index["arquivos"])), ensure_ascii=False))
    for r in index["arquivos"]:
        for falha in r["falhas"]:
            print(f"FALHA {r['arquivo']}: " + json.dumps(falha, ensure_ascii=False))
    print("10 arquivos com mais avisos:")
    for r in sorted(index["arquivos"], key=lambda r: (-sum(r["avisos_por_tipo"].values()), r["arquivo"].casefold()))[:10]:
        print(f"  {r['arquivo']}: {sum(r['avisos_por_tipo'].values())}")
    for exemplo in index["exemplos"]:
        print(f"\nEXEMPLO {exemplo['tipo']}: {exemplo['arquivo'] or 'indisponível'}")
        print("Critério: " + exemplo["criterio"])
        if exemplo["arquivo"]:
            print(textos[exemplo["arquivo"]], end="")
        else:
            print("Nenhum arquivo elegível para esse critério.")


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--gobr", type=Path, default=ROOT / "data/gobr")
    cli.add_argument("--out", type=Path, default=ROOT / "data/processed/explicacoes")
    cli.add_argument("--pairs", type=Path, default=ROOT / "data/pairs.json")
    cli.add_argument("--gold", type=Path, default=ROOT / "data/processed/gold")
    cli.add_argument("--consolidado", type=Path)
    args = cli.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        index, textos = gerar_lote(args.gobr, args.out, pares=args.pairs, pasta_gold=args.gold, consolidado=args.consolidado)
    except Exception as exc:
        print(f"FALHA: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    imprimir_relatorio(index, textos)
    return 1 if index["resumo"]["arquivos_com_falhas"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
