"""Mostra um .gobr parseado de forma compacta, ou os blocos com `restricoes` (somente leitura).

Uso:
  python scripts/show_parsed.py ARQUIVO            # nome em data/gobr (com ou sem .gobr) ou caminho
  python scripts/show_parsed.py --restricoes       # blocos com restricoes de toda a pasta, com o texto original
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gobr_agent.parsing import parse_dir, parse_file  # noqa: E402
from gobr_agent.parsing.models import (  # noqa: E402
    BlocoBruto,
    Carteira,
    Frequencia,
    LimparParametros,
    Parametros,
    Preferencia,
    Segmentacao,
    Time,
)


def fmt_escopos(escopos) -> str:
    return " ".join(f"{(e.ligador + ' ') if e.ligador else ''}{e.tipo}:{','.join(e.nomes)}" for e in escopos) or "-"


def fmt_quando(quando) -> str:
    if not quando:
        return "-"
    return " | ".join(f"{(c.conector + ' ') if c.conector else ''}{c.texto}" for c in quando)


def fmt_frequencia(f: Frequencia | None) -> str:
    if f is None:
        return "-"
    if not f.reconhecida:
        return f"NAO RECONHECIDA: {f.bruta}"
    partes = [f.tipo]
    if f.tipo == "dias":
        partes.append(f"{f.dias}d")
    elif f.tipo == "periodo":
        partes.append(f"{f.periodo}({f.dias}d)" + (f" pivo={f.data_pivo}" if f.data_pivo else ""))
    elif f.tipo == "dinamica":
        partes.append(f.fonte + (f" ajuste={f.ajuste_dias:+d}d" if f.ajuste_dias else ""))
    elif f.tipo == "estatistica":
        partes.append(f.estatistica)
    if f.minimo_dias is not None:
        partes.append(f"min={f.minimo_dias}d")
    if f.maximo_dias is not None:
        partes.append(f"max={f.maximo_dias}d")
    if f.alternativas:
        partes.append("ou[" + "; ".join(fmt_frequencia(a) for a in f.alternativas) + "]")
    return " ".join(partes)


def fmt_preferencia(p: Preferencia | None) -> str:
    if p is None:
        return "-"
    if not p.reconhecida:
        return f"NAO RECONHECIDA: {p.bruta}"
    if p.remover:
        texto = "remover"
    elif p.fonte:
        texto = f"fonte={p.fonte}"
    else:
        texto = " ".join(f"{d}={v}" for d, v in p.dias.items() if v) or "(nenhum dia)"
    if p.alternativas:
        texto += " ou[" + "; ".join(fmt_preferencia(a) for a in p.alternativas) + "]"
    return texto


def fmt_flags(p: Parametros) -> str:
    flags = [n for n, v in (("nao_agendar", p.nao_agendar), ("fixo", p.fixo), ("roteirizavel", p.roteirizavel)) if v]
    flags += [f"sem_choque={s.alvo}:{','.join(s.nomes)}" for s in p.sem_choque]
    return " ".join(flags) or "-"


def mostrar_bloco(b, indice: int) -> None:
    cab = f"[{indice:>3}] {b.rotulo:<17} \"{b.nome}\"  (linhas {b.linha_ini}-{b.linha_fim})"
    print(cab + ("  ** INCOMPLETO **" if b.incompleto else ""))
    if isinstance(b, Parametros):
        print(f"      ordem={b.ordem}  escopos: {fmt_escopos(b.escopos)}  catch_all={'sim' if b.catch_all else 'nao'}")
        print(f"      quando: {fmt_quando(b.quando)}")
        print(f"      frequencia: {fmt_frequencia(b.frequencia)}  | preferencia: {fmt_preferencia(b.preferencia)}")
        print(f"      flags: {fmt_flags(b)}  | restricoes: {[r.texto for r in b.restricoes] or '-'}")
    elif isinstance(b, LimparParametros):
        print(f"      ordem={b.ordem}  escopos: {fmt_escopos(b.escopos)}")
    elif isinstance(b, Time):
        print(f"      vendedores: {b.vendedores}")
    elif isinstance(b, (Carteira, Segmentacao)):
        print(f"      clientes: {' ; '.join(b.clientes) or '-'}")
        print(f"      quando: {fmt_quando(b.quando)}")
    elif isinstance(b, BlocoBruto):
        print(f"      {len(b.linhas)} linhas brutas")
    for linha, texto in b.nao_reconhecidas:
        print(f"      NAO RECONHECIDA {linha}: {texto}")


def mostrar_arquivo(caminho: Path) -> None:
    arq = parse_file(caminho)
    print(f"=== {arq.caminho}  version={arq.version}  blocos={len(arq.blocos)}")
    for i, bloco in enumerate(arq.blocos):
        mostrar_bloco(bloco, i)
    for titulo, lista in (("AVISOS", arq.avisos), ("ERROS", arq.erros)):
        print(f"--- {titulo}: {len(lista)}")
        for p in lista:
            print(f"    linha {p.linha}: {p.mensagem}  {p.trecho}")


def mostrar_restricoes(pasta: Path) -> None:
    total = 0
    for arq in parse_dir(pasta):
        linhas = (pasta / arq.caminho).read_text(encoding="utf-8-sig").splitlines()
        for p in arq.parametros:
            if not p.restricoes:
                continue
            total += len(p.restricoes)
            marcadas = {r.linha for r in p.restricoes}
            print(f"\n##### {arq.caminho}  bloco #{p.ordem} \"{p.nome}\"  linhas {p.linha_ini}-{p.linha_fim}")
            for n in range(p.linha_ini, p.linha_fim + 1):
                marca = ">> RESTRICAO" if n in marcadas else "            "
                print(f"{marca} {n:>4}| {linhas[n - 1]}")
            print(f"     lido como: escopos={fmt_escopos(p.escopos)} | quando={fmt_quando(p.quando)}")
            print(f"                frequencia={fmt_frequencia(p.frequencia)} | preferencia={fmt_preferencia(p.preferencia)}")
            print(f"                flags={fmt_flags(p)} | restricoes={[r.texto for r in p.restricoes]}")
    print(f"\ntotal de linhas em restricoes: {total}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arquivo", nargs="?")
    parser.add_argument("--dir", default="data/gobr")
    parser.add_argument("--restricoes", action="store_true")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    pasta = Path(args.dir)
    if args.restricoes:
        mostrar_restricoes(pasta)
        return 0
    if not args.arquivo:
        parser.error("informe um arquivo ou use --restricoes")
    caminho = Path(args.arquivo)
    if not caminho.exists():
        caminho = pasta / (args.arquivo if args.arquivo.endswith(".gobr") else args.arquivo + ".gobr")
    mostrar_arquivo(caminho)
    return 0


if __name__ == "__main__":
    sys.exit(main())
