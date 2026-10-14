"""Levantamento de padrões de negócio nos .gobr (somente leitura): quantos arquivos/blocos
têm bloqueio de baixados, bloqueio de inadimplentes, catch-all final `nao agendar`,
escopo por segmentacao, alerta/tags, e os `quando` mais frequentes.

Uso: python scripts/survey_patterns.py [--dir data/gobr]
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

from find_anomalies import norm, parametros_blocks

BAIXADA = "status na receita federal definido como baixada"
CONTINUATION_START = ('"', ")", ",", "'")
BLOCK_WORDS = {"alerta", "tags", "limpar"}


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", norm(text)).strip()


def body_lines(block):
    """Linhas do corpo sem comentários nem brancos, normalizadas."""
    return [clean(t) for _, t in block[1:] if t.strip() and not t.strip().startswith("#")]


def quando_atoms(body: list[str]) -> list[str]:
    """Condições do `quando`: a 1ª linha e cada linha `e ...`/`ou ...` que a segue.
    Linhas de continuação de listas (aspas, vírgula) são coladas ao átomo anterior."""
    atoms: list[str] = []
    started = False
    for line in body:
        if not started:
            if line.startswith("quando "):
                atoms.append(line[len("quando "):])
                started = True
            continue
        if line.startswith(("e ", "ou ")) and not line.startswith(("e da ", "e do ")):
            atoms.append(line.split(" ", 1)[1])
        elif line.startswith(CONTINUATION_START) or line[:1].isdigit():
            atoms[-1] += " " + line
        else:
            break
    return atoms


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="data/gobr")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    files = sorted(Path(args.dir).glob("*.gobr"))
    found = {k: {"files": set(), "blocks": 0} for k in ("baixada", "inadimplente", "final", "catchall_nao", "segmentacao", "alerta_tags")}
    inad_texts: Counter = Counter()
    atoms_c: Counter = Counter()
    clauses_c: Counter = Counter()
    atoms_abs: Counter = Counter()

    def hit(key: str, name: str) -> None:
        found[key]["files"].add(name)
        found[key]["blocks"] += 1

    for path in files:
        raw = path.read_text(encoding="utf-8-sig").splitlines()
        for line in raw:
            if clean(line.split("#")[0]).split(" ")[0] in BLOCK_WORDS and not line[:1].isspace():
                hit("alerta_tags", path.name)
        blocks = list(parametros_blocks(path))
        for idx, (start, block) in enumerate(blocks):
            body = body_lines(block)
            nao = any(l.startswith("nao agendar") for l in body)
            text = " | ".join(body)
            atoms = quando_atoms(body)
            if nao and BAIXADA in text:
                hit("baixada", path.name)
            if nao and "inadimplente" in text:
                hit("inadimplente", path.name)
                inad_texts[" e ".join(atoms)] += 1
            if nao and not atoms:
                hit("catchall_nao", path.name)
                if idx == len(blocks) - 1:
                    hit("final", path.name)
            if any(re.match(r"(e )?da segmentacao\s*\(", l) for l in body):
                hit("segmentacao", path.name)
            for a in atoms:
                atoms_c[a] += 1
                atoms_abs[re.sub(r"\d+", "N", a)] += 1
            if atoms:
                clauses_c[" e ".join(atoms)] += 1

    labels = {
        "baixada": "(1) bloco `nao agendar` com status na receita federal definido como baixada",
        "inadimplente": "(2) bloco `nao agendar` cujo texto menciona inadimplente(s)",
        "final": "(3) último parametros do arquivo é catch-all `nao agendar`",
        "catchall_nao": "    (referência) catch-all `nao agendar` em qualquer posição",
        "segmentacao": "(4) parametros com `da segmentacao(` no escopo",
        "alerta_tags": "(5) linha de bloco `alerta`, `tags` ou `limpar`",
    }
    print(f"{len(files)} arquivos\n")
    print(f"{'padrão':<86} {'arquivos':>8} {'blocos':>7}")
    for key, label in labels.items():
        print(f"{label:<86} {len(found[key]['files']):>8} {found[key]['blocks']:>7}")
    print("\n(2) condições `quando` dos blocos de inadimplência (distintas):")
    for text, n in inad_texts.most_common(8):
        print(f"  {n:>4}  {text or '(sem quando)'}")

    for title, counter in (
        ("10 condições `quando` mais frequentes (cada `e ...` conta como uma; normalizadas)", atoms_c),
        ("10 condições mais frequentes com números trocados por N", atoms_abs),
        ("10 cláusulas `quando` completas mais frequentes", clauses_c),
    ):
        print(f"\n{title}:")
        for text, n in counter.most_common(10):
            print(f"  {n:>4}  {text[:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
