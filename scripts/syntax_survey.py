"""Levantamento de sintaxe dos .gobr: palavras que iniciam linha, variações de escrita e catch-all.

Uso: python scripts/syntax_survey.py [--dir data/gobr]
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

NAO_AGENDAR = {"nao agendar", "não agendar"}
KNOWN = {"version", "time", "segmentacao", "carteira", "parametros", "limpar", "alerta", "tags"}

VARIANTS = {
    "do time(": re.compile(r"\bdo time\("),
    "do time (": re.compile(r"\bdo time \("),
    "da carteira(": re.compile(r"\bda carteira\("),
    "da carteira (": re.compile(r"\bda carteira \("),
    "do carteira(": re.compile(r"\bdo carteira\("),
    "recencia de positivacao global em": re.compile(r"recencia de positivacao global em"),
    "recencia de positivacao em": re.compile(r"recencia de positivacao em"),
    "fora da recencia de positivacao": re.compile(r"fora da recencia de positivacao"),
    "nao agendar": re.compile(r"^\s*nao agendar\b"),
    "não agendar (acentuado)": re.compile(r"^\s*não agendar\b"),
    "frequencia": re.compile(r"^\s*frequencia\b"),
    "frequência (acentuado)": re.compile(r"^\s*frequência\b"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="data/gobr")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    files = sorted(Path(args.dir).rglob("*.gobr"))
    first_words = Counter()
    first_word_files: dict[str, set] = {}
    variants = {k: [0, set()] for k in VARIANTS}
    catchall, nao_agendar, fallback_nao_agendar = set(), set(), set()

    for path in files:
        text = path.read_text(encoding="utf-8-sig")
        raw_lines = [l.rstrip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
        for line in raw_lines:
            word = line.split()[0].rstrip(":")
            top = word in KNOWN
            if word[0] in '"0123456789)':
                word = "<continuação de lista>"
            word = ("[bloco] " if top else "[recuado] ") + word
            first_words[word] += 1
            first_word_files.setdefault(word, set()).add(path.name)
            for name, pat in VARIANTS.items():
                n = len(pat.findall(line))
                if n:
                    variants[name][0] += n
                    variants[name][1].add(path.name)
        # Blocos: linhas sem recuo abrem bloco; as indentadas pertencem ao anterior.
        cur = None
        all_blocks = []
        for line in raw_lines:
            if line[0] not in " \t":
                cur = [line]
                all_blocks.append(cur)
            elif cur is not None:
                cur.append(line)
        for b in all_blocks:
            if b[0].split()[0] != "parametros":
                continue
            body = [l.strip() for l in b[1:]]
            if not any(l.startswith("quando") for l in body):
                catchall.add(path.name)
                if any(l in NAO_AGENDAR for l in body):
                    fallback_nao_agendar.add(path.name)
            if any(l in NAO_AGENDAR for l in body):
                nao_agendar.add(path.name)

    print(f"{len(files)} arquivos\n")
    print("(a) Palavra que inicia linha (sem comentários/brancos): ocorrências / arquivos")
    for word, n in first_words.most_common():
        bare = word.split("] ", 1)[1]
        mark = "" if word.startswith("[recuado]") or bare in KNOWN else "   <-- FORA da lista de palavras-chave conhecidas"
        print(f"  {word:<36} {n:>6} / {len(first_word_files[word]):>3}{mark}")
    print("\n(b) Variações: ocorrências / arquivos")
    for name, (n, fs) in variants.items():
        print(f"  {name:<36} {n:>6} / {len(fs):>3}")
    print("\n(c) Arquivos com:")
    print(f"  parametros sem 'quando' (catch-all): {len(catchall)}")
    print(f"    destes, catch-all que é 'nao agendar': {len(fallback_nao_agendar)}")
    print(f"  'nao agendar' em algum bloco parametros: {len(nao_agendar)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
