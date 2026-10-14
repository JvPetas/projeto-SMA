"""Roda o parser em todos os .gobr de uma pasta e resume o resultado (somente leitura).

Imprime: blocos por tipo; avisos e erros agrupados por mensagem; formas de frequencia e
preferencia não reconhecidas; e as linhas que não viraram cláusula (restricoes e não reconhecidas).

Uso: python scripts/parse_all.py [--dir data/gobr] [--exemplos 3]
"""
import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gobr_agent.parsing import parse_dir  # noqa: E402
from gobr_agent.parsing.normalize import assinatura  # noqa: E402


def agrupar_problemas(titulo: str, problemas, exemplos: int) -> None:
    grupos = defaultdict(list)
    for p in problemas:
        grupos[p.mensagem].append(p)
    total = sum(len(v) for v in grupos.values())
    print(f"\n== {titulo}: {total} em {len(grupos)} mensagens")
    for mensagem, itens in sorted(grupos.items(), key=lambda kv: -len(kv[1])):
        arquivos = {p.arquivo for p in itens}
        print(f"  {len(itens):>5} em {len(arquivos):>3} arquivos  {mensagem}")
        for p in itens[:exemplos]:
            print(f"           {p.arquivo}:{p.linha}  {p.trecho[:90]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="data/gobr")
    parser.add_argument("--exemplos", type=int, default=3, help="exemplos por mensagem")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    arquivos = parse_dir(args.dir)
    print(f"{len(arquivos)} arquivos em {args.dir}")
    por_tipo = Counter(b.rotulo for a in arquivos for b in a.blocos)
    print("\n== Blocos por tipo")
    for rotulo, n in por_tipo.most_common():
        print(f"  {n:>6}  {rotulo}")
    print(f"  {sum(por_tipo.values()):>6}  total")
    print(f"  incompletos (com erro): {sum(b.incompleto for a in arquivos for b in a.blocos)}")

    agrupar_problemas("Erros", [e for a in arquivos for e in a.erros], args.exemplos)
    agrupar_problemas("Avisos", [w for a in arquivos for w in a.avisos], args.exemplos)

    print("\n== Formas não reconhecidas (assinatura: números -> N)")
    for campo in ("frequencia", "preferencia"):
        formas: dict[str, list[str]] = defaultdict(list)
        for a in arquivos:
            for p in a.parametros:
                valor = getattr(p, campo)
                if valor is not None and not valor.reconhecida:
                    formas[assinatura(valor.bruta)].append(f"{a.caminho}:{p.linha_ini}")
        print(f"  {campo}: {sum(len(v) for v in formas.values())} ocorrências, {len(formas)} formas")
        for forma, locais in sorted(formas.items(), key=lambda kv: -len(kv[1])):
            print(f"    {len(locais):>4}  {forma}   [{locais[0]}]")

    print("\n== Linhas que não viraram cláusula")
    restricoes = [(a.caminho, r) for a in arquivos for p in a.parametros for r in p.restricoes]
    nao_rec = [(a.caminho, b, l) for a in arquivos for b in a.blocos for l in b.nao_reconhecidas]
    print(f"  restricoes: {len(restricoes)} linhas em {len({c for c, _ in restricoes})} arquivos")
    for forma, n in Counter(assinatura(r.texto.lower()) for _, r in restricoes).most_common(8):
        print(f"    {n:>4}  {forma}")
    print(f"  não reconhecidas: {len(nao_rec)} linhas em {len({c for c, _, _ in nao_rec})} arquivos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
