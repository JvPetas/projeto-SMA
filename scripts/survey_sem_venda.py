"""Levantamento (somente leitura) sobre `sem venda`, `sem vendas`, `sem venda do vendedor`,
`e o cliente filial` e a cobertura em condições atômicas.

Uso: python scripts/survey_sem_venda.py [--dir data/gobr]
"""
import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gobr_agent.explain.atomos import separar_atomos  # noqa: E402
from gobr_agent.parsing import parse_dir  # noqa: E402
from gobr_agent.parsing.models import Carteira, Parametros, Segmentacao  # noqa: E402
from gobr_agent.parsing.normalize import assinatura  # noqa: E402

PROSPECT = "no ciclo de vida prospect com a empresa"


def texto_frequencia(p: Parametros) -> str:
    if p.nao_agendar:
        return "nao agendar"
    f = p.frequencia
    if f is None:
        return "(sem frequencia)"
    if f.tipo == "dias":
        return f"{f.dias} dias"
    if f.tipo == "periodo":
        return f"{f.periodo}()"
    return f"{f.tipo}:{f.fonte or f.estatistica or ''}"


def chave_escopo(p: Parametros):
    return tuple((e.tipo, e.nomes) for e in p.escopos)


def texto_do_bloco(pasta: Path, arq, p) -> str:
    linhas = (pasta / arq.caminho).read_text(encoding="utf-8-sig").splitlines()
    return "\n".join(f"      {n:>4}| {linhas[n - 1]}" for n in range(p.linha_ini, p.linha_fim + 1))


def cobertura(contagem: Counter, niveis=(0.50, 0.80, 0.90, 0.95)) -> str:
    total, acumulado, pendentes, saida = sum(contagem.values()), 0, list(niveis), []
    for i, (_, n) in enumerate(contagem.most_common(), 1):
        acumulado += n
        while pendentes and acumulado >= pendentes[0] * total:
            saida.append(f"{int(pendentes.pop(0) * 100)}% = {i}")
    return ", ".join(saida)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="data/gobr")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    pasta = Path(args.dir)
    arquivos = parse_dir(pasta)

    # ---------------------------------------------------------------- a) `sem venda`
    com = [(a, p) for a in arquivos for p in a.parametros if any(c.assinatura == "sem venda" for c in p.quando)]
    print(f"== a) `sem venda`: {sum(1 for a, p in com for c in p.quando if c.assinatura == 'sem venda')} linhas "
          f"em {len(com)} blocos de {len({a.caminho for a, _ in com})} arquivos")
    print("\n  nomes de bloco mais comuns (top 15):")
    for nome, n in Counter(p.nome for _, p in com).most_common(15):
        print(f"    {n:>4}  {nome}")
    print("\n  frequências desses blocos:")
    for texto, n in Counter(texto_frequencia(p) for _, p in com).most_common(12):
        print(f"    {n:>4}  {texto}")
    mesmo_escopo, mesmo_bloco = set(), set()
    for a in arquivos:
        grupos = defaultdict(lambda: [False, False])
        for p in a.parametros:
            tem_sv = any(c.assinatura == "sem venda" for c in p.quando)
            tem_pr = any(PROSPECT in separar_atomos(c.texto) for c in p.quando)
            grupos[chave_escopo(p)][0] |= tem_sv
            grupos[chave_escopo(p)][1] |= tem_pr
            if tem_sv and tem_pr:
                mesmo_bloco.add(a.caminho)
        if any(sv and pr for sv, pr in grupos.values()):
            mesmo_escopo.add(a.caminho)
    print(f"\n  arquivos com `sem venda` E `{PROSPECT}` no mesmo escopo: {len(mesmo_escopo)} "
          f"(de {len({a.caminho for a, _ in com})} arquivos com `sem venda`); no MESMO bloco: {len(mesmo_bloco)}")

    # ------------------------------------------- b) `sem vendas` e `sem venda do vendedor`
    for alvo in ("sem vendas", "sem venda do vendedor"):
        achados = [(a, p) for a in arquivos for p in a.parametros if any(c.assinatura == alvo for c in p.quando)]
        total = sum(1 for _, p in achados for c in p.quando if c.assinatura == alvo)
        print(f"\n== b) `{alvo}`: {total} linhas em {len({a.caminho for a, _ in achados})} arquivos; 5 exemplos (arquivos distintos)")
        vistos = set()
        for a, p in achados:
            if a.caminho in vistos:
                continue
            vistos.add(a.caminho)
            print(f"\n  {a.caminho}  bloco \"{p.nome}\" (linhas {p.linha_ini}-{p.linha_fim})")
            print(texto_do_bloco(pasta, a, p))
            if len(vistos) == 5:
                break

    # ------------------------------------------------------------ c) `e o cliente filial`
    print("\n== c) `e o cliente filial` (assinatura da linha inteira)")
    achados = []
    for a in arquivos:
        for b in a.blocos:
            if isinstance(b, (Parametros, Carteira, Segmentacao)):
                for c in b.quando:
                    if c.assinatura == "e o cliente filial":
                        achados.append((a.caminho, c.linha, b.nome, c.bruta))
    print(f"  {len(achados)} linhas em {len({x[0] for x in achados})} arquivos")
    for arq, linha, nome, bruta in achados:
        print(f"    {arq}:{linha}  [{nome}]  {bruta}")
    outras = Counter()
    for a in arquivos:
        for b in a.blocos:
            if isinstance(b, (Parametros, Carteira, Segmentacao)):
                for c in b.quando:
                    if "cliente filial" in c.texto and c.assinatura != "e o cliente filial":
                        outras[c.assinatura] += 1
    print("  outras linhas que contêm `cliente filial`:", dict(outras))

    # ------------------------------------------------------ d) cobertura em átomos
    atomos, atomos_s, total_linhas = Counter(), Counter(), 0
    for a in arquivos:
        for b in a.blocos:
            if isinstance(b, (Parametros, Carteira, Segmentacao)):
                for c in b.quando:
                    total_linhas += 1
                    for atomo in separar_atomos(c.texto):
                        sig = assinatura(atomo)
                        atomos[sig] += 1
                        atomos_s[re.sub(r'"[^"]*"', "S", sig)] += 1
    print(f"\n== d) condições atômicas: {sum(atomos.values())} átomos em {total_linhas} linhas; {len(atomos)} distintos")
    print(f"  átomos necessários para cobrir: {cobertura(atomos)}")
    print(f"  com texto entre aspas -> S: {len(atomos_s)} distintos; {cobertura(atomos_s)}")
    print("  15 átomos mais frequentes:")
    for sig, n in atomos.most_common(15):
        print(f"    {n:>4}  {sig[:100]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
