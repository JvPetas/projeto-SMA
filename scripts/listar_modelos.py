"""Lista capacidades e limites dos modelos disponíveis na configuração local."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import logging
from pathlib import Path
import sys
import warnings

ROOT = Path(__file__).resolve().parents[1]


def _campo(modelo, nome):
    return modelo.get(nome) if isinstance(modelo, dict) else getattr(modelo, nome, None)


def _dimensoes(modelo):
    informadas = set()
    for campo in ("supported_output_dimensions", "output_dimensions", "embedding_dimensions",
                  "embedding_dimension", "output_dimensionality", "dimensions"):
        valor = _campo(modelo, campo)
        for n in valor if isinstance(valor, (list, tuple)) else (valor,):
            if type(n) is int and n > 0:
                informadas.add(n)
    return sorted(informadas)


def listar(client):
    grupos = {"generateContent": [], "embedContent": []}
    for modelo in client.models.list():
        acoes = _campo(modelo, "supported_actions") or []
        for acao, registros in grupos.items():
            if acao in acoes:
                registros.append({"nome": _campo(modelo, "name") or "nome não informado",
                                  "entrada": _campo(modelo, "input_token_limit"),
                                  "saida": _campo(modelo, "output_token_limit"),
                                  "dimensoes": _dimensoes(modelo)})
    for registros in grupos.values():
        registros.sort(key=lambda r: r["nome"])
    return grupos


def imprimir(grupos, segredo):
    def seguro(valor):
        return " ".join(str(valor).replace(segredo, "[oculto]").split()).replace("|", r"\|")

    print("\nGeração de conteúdo (generateContent):")
    print("| Modelo | Limite de entrada (tokens) | Limite de saída (tokens) |")
    print("|---|---:|---:|")
    for r in grupos["generateContent"]:
        entrada = r["entrada"] if type(r["entrada"]) is int else "não informado"
        saida = r["saida"] if type(r["saida"]) is int else "não informado"
        print(f"| {seguro(r['nome'])} | {entrada} | {saida} |")
    print(f"Total: {len(grupos['generateContent'])}")
    print("\nEmbeddings (embedContent):")
    print("| Modelo | Dimensões informadas pela API |")
    print("|---|---|")
    for r in grupos["embedContent"]:
        dimensoes = ", ".join(str(n) for n in r["dimensoes"]) or "não informadas"
        print(f"| {seguro(r['nome'])} | {dimensoes} |")
    print(f"Total: {len(grupos['embedContent'])}")
    print("\nNenhum modelo escolhido; parada ao fim da Fase 1.")


def main(argv=None, *, client_factory=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--env", type=Path, default=ROOT / ".env")
    args = cli.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not args.env.is_file():
        print(".env: ausente; execução interrompida.")
        return 1
    print(".env: existe")
    try:
        from dotenv import dotenv_values
        valores = dotenv_values(args.env, encoding="utf-8-sig", interpolate=False, verbose=False)
        segredo = (valores.get("GEMINI_API_KEY") or "").strip()
    except Exception:
        print("Não foi possível ler a configuração local; execução interrompida.")
        return 1
    if not segredo:
        print("Chave: vazia ou ausente; execução interrompida.")
        return 1
    print("Chave: preenchida (valor não exibido)")
    nivel_anterior = logging.root.manager.disable
    try:
        # Respostas e exceções do cliente não são enviadas à saída nem a arquivos.
        logging.disable(logging.CRITICAL)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if client_factory is None:
                from google import genai
                client_factory = genai.Client
            client = client_factory(api_key=segredo, vertexai=False, http_options={"timeout": 30000})
            try:
                grupos = listar(client)
            finally:
                client.close()
    except Exception as exc:
        codigo = getattr(exc, "code", None)
        http = f" (HTTP {codigo})" if type(codigo) is int else ""
        print("Falha ao listar modelos" + http + "; confira a conexão e as permissões. Detalhes omitidos.", file=sys.stderr)
        return 1
    finally:
        logging.disable(nivel_anterior)
    imprimir(grupos, segredo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
