"""Cobertura das condições `quando` por assinatura (somente leitura).

Cada linha de `quando` (parametros, carteira e segmentacao) tem uma `assinatura`: o texto
normalizado com os números trocados por N. Mostra quantas assinaturas distintas existem,
quantas cobrem 50/80/90/95% das linhas e as mais frequentes.

Uso: python scripts/survey_conditions.py [--dir data/gobr] [--top 40]
"""
import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gobr_agent.parsing import parse_dir  # noqa: E402
from gobr_agent.parsing.models import Carteira, Parametros, Segmentacao  # noqa: E402


def cobertura(contagem: Counter, niveis=(0.50, 0.80, 0.90, 0.95)) -> dict[float, int]:
    total = sum(contagem.values())
    resultado, acumulado = {}, 0
    pendentes = list(niveis)
    for i, (_, n) in enumerate(contagem.most_common(), 1):
        acumulado += n
        while pendentes and acumulado >= pendentes[0] * total:
            resultado[pendentes.pop(0)] = i
    return resultado


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="data/gobr")
    parser.add_argument("--top", type=int, default=40)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    linhas = Counter()
    por_origem = Counter()
    arquivos = defaultdict(set)
    exemplo = {}
    abstratas = Counter()  # mesma assinatura, mas com o conteúdo entre aspas trocado por S
    for arq in parse_dir(args.dir):
        for bloco in arq.blocos:
            if not isinstance(bloco, (Parametros, Carteira, Segmentacao)):
                continue
            for c in bloco.quando:
                linhas[c.assinatura] += 1
                por_origem[bloco.rotulo.split()[0]] += 1
                arquivos[c.assinatura].add(arq.caminho)
                exemplo.setdefault(c.assinatura, f"{arq.caminho}:{c.linha}")
                abstratas[re.sub(r'"[^"]*"', "S", c.assinatura)] += 1

    total = sum(linhas.values())
    print(f"{total} linhas de `quando` ({dict(por_origem)}); {len(linhas)} assinaturas distintas")
    for nome, contagem in (("assinatura", linhas), ("assinatura com texto entre aspas -> S", abstratas)):
        cob = cobertura(contagem)
        print(f"\n[{nome}] {len(contagem)} distintas; assinaturas para cobrir: "
              + ", ".join(f"{int(p * 100)}% = {n}" for p, n in cob.items()))
    print(f"\n{'#':>3} {'linhas':>6} {'arq.':>4} {'acum.%':>6}  {'exemplo':<24} assinatura")
    acumulado = 0
    for i, (assinatura, n) in enumerate(linhas.most_common(args.top), 1):
        acumulado += n
        print(f"{i:>3} {n:>6} {len(arquivos[assinatura]):>4} {100 * acumulado / total:>6.1f}  {exemplo[assinatura]:<24} {assinatura[:100]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
