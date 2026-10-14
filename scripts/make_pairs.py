"""Gera data/pairs.json pareando cada .gobr com a descrição de mesmo nome base em data/imagens.

Um .gobr com descrição de mesmo nome base vira par de referência (gabarito=true);
os demais ficam com descricao=null e gabarito=false. Não sobrescreve um pairs.json
existente sem --force.

Uso: python scripts/make_pairs.py [--gobr data/gobr] [--imagens data/imagens] [--out data/pairs.json] [--force]
"""
import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gobr", default="data/gobr")
    parser.add_argument("--imagens", default="data/imagens")
    parser.add_argument("--out", default="data/pairs.json")
    parser.add_argument("--force", action="store_true", help="sobrescreve o arquivo de saída")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"{out} já existe; use --force para sobrescrever", file=sys.stderr)
        return 1

    descricoes = {
        p.stem.lower(): p.name
        for p in Path(args.imagens).iterdir()
        if p.is_file() and p.name != ".gitkeep"
    }
    pairs = []
    for path in sorted(Path(args.gobr).glob("*.gobr")):
        descricao = descricoes.get(path.stem.lower())
        pairs.append({"gobr": path.name, "descricao": descricao, "gabarito": descricao is not None})

    out.write_text(json.dumps(pairs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pareados = [p for p in pairs if p["descricao"]]
    sem_gobr = sorted(set(descricoes.values()) - {p["descricao"] for p in pareados})
    print(f"{len(pairs)} itens gravados em {out}; {len(pareados)} com descrição")
    if sem_gobr:
        print("descrições sem .gobr correspondente: " + ", ".join(sem_gobr))
    return 0


if __name__ == "__main__":
    sys.exit(main())
