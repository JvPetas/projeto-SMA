"""Casos de recência que merecem olhar (somente leitura): blocos puros sem clientes efetivos e
catch-alls com lacuna.

Uso: python scripts/survey_recencia.py [--dir data/gobr] [--exemplos 5]
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gobr_agent.explain.recencia import (  # noqa: E402
    INF,
    _classificar,
    analisar_grupo,
    chave_do_grupo,
    intersecao,
    texto_intervalos,
)
from gobr_agent.parsing import parse_dir  # noqa: E402


def par(intervalos) -> str:
    return " ∪ ".join(f"({int(lo)}, {'∞' if hi == INF else int(hi)})" for lo, hi in intervalos) or "∅"


def escopo_texto(p) -> str:
    return " ".join(f"{e.tipo}:{','.join(e.nomes)}" for e in p.escopos)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="data/gobr")
    parser.add_argument("--exemplos", type=int, default=5)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    vazios, lacunas = [], []
    for arq in parse_dir(args.dir):
        grupos = defaultdict(list)
        for p in arq.parametros:
            grupos[chave_do_grupo(p)].append(p)
        for blocos in grupos.values():
            infos = analisar_grupo(blocos)
            classes = [_classificar(p) for p in blocos]
            for i, (p, info) in enumerate(zip(blocos, infos)):
                if info.puro and info.efetivo == ():
                    consumidores = [
                        (blocos[j].nome, classes[j][1])
                        for j in range(i)
                        if classes[j] and classes[j][0] == info.cadeia and intersecao(classes[j][1], info.intervalo)
                    ]
                    vazios.append((arq.caminho, p, info, consumidores))
                if info.catch_all and info.lacunas:
                    cadeia = [(blocos[j].nome, classes[j][1]) for j in range(i) if classes[j]]
                    lacunas.append((arq.caminho, p, info, cadeia))

    print(f"== a) blocos puros sem clientes efetivos: {len(vazios)}")
    for arquivo, p, info, consumidores in vazios:
        print(f"\n  {arquivo}:{p.linha_ini}  \"{p.nome}\"  escopo={escopo_texto(p)}  cadeia={info.cadeia}")
        print(f"      intervalo literal: {par(info.intervalo)}   [{info.literal}]")
        for nome, intervalo in consumidores:
            print(f"        consumido por: \"{nome}\"  {par(intervalo)}")

    print(f"\n== b) catch-alls com lacuna: {len(lacunas)} (mostrando {args.exemplos}, de arquivos distintos)")
    vistos = set()
    for arquivo, p, info, cadeia in lacunas:
        if arquivo in vistos:
            continue
        vistos.add(arquivo)
        print(f"\n  {arquivo}:{p.linha_ini}  catch-all \"{p.nome}\"  escopo={escopo_texto(p)}")
        for nome, intervalo in cadeia:
            print(f"        {par(intervalo):<22} \"{nome}\"")
        print(f"      faixa descoberta: {texto_intervalos(info.lacunas)}   {par(info.lacunas)}")
        if len(vistos) == args.exemplos:
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
