"""Formas distintas das linhas `frequencia` e `preferencia` (somente leitura) e blocos que
vêm depois de um catch-all `nao agendar`.

Uma linha de `frequencia`/`preferencia` inclui as linhas seguintes mais recuadas
(continuação). Números viram N e textos entre aspas viram S.

Uso: python scripts/survey_forms.py [--dir data/gobr] [--max 60]
"""
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

from find_anomalies import norm, parametros_blocks

SCOPE = re.compile(r"^(?:e )?(do time|da carteira|da segmentacao)\s*\((.*)\)\s*$")


def indent(text: str) -> int:
    return len(text.expandtabs(4)) - len(text.expandtabs(4).lstrip())


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", norm(text)).strip()


def signature(text: str) -> str:
    text = re.sub(r'"[^"]*"', "S", text)
    return re.sub(r"\d+", "N", text)


def content_lines(block):
    return [(n, t) for n, t in block[1:] if t.strip() and not t.strip().startswith("#")]


def scopes(block) -> list[str]:
    found = []
    for _, t in content_lines(block):
        line = clean(t)
        if line.startswith("quando "):
            break
        m = SCOPE.match(line)
        if m:
            found.append(f"{m.group(1)}({m.group(2)})")
    return found


def collect_forms(files):
    forms = {"frequencia": defaultdict(lambda: [0, set(), None]), "preferencia": defaultdict(lambda: [0, set(), None])}
    for path in files:
        for _, block in parametros_blocks(path):
            lines = content_lines(block)
            for i, (n, t) in enumerate(lines):
                first = clean(t).split(" ")[0]
                if first not in forms:
                    continue
                parts = [clean(t)]
                j = i + 1
                while j < len(lines) and indent(lines[j][1]) > indent(t):
                    parts.append(clean(lines[j][1]))
                    j += 1
                form = signature(" / ".join(parts))
                entry = forms[first][form]
                entry[0] += 1
                entry[1].add(path.name)
                if entry[2] is None:
                    entry[2] = f"{path.name}:{n}"
    return forms


def print_forms(title, table, limit):
    rows = sorted(table.items(), key=lambda kv: (-kv[1][0], kv[0]))
    print(f"\n== {title}: {len(rows)} formas distintas, {sum(v[0] for _, v in rows)} ocorrências")
    print(f"{'ocorr.':>6} {'arq.':>4}  {'exemplo':<22} forma")
    for form, (count, fs, example) in rows[:limit]:
        print(f"{count:>6} {len(fs):>4}  {example:<22} {form}")
    if len(rows) > limit:
        rest = rows[limit:]
        print(f"   ... mais {len(rest)} formas, {sum(v[0] for _, v in rest)} ocorrências (use --max para ver)")


def report_catchall(files):
    print("\n== Blocos depois de um catch-all `nao agendar` (bloco sem `quando` e com `nao agendar`)")
    total_pairs = same_pairs = 0
    cases = 0
    for path in files:
        blocks = list(parametros_blocks(path))
        for idx, (start, block) in enumerate(blocks):
            body = [clean(t) for _, t in content_lines(block)]
            if any(l.startswith("quando ") for l in body) or not any(l.startswith(("nao agendar")) for l in body):
                continue
            later = blocks[idx + 1:]
            if not later:
                continue
            cases += 1
            sc = scopes(block)
            print(f"\n{path.name}:{start}  catch-all escopo={sc or '(nenhum)'}  | blocos seguintes: {len(later)}")
            for s2, b2 in later:
                sc2 = scopes(b2)
                same = sc2 == sc
                total_pairs += 1
                same_pairs += same
                print(f"    linha {s2:>4}: escopo={sc2 or '(nenhum)'}  {'= MESMO' if same else '!= diferente'}")
    print(f"\ncatch-alls com blocos depois: {cases}; pares (catch-all, bloco seguinte): {total_pairs}; mesmo escopo: {same_pairs}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="data/gobr")
    parser.add_argument("--max", type=int, default=60, help="formas mostradas por tabela")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    files = sorted(Path(args.dir).glob("*.gobr"))
    forms = collect_forms(files)
    print(f"{len(files)} arquivos")
    print_forms("frequencia", forms["frequencia"], args.max)
    print_forms("preferencia", forms["preferencia"], args.max)
    report_catchall(files)
    return 0


if __name__ == "__main__":
    sys.exit(main())
