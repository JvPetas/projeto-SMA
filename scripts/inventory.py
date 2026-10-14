"""Inventário dos arquivos .gobr: varre a pasta inteira e resume a estrutura de cada um.

Uso: python scripts/inventory.py [--dir data/gobr]
"""
import argparse
import re
import sys
from pathlib import Path

# Palavra-chave no início da linha (sem contar comentários). "limpar parametros"
# e "carteira livre" têm contagem própria, separada de "parametros" e "carteira".
KEYWORDS = {
    "time": re.compile(r"^time\b"),
    "parametros": re.compile(r"^parametros\b"),
    "carteira": re.compile(r"^carteira\b(?!\s+livre\b)"),
    "carteira livre": re.compile(r"^carteira\s+livre\b"),
    "alerta": re.compile(r"^alerta\b"),
    "tags": re.compile(r"^tags\b"),
    "segmentacao": re.compile(r"^segmentacao\b"),
    "limpar parametros": re.compile(r"^limpar\s+parametros\b"),
}
VERSION = re.compile(r"^version\s+1\.0\b")

COLUMNS = ["arquivo", "v1.0", *KEYWORDS, "comentarios"]


def guess_encoding(raw: bytes) -> str:
    """Palpite de codificação para bytes que não são UTF-8."""
    try:
        import charset_normalizer

        best = charset_normalizer.from_bytes(raw).best()
        if best is not None:
            return best.encoding
    except ImportError:
        pass
    try:
        raw.decode("cp1252")
        return "cp1252 (provável; instale charset-normalizer para confirmar)"
    except UnicodeDecodeError:
        return "latin-1 (provável)"


def analyze(path: Path) -> dict:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return {"arquivo": path.name, "erro": f"não é UTF-8 ({exc.reason} no byte {exc.start}); "
                f"codificação provável: {guess_encoding(raw)}"}

    counts = {k: 0 for k in KEYWORDS}
    comments = 0
    first_code_line = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            comments += 1
            continue
        if first_code_line is None:
            first_code_line = stripped
        for key, pattern in KEYWORDS.items():
            if pattern.match(stripped):
                counts[key] += 1
                break
    return {
        "arquivo": path.name,
        "v1.0": "sim" if first_code_line and VERSION.match(first_code_line) else "NÃO",
        **counts,
        "comentarios": comments,
    }


def print_table(rows: list[dict]) -> None:
    table = [[str(r.get(c, "")) for c in COLUMNS] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in table)) for i, c in enumerate(COLUMNS)]
    fmt = lambda cells: "  ".join(
        cell.ljust(w) if i == 0 else cell.rjust(w) for i, (cell, w) in enumerate(zip(cells, widths))
    )
    print(fmt(COLUMNS))
    print("  ".join("-" * w for w in widths))
    for row in table:
        print(fmt(row))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="data/gobr", help="pasta com os .gobr (padrão: data/gobr)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    files = sorted(p for p in Path(args.dir).rglob("*") if p.is_file() and p.suffix.lower() == ".gobr")
    print(f"{len(files)} arquivo(s) .gobr em {args.dir}\n")
    if not files:
        return 0

    results = [analyze(p) for p in files]
    print_table([r for r in results if "erro" not in r])
    errors = [r for r in results if "erro" in r]
    if errors:
        print("\nArquivos que não leram como UTF-8:")
        for r in errors:
            print(f"  {r['arquivo']}: {r['erro']}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
