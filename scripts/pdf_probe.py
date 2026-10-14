"""Sonda de PDFs (somente leitura): páginas, texto extraível, tabelas, imagens e títulos numerados.

Uso: python scripts/pdf_probe.py ARQUIVO.pdf [ARQUIVO.pdf ...] [--headings]
"""
import argparse
import re
import sys
from collections import Counter

import fitz  # pymupdf

NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+\S")


def probe(path: str, headings: bool) -> None:
    doc = fitz.open(path)
    pages = len(doc)
    text_chars, with_text, tables, images, img_only = 0, 0, 0, 0, 0
    table_pages = []
    for page in doc:
        text = page.get_text()
        n = len(text.strip())
        text_chars += n
        with_text += n > 0
        imgs = page.get_images(full=True)
        images += len(imgs)
        img_only += (n == 0 and bool(imgs))
        found = page.find_tables().tables
        if found:
            tables += len(found)
            table_pages.append(page.number + 1)
    print(f"== {path}")
    print(f"  páginas: {pages} | com texto: {with_text} | caracteres: {text_chars}")
    print(f"  imagens embutidas: {images} | páginas só-imagem (sem texto): {img_only}")
    print(f"  tabelas detectadas por find_tables: {tables}" + (f" (páginas {table_pages[:15]})" if table_pages else ""))
    if headings:
        probe_headings(doc)


def probe_headings(doc) -> None:
    body_sizes: Counter = Counter()
    candidates = []
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                text = "".join(s["text"] for s in spans).strip()
                size = round(max(s["size"] for s in spans), 1)
                bold = all(bool(s["flags"] & 16) or "bold" in s["font"].lower() for s in spans)
                body_sizes[size] += len(text)
                if NUMBERED.match(text):
                    candidates.append((page.number + 1, size, bold, text))
    body = body_sizes.most_common(1)[0][0]
    print(f"  tamanho de corpo (mais frequente): {body}")
    print(f"  linhas que começam com numeração (N., N.N...): {len(candidates)}")
    bigger = [c for c in candidates if c[1] > body or c[2]]
    print(f"    destas, com fonte maior que o corpo ou negrito: {len(bigger)}")
    by_style = Counter((c[1], c[2]) for c in candidates)
    print("    estilos (tamanho, negrito): " + ", ".join(f"{k}: {v}" for k, v in by_style.most_common(6)))
    for page, size, bold, text in candidates[:25]:
        print(f"    p.{page:<3} {size:>5} {'B' if bold else '-'}  {text[:80]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+")
    parser.add_argument("--headings", action="store_true", help="analisa títulos numerados (manual)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    for f in args.files:
        probe(f, args.headings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
