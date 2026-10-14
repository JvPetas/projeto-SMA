"""Relata blocos `parametros` anômalos (somente leitura): sem frequencia nem nao agendar,
e sem `da carteira(` nem `do time(`. Não corrige nada.

Uso: python scripts/find_anomalies.py [--dir data/gobr]
"""
import argparse
import re
import sys
import unicodedata
from pathlib import Path

KEYWORDS = {"version", "time", "segmentacao", "carteira", "parametros", "limpar", "alerta", "tags"}


def norm(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def parametros_blocks(path: Path):
    """Gera (linha_inicial, [(nº da linha, texto)]) de cada bloco parametros, comentários inclusos."""
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    start, current = None, []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        first = norm(stripped.split()[0]).rstrip(":") if stripped and not stripped.startswith("#") else None
        if first in KEYWORDS:
            if start is not None:
                yield start, current
            start, current = (i, [(i, line)]) if first == "parametros" else (None, [])
        elif start is not None:
            current.append((i, line))
    if start is not None:
        yield start, current


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="data/gobr")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    total = freq = nao = 0
    sem_nenhum, sem_escopo = [], []
    for path in sorted(Path(args.dir).glob("*.gobr")):
        for start, block in parametros_blocks(path):
            body = [norm(t).strip() for _, t in block[1:] if t.strip() and not t.strip().startswith("#")]
            has_freq = any(re.match(r"frequencia\b", l) for l in body)
            has_nao = any(l.startswith("nao agendar") for l in body)
            has_scope = any(re.match(r"(do time|da carteira)\s*\(", l) for l in body)
            total += 1
            freq += has_freq
            nao += has_nao
            if not (has_freq or has_nao):
                sem_nenhum.append((path.name, start, block))
            if not has_scope:
                sem_escopo.append((path.name, start, block))

    print(f"blocos parametros: {total} | com frequencia: {freq} | com nao agendar: {nao} | soma: {freq + nao}")
    for title, found in (("sem frequencia e sem nao agendar", sem_nenhum), ("sem da carteira( nem do time(", sem_escopo)):
        print(f"\n== {title}: {len(found)} bloco(s)")
        for name, start, block in found:
            print(f"-- {name}, linha {start}")
            for n, text in block:
                print(f"   {n:>4}| {text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
