"""Esqueleto determinístico das parametrizações GOBR, na ordem do arquivo."""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..parsing import parse_file
from ..parsing.models import ArquivoGobr, BlocoBruto, Frequencia, Parametros, Preferencia
from .atomos import separar_atomos
from .glossario import traduzir_condicao
from .recencia import (
    AVISO_MISTURA, INF, SOMBREAMENTO_HIPOTESE, SOMBREAMENTO_PROVADO,
    InfoRecencia, analisar_arquivo, chave_do_grupo, interpretar_atomo, texto_intervalos,
)

AVISO_PROSPECT = (
    "⚠ o manual não define se cliente sem compra entra em 'fora da recência'; "
    "se entrar, o bloco de prospects abaixo não será atingido"
)
AVISO_FORA_ENTRE = (
    "⚠ pelo manual, 'fora ... entre' exclui o intervalo {a}–{b}; vários exemplos "
    "usam essa forma querendo 'dentro de {a}–{b}' (não confirmado)"
)
AVISO_HISTORICO = "⚠ histórico misto global/sem qualificador; as faixas são descritas pela ordem dos blocos"
NOTA_BLOQUEIOS = "exceto clientes bloqueados nas regras 'Não agendar' acima"
_AVISOS_SINTAXE = {
    "parametros sem frequência nem nao agendar",
}
_NOTAS_SINTAXE = {"version 1.0 ausente", "aspa solta removida", "caracteres de controle removidos"}


@dataclass(frozen=True)
class Aviso:
    tipo: str
    linha: int
    mensagem: str


@dataclass
class Linha:
    nome: str
    condicao: str
    frequencia: str
    observacao: str
    linha: int
    escopo: tuple
    antecedentes: tuple[str, ...] = ()
    recencia: InfoRecencia | None = None


@dataclass
class Esqueleto:
    cabecalho: dict
    linhas: list[Linha] = field(default_factory=list)
    extras: list[dict] = field(default_factory=list)
    avisos: list[Aviso] = field(default_factory=list)


def _primaria(f: Frequencia) -> str:
    if f.tipo == "dias":
        return f"{f.dias} dias"
    if f.tipo == "periodo":
        return f"{f.periodo.capitalize()} ({f.dias} dias)" + (f", referência {f.data_pivo}" if f.data_pivo else "")
    if f.tipo == "remover":
        return "Remover frequência parametrizada"
    if f.tipo == "estatistica":
        quem, origem = f.estatistica.rsplit("_", 1)
        return f"frequência de {quem} {'da empresa' if origem == 'empresa' else 'do vendedor'}"
    if f.tipo == "dinamica":
        texto = {
            "vendedor": "configurada pelo vendedor (padrão 7 dias)",
            "govendas": "frequência padrão do Govendas",
            "historico": "frequência do histórico do cliente",
            "qualquer_vendedor": "frequência de qualquer vendedor",
        }[f.fonte]
        if f.ajuste_dias:
            texto += f" {'mais' if f.ajuste_dias > 0 else 'menos'} {abs(f.ajuste_dias)} dias"
        return texto
    return f.bruta


def _frequencia(f: Frequencia | None) -> str:
    if f is None:
        return "Frequência não informada"
    if not f.reconhecida:
        return f.bruta
    texto = _primaria(f)
    alternativas = iter(f.alternativas)
    for parte in f.bruta.split(" ou ")[1:]:
        if parte.startswith(("no minimo", "no maximo")):
            limite = parte.replace("no minimo", "no mínimo").replace("no maximo", "no máximo")
            from ..parsing.parser import PERIODOS
            for periodo, dias in PERIODOS.items():
                limite = limite.replace(f"{periodo}()", f"{periodo.capitalize()} ({dias} dias)")
            texto += " ou " + limite
        else:
            texto += " ou " + _primaria(next(alternativas))
    return texto


_DIAS = {"seg": "segunda", "ter": "terça", "qua": "quarta", "qui": "quinta", "sex": "sexta",
         "sab": "sábado", "dom": "domingo", "uteis": "dias úteis"}


def _preferencia(p: Preferencia) -> str:
    if p.remover:
        texto = "remover preferência parametrizada"
    elif p.fonte:
        texto = "preferência do " + ("vendedor" if p.fonte == "vendedor" else "histórico")
    elif p.reconhecida:
        texto = ", ".join(f"{_DIAS[x.dia]} (peso {x.intensidade})" for x in p.itens)
    else:
        texto = p.bruta
    for a in p.alternativas:
        texto += " ou " + _preferencia(a)
    return texto


def _sufixo(historia: tuple[str, str] | None) -> str:
    if not historia:
        return ""
    return {"global": " (qualquer vendedor da empresa)", "vendedor": " (pelo vendedor)",
            "grupo": " (algum vendedor do mesmo grupo)"}[historia[1]]


def _texto_recencia(intervalos, historia, primeira=False) -> str:
    evento = "visita" if historia and historia[0] == "visita" else "compra"
    partes = []
    for lo, hi in intervalos:
        if lo == 0 and hi == INF:
            partes.append(f"qualquer tempo desde a última {evento}")
        elif hi == INF:
            partes.append(f"última {evento} há mais de {int(lo)} dias")
        elif lo == 0 and primeira:
            partes.append(f"última {evento} até {int(hi)} dias")
        else:
            partes.append(f"última {evento} entre {int(lo)} e {int(hi)} dias")
    return " ou ".join(partes) + _sufixo(historia)


def _literal_recencia(texto: str) -> str | None:
    a = interpretar_atomo(texto)
    if a is None:
        return None
    evento = "visita" if a.tipo == "visita" else "compra"
    numeros = re.findall(r"\d+", texto)
    if a.fora_entre:
        return f"última {evento} fora do intervalo de {numeros[0]} a {numeros[1]} dias" + _sufixo(a.historia)
    if a.fora_em is not None:
        return f"última {evento} há mais de {a.fora_em} dias" + _sufixo(a.historia)
    if len(numeros) == 1:
        return f"{evento} nos últimos {numeros[0]} dias" + _sufixo(a.historia)
    return f"última {evento} entre {numeros[0]} e {numeros[1]} dias" + _sufixo(a.historia)


def _condicao(p: Parametros, info: InfoRecencia, traducoes, tem_anteriores: bool) -> str:
    if not p.quando:
        texto = "Demais clientes do escopo" if tem_anteriores else "Todos os clientes do escopo"
        if info.texto_catch_all:
            texto += " com recência acima de " + info.texto_catch_all.removeprefix("mais de ")
    elif info.puro and not info.fora_entre and info.historia and (info.efetivo or info.intervalo):
        intervalos = info.efetivo or info.intervalo
        texto = _texto_recencia(intervalos, info.historia, primeira=bool(intervalos and intervalos[0][0] == 0))
    else:
        partes = []
        for c, ts in zip(p.quando, traducoes):
            atomos = separar_atomos(c.texto)
            fragmentos = [_literal_recencia(a) or (t.texto if t.chave is not None else a) for a, t in zip(atomos, ts)]
            if partes:
                partes.append(c.conector or "e")
            partes.append(" e ".join(fragmentos))
        texto = " ".join(partes)
    if p.filtros_temporais:
        texto = "Execução: " + " e ".join(f.bruta for f in p.filtros_temporais) + "; " + texto
    return texto


def _mapa_carteiras(arq: ArquivoGobr) -> dict[str, str]:
    mapa = {}
    for c in arq.carteiras:
        nomes = {n for t in c.clientes for n in re.findall(r'carteirafixa\s*\("([^"]+)"\)', t)}
        if len(nomes) == 1:
            mapa[c.nome] = next(iter(nomes))
    return mapa


def _avisos_prospect(arq: ArquivoGobr, mapa: dict[str, str]) -> set[int]:
    resultado = set()
    for i, p in enumerate(arq.parametros):
        atomos = [a for c in p.quando for t in separar_atomos(c.texto) if (a := interpretar_atomo(t))]
        negativas = {a.cadeia for a in atomos if a.fora_em is not None}
        positivas = {a.cadeia for a in atomos if a.fora_em is None and not a.fora_entre}
        for c in p.quando:
            for t in separar_atomos(c.texto):
                m = re.match(r"recencia de (positivacao|visita)(?: (global|do vendedor))? ", t)
                if m:
                    positivas.add("visita" if m[1] == "visita" else "positivacao_vendedor" if m[2] == "do vendedor" else "positivacao")
        if any(c.conector == "ou" or " ou " in c.texto for c in p.quando):
            positivas = set()
        if not negativas - positivas:
            continue
        for q in arq.parametros[i + 1:]:
            if chave_do_grupo(p, mapa) == chave_do_grupo(q, mapa) and any(
                a.startswith("no ciclo de vida prospect") for c in q.quando for a in separar_atomos(c.texto)
            ):
                resultado.add(p.linha_ini)
    return resultado


def gerar_esqueleto(caminho: str | Path) -> Esqueleto:
    arq = parse_file(caminho)
    mapa = _mapa_carteiras(arq)
    infos = analisar_arquivo(arq, mapa)
    prospect = _avisos_prospect(arq, mapa)
    cabecalho = {
        "arquivo": arq.caminho, "versao": arq.version,
        "times": [{"nome": t.nome, "vendedores": t.vendedores} for t in arq.times],
        "segmentacoes": [{"nome": s.nome, "clientes": s.clientes, "condicoes": tuple(c.texto for c in s.quando)} for s in arq.segmentacoes],
        "carteiras": [{"nome": c.nome, "tipo": c.tipo, "clientes": c.clientes, "condicoes": tuple(q.texto for q in c.quando)} for c in arq.carteiras],
        "carteira_padrao": None if arq.carteiras else "carteirafixa do time",
        "problemas_sintaxe": tuple(sorted(
            {(p.linha, p.mensagem) for p in arq.erros}
            | {(p.linha, p.mensagem) for p in arq.avisos if p.mensagem in _AVISOS_SINTAXE}
        )),
        "notas_sintaxe": tuple(sorted((p.linha, p.mensagem) for p in arq.avisos if p.mensagem in _NOTAS_SINTAXE)),
    }
    cabecalho["nivel_diagnostico"] = "erro" if cabecalho["problemas_sintaxe"] else "aviso" if cabecalho["notas_sintaxe"] else "nenhum"
    esqueleto = Esqueleto(cabecalho)
    for problema in arq.avisos:
        esqueleto.avisos.append(Aviso("parser", problema.linha, problema.mensagem))
    for problema in arq.erros:
        esqueleto.avisos.append(Aviso("erro_parser", problema.linha, problema.mensagem))
    escopos_anteriores = set()
    for p in arq.parametros:
        escopo = chave_do_grupo(p, mapa)
        info = infos[p.linha_ini]
        traducoes = [traduzir_condicao(c) for c in p.quando]
        observacoes = []

        def observar(tipo: str, mensagem: str) -> None:
            if mensagem not in observacoes:
                observacoes.append(mensagem)
                esqueleto.avisos.append(Aviso(tipo, p.linha_ini, mensagem))

        for ts in traducoes:
            for t in ts:
                if t.observacao:
                    observar("glossario_" + (t.status or "SEM_ENTRADA"), t.observacao)
                elif t.chave is None:
                    observar("glossario_SEM_ENTRADA", "⚠ condição sem tradução; literal preservado")
        if AVISO_MISTURA in info.notas:
            observar("historico_misto", AVISO_HISTORICO)
        if info.lacunas:
            observar("lacuna_catch_all", "também recebe clientes com recência " + texto_intervalos(info.lacunas))
        if info.bloqueios_anteriores:
            observar("bloqueios_anteriores", NOTA_BLOQUEIOS)
        if info.antecedentes:
            citados = "; ".join(info.antecedentes[:2])
            if len(info.antecedentes) > 2:
                citados += f"; +{len(info.antecedentes) - 2}"
            observar("precedentes", "pode haver clientes já tratados pela regra " + citados)
        if info.sombreamento_provado:
            observar("sombreamento_provado", SOMBREAMENTO_PROVADO)
        elif info.sombreado_sob_hipotese:
            observar("sombreado_sob_hipotese", SOMBREAMENTO_HIPOTESE)
        if p.linha_ini in prospect:
            observar("prospect_apos_fora", AVISO_PROSPECT)
        if info.fora_entre:
            for c in p.quando:
                for t in separar_atomos(c.texto):
                    a = interpretar_atomo(t)
                    if a and a.fora_entre:
                        numeros = re.findall(r"\d+", t)
                        observar("fora_entre", AVISO_FORA_ENTRE.format(a=numeros[0], b=numeros[1]))
        frequencia = "Não agendar" if p.nao_agendar else _frequencia(p.frequencia)
        if p.preferencia is not None:
            frequencia += "; preferência: " + _preferencia(p.preferencia)
        esqueleto.linhas.append(Linha(p.nome, _condicao(p, info, traducoes, escopo in escopos_anteriores), frequencia,
                                     "; ".join(observacoes), p.linha_ini, escopo,
                                     info.antecedentes, info))
        escopos_anteriores.add(escopo)
    for bloco in arq.blocos:
        if isinstance(bloco, BlocoBruto) and bloco.tipo in ("alerta", "tags"):
            esqueleto.extras.append({"tipo": bloco.tipo, "nome": bloco.nome, "linha": bloco.linha_ini, "linhas": bloco.linhas})
    return esqueleto


def _celula(texto: object) -> str:
    return re.sub(r"[\x00-\x08\x0b-\x1f]", lambda m: f"\\x{ord(m.group()):02x}", str(texto)).replace("|", "\\|").replace("\n", " ")


def renderizar_markdown(esqueleto: Esqueleto) -> str:
    c = esqueleto.cabecalho
    linhas = []
    if c.get("problemas_sintaxe"):
        descricao = "; ".join(f"linha {n}: {mensagem}" for n, mensagem in c["problemas_sintaxe"])
        linhas += ["> ⚠ arquivo com erro de sintaxe: " + _celula(descricao) + "; a tabela pode estar incompleta", ""]
    linhas += ["# " + _celula(c["arquivo"]), ""]
    if c.get("notas_sintaxe"):
        descricao = "; ".join(f"linha {n}: {mensagem}" for n, mensagem in c["notas_sintaxe"])
        linhas += ["> ⚠ aviso: " + _celula(descricao), ""]
    linhas += ["Versão: " + (c["versao"] or "não declarada")]
    for t in c["times"]:
        linhas.append(f"Time: {_celula(t['nome'])}; vendedores: {_celula(t['vendedores'])}")
    for titulo, chave in (("Segmentação", "segmentacoes"), ("Carteira", "carteiras")):
        for item in c[chave]:
            linhas.append(titulo + ": " + _celula(item["nome"]) + "; clientes: " + _celula("; ".join(item["clientes"]))
                          + ("; condição: " + _celula(" e ".join(item["condicoes"])) if item["condicoes"] else ""))
    if c["carteira_padrao"]:
        linhas.append("Carteira: " + c["carteira_padrao"])
    linhas += ["", "| Nome | Condição | Frequência | Observação |", "|---|---|---|---|"]
    linhas += ["| " + " | ".join(_celula(v) for v in (l.nome, l.condicao, l.frequencia, l.observacao)) + " |" for l in esqueleto.linhas]
    if esqueleto.extras:
        linhas += ["", "## Alertas e tags", ""]
        for e in esqueleto.extras:
            linhas.append(f"- {_celula(e['tipo'])} {_celula(e['nome'])} (linha {e['linha']}): " + _celula("; ".join(e["linhas"])))
    return "\n".join(linhas) + "\n"


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("caminho", type=Path)
    cli.add_argument("--out", type=Path)
    args = cli.parse_args(argv)
    caminhos = sorted(args.caminho.glob("*.gobr")) if args.caminho.is_dir() else [args.caminho]
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
    for caminho in caminhos:
        texto = renderizar_markdown(gerar_esqueleto(caminho))
        if args.out:
            (args.out / (caminho.stem + ".md")).write_text(texto, encoding="utf-8")
        else:
            print(texto, end="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
