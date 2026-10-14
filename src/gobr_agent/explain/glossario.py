"""Glossário determinístico: condição atômica do `quando` -> fragmento em português.

Chave = átomo normalizado com N no lugar de números e S no lugar de textos entre aspas
(`igual("a","b","c")` vira `igual(S)`; `N dia` vira `N dias`). O modelo usa `{N}` (números, na
ordem em que aparecem) e `{S}` (textos entre aspas, separados por vírgula).

Nada além do manual: cada entrada aponta as linhas do manual em que se apoia (página do PDF e
página impressa, entre colchetes na documentação). Átomo sem entrada sai como
`[sem tradução: <literal>]`.

Status:
  DEFINIDA       existe a linha da tabela (o `...` ou o `<<condicional de tempo>>` é preenchido por `em N dias`, `entre ...`)
  COMPOSICAO     não existe linha própria: linha-base do manual mais uma nota do manual (visita/positivação,
                 com a empresa/com o vendedor, igual/diferente...)
  ALIAS          variante de escrita do corpus de outra chave
  SEM_DEFINICAO  o manual não define; o literal sai sem expandir, com um aviso
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

from ..parsing.models import Condicao
from .atomos import separar_atomos

DEFINIDA, COMPOSICAO, ALIAS, SEM_DEFINICAO = "DEFINIDA", "COMPOSICAO", "ALIAS", "SEM_DEFINICAO"
STATUS = (DEFINIDA, COMPOSICAO, ALIAS, SEM_DEFINICAO)
AVISO_SEM_DEFINICAO = "⚠ condição sem definição no manual"


@dataclass(frozen=True)
class Fonte:
    pdf: int  # página do PDF
    impressa: int  # página impressa no rodapé
    trecho: str  # texto literal do manual


@dataclass(frozen=True)
class Entrada:
    chave: str
    modelo: str
    status: str
    fontes: tuple[Fonte, ...] = ()
    nota: str = ""
    alias_de: str | None = None


@dataclass(frozen=True)
class Traducao:
    texto: str
    chave: str | None  # None quando o átomo não está no glossário
    status: str | None
    traduzido: bool  # True só para DEFINIDA, COMPOSICAO e ALIAS
    observacao: str | None = None


def F(pdf: int, impressa: int, trecho: str) -> Fonte:
    return Fonte(pdf, impressa, trecho)


# ------------------------------------------------------------ trechos literais do manual (cap. 6)
_VISITA_GRUPO = F(28, 24, "Clientes cuja última visita ocorreu no intervalo especificado por algum vendedor do mesmo grupo do vendedor que tem o cliente na carteira")
_FORA_VISITA_GRUPO = F(28, 24, "Clientes cuja última visita ocorreu fora do intervalo especificado por algum vendedor do mesmo grupo do vendedor que tem o cliente na carteira")
_VISITA_VENDEDOR = F(28, 24, "Clientes cuja última visita ocorreu no intervalo especificado foi do vendedor que tem o cliente na carteira")
_GLOBAL = F(28, 24, "Clientes cuja última positivação ocorreu no intervalo especificado por qualquer vendedor da empresa")
_FORA_GLOBAL_VISITA = F(28, 24, "Clientes cuja última visita ocorreu fora do intervalo especificado por qualquer vendedor da empresa")
_FORA_POSIT_VENDEDOR = F(28, 24, "Clientes cuja última positivação ocorreu fora do intervalo especificado foi do vendedor que tem o cliente na carteira")
_NOTA_VISITA_POSIT = F(28, 24, "As duas opções são possíveis: visita ou positivação.")
_EM_N_DIAS = F(39, 35, "em <<N>> dias: dentro do intervalo dos dias especificados")
_ENTRE_TEMPO = F(40, 36, "entre <<tempo>> e <<tempo>>: intervalo de tempo definido")
_NA_SEMANA = F(39, 35, "na semana: intervalo que compreende a semana atual")
_NO_MES = F(40, 36, "no mês: intervalo que compreende o mês atual")
_NO_ANO = F(40, 36, "no ano: intervalo que compreende o ano atual")
_NOTA_EMPRESA_VENDEDOR = F(33, 29, "As opções para os filtros são com a empresa ou com o vendedor.")
_NOTA_TEXTOS = F(32, 28, "As opções para todos os filtros com textos são: ìgual, diferente, contém e inicia com")
_NOTA_IDS = F(32, 28, "As opções para todos os filtros com id são: são: ìgual e diferente")
_RAMO = F(32, 28, "ramo de atividade igual(\"1\", \"12\"): Filtro por id do ramo de atividade comercial igual a um dos valores")
_NOTA_VALORES = F(29, 25, "Também podem ser combinados maior que, menor que e igual a utilizando um e.")
_NOTA_INDEFINIDO = F(29, 25, "Para os filtros de ticket médio e faturamento, o parâmetro ou indefinido pode ser adicionado ao final para incluir também os clientes cujo valor é desconhecido no sistema.")
_NOTA_VENDA = F(27, 23, "As opções venda podem ser: do vendedor ou da empresa.")
_NAO_TEM_VENDA = F(27, 23, "não tem venda <<condicional de tempo>>: Clientes que não tem venda de nenhum vendedor do mesmo grupo no período especificado")

_REC_BASE = (_VISITA_GRUPO, _NOTA_VISITA_POSIT)
_REC_BASE_FORA = (_FORA_VISITA_GRUPO, _NOTA_VISITA_POSIT)
_REC_VEND = (_VISITA_VENDEDOR, _NOTA_VISITA_POSIT)
_GRUPO = "por algum vendedor do mesmo grupo do vendedor que tem o cliente na carteira"
_VEND_CART = "foi do vendedor que tem o cliente na carteira"
_EMPRESA = "por qualquer vendedor da empresa"


def _entradas() -> list[Entrada]:
    d, c = DEFINIDA, COMPOSICAO
    cliente_filial = Entrada(
        "cliente filial", "o registro é uma filial", d, (F(31, 27, "cliente filial: O registro é uma filial"),)
    )
    entradas = [
        # --- 6.1 atividade e inatividade
        Entrada("ativos para o vendedor", "clientes ativos segundo o histórico do vendedor específico", d,
                (F(26, 22, "Clientes ativos segundo o histórico do vendedor específico"),)),
        Entrada("ativos para a empresa", "clientes ativos segundo o histórico de qualquer vendedor da empresa", d,
                (F(26, 22, "Clientes ativos segundo o histórico de qualquer vendedor da empresa"),)),
        Entrada("inativos para o vendedor", "clientes sem compra com o vendedor específico há tempo suficiente para serem inativos", d,
                (F(26, 22, "Clientes sem compra com o vendedor específico há tempo suficiente para serem inativos"),)),
        Entrada("inativos para a empresa", "clientes sem compra com nenhum vendedor da empresa", d,
                (F(26, 22, "Clientes sem compra com nenhum vendedor da empresa"),)),
        Entrada("inatividade de N dias", "clientes sem compra há pelo menos {N} dias", d,
                (F(26, 22, "Clientes sem compra há pelo menos N dias («tempo»)"),)),
        Entrada("unica compra com a empresa", "clientes que só compraram uma única vez com a empresa", d,
                (F(26, 22, "Clientes que só compraram uma única vez com a empresa"),)),
        Entrada("unica compra com o vendedor", "clientes que só compraram uma única vez com o vendedor", d,
                (F(27, 23, "Clientes que só compraram uma única vez com o vendedor"),)),
        Entrada("atividade do vendedor de N dias", "cliente comprou do vendedor no período de {N} dias", d,
                (F(27, 23, "atividade do vendedor de <<tempo>>: Se o cliente comprou do vendedor no tempo especificado"),
                 F(37, 33, "<<N>> dias: O tempo é uma regra que referencia um período"))),
        Entrada("tem venda da empresa entre N dias e N dias", "clientes que compraram de qualquer vendedor entre {N} e {N} dias", d,
                (F(27, 23, "tem venda da empresa <<condicional de tempo>>: Clientes que compraram de qualquer vendedor no período especificado"), _ENTRE_TEMPO)),
        Entrada("nao tem venda em N dias", "clientes sem venda de nenhum vendedor do mesmo grupo em {N} dias", c,
                (_NAO_TEM_VENDA, _EM_N_DIAS)),
        Entrada("nao tem venda da empresa no ano", "clientes que não têm venda da empresa no ano atual", c,
                (_NAO_TEM_VENDA, _NOTA_VENDA, _NO_ANO)),
        # --- 6.2 recência (visita e positivação)
        Entrada("recencia de visita em N dias", "última visita nos últimos {N} dias, " + _GRUPO, d, (_VISITA_GRUPO, _EM_N_DIAS)),
        Entrada("recencia de visita entre N dias e N dias", "última visita entre {N} e {N} dias, " + _GRUPO, d, (_VISITA_GRUPO, _ENTRE_TEMPO)),
        Entrada("fora da recencia de visita em N dias", "última visita fora dos últimos {N} dias, " + _GRUPO, d, (_FORA_VISITA_GRUPO, _EM_N_DIAS)),
        Entrada("recencia de visita na semana", "última visita na semana atual, " + _GRUPO, d, (_VISITA_GRUPO, _NA_SEMANA)),
        Entrada("recencia de positivacao em N dias", "última positivação nos últimos {N} dias, " + _GRUPO, c, _REC_BASE + (_EM_N_DIAS,),
                "O manual só traz a linha `recencia de visita`; positivação vem da nota da tabela."),
        Entrada("recencia de positivacao entre N dias e N dias", "última positivação entre {N} e {N} dias, " + _GRUPO, c, _REC_BASE + (_ENTRE_TEMPO,)),
        Entrada("recencia de positivacao no mes", "última positivação no mês atual, " + _GRUPO, c, _REC_BASE + (_NO_MES,)),
        Entrada("recencia de positivacao global em N dias", "última positivação nos últimos {N} dias, " + _EMPRESA, d, (_GLOBAL, _EM_N_DIAS)),
        Entrada("recencia de positivacao global entre N dias e N dias", "última positivação entre {N} e {N} dias, " + _EMPRESA, d, (_GLOBAL, _ENTRE_TEMPO)),
        Entrada("recencia de positivacao do vendedor em N dias", "última positivação nos últimos {N} dias " + _VEND_CART, c, _REC_VEND + (_EM_N_DIAS,)),
        Entrada("recencia de positivacao do vendedor entre N dias e N dias", "última positivação entre {N} e {N} dias " + _VEND_CART, c, _REC_VEND + (_ENTRE_TEMPO,)),
        Entrada("fora da recencia de positivacao em N dias", "última positivação fora dos últimos {N} dias, " + _GRUPO, c, _REC_BASE_FORA + (_EM_N_DIAS,)),
        Entrada("fora da recencia de positivacao entre N dias e N dias", "última positivação fora do intervalo entre {N} e {N} dias, " + _GRUPO, c, _REC_BASE_FORA + (_ENTRE_TEMPO,)),
        Entrada("fora da recencia de positivacao global em N dias", "última positivação fora dos últimos {N} dias, " + _EMPRESA, c, (_FORA_GLOBAL_VISITA, _NOTA_VISITA_POSIT, _EM_N_DIAS)),
        Entrada("fora da recencia de positivacao global entre N dias e N dias", "última positivação fora do intervalo entre {N} e {N} dias, " + _EMPRESA, c, (_FORA_GLOBAL_VISITA, _NOTA_VISITA_POSIT, _ENTRE_TEMPO)),
        Entrada("fora da recencia de positivacao do vendedor em N dias", "última positivação fora dos últimos {N} dias " + _VEND_CART, d, (_FORA_POSIT_VENDEDOR, _EM_N_DIAS)),
        Entrada("fora da recencia de positivacao do vendedor entre N dias e N dias", "última positivação fora do intervalo entre {N} e {N} dias " + _VEND_CART, d, (_FORA_POSIT_VENDEDOR, _ENTRE_TEMPO)),
        # --- 6.3 financeiros
        Entrada("inadimplentes", "clientes com pendências financeiras em aberto", d, (F(28, 24, "Clientes com pendências financeiras em aberto"),)),
        Entrada("adimplentes", "clientes sem pendências financeiras em aberto", d, (F(28, 24, "Clientes sem pendências financeiras em aberto"),)),
        Entrada("nao tem credito", "clientes sem crédito disponível", d, (F(28, 24, "Clientes sem crédito disponível"),)),
        Entrada("com N% de credito", "clientes com a porcentagem de crédito, em relação ao limite, maior ou igual a {N}%", d,
                (F(29, 25, "Clientes com a porcentagem de crédito, em relação ao limite, maior ou igual a especificada"),)),
        Entrada("com menos de r$ N de credito disponivel", "clientes com crédito disponível abaixo de R$ {N}", d,
                (F(29, 25, "Clientes com crédito disponível abaixo do valor especificado"),)),
        Entrada("total faturado no ano com a empresa maior que r$ N", "faturamento total no ano com a empresa acima de R$ {N}", d,
                (F(29, 25, "Clientes com faturamento acima do valor no período"),)),
        Entrada("total faturado no ano com a empresa menor que r$ N ou indefinido", "faturamento total no ano com a empresa abaixo de R$ {N}, ou valor indefinido", c,
                (F(29, 25, "Clientes com faturamento acima do valor no período"), _NOTA_VALORES, _NOTA_INDEFINIDO)),
        Entrada("media faturada no ano com a empresa maior que r$ N", "faturamento médio por mês no ano com a empresa maior que R$ {N}", c,
                (F(29, 25, "media faturada no <<periodo>> com a empresa menor que R$ <<valor>> e maior que R$ <<valor>>: Clientes com faturamento medio por mês no período dentro dos valores especificados"), _NOTA_VALORES)),
        # --- 6.5 localização e classificação
        Entrada("nome da cidade igual(S)", "clientes na cidade: {S}", d, (F(30, 26, "nome da cidade igual(\"cidade1\", \"cidade2\"): Clientes na cidade especificada"),)),
        Entrada("nome do bairro igual(S)", "clientes no bairro: {S}", c,
                (F(30, 26, "nome do bairro diferente(...): Clientes em bairro diferente da especificada"), _NOTA_TEXTOS)),
        Entrada("uf do estado igual(S)", "UF do estado igual a: {S}", c,
                (F(30, 26, "uf do estado contém(\"SP\", \"MG\"): Clientes cujo nome da UF do estado contém o texto informado"), _NOTA_TEXTOS)),
        Entrada("o rotulo contem(S)", "rótulo de classificação contém: {S}", c,
                (F(31, 27, "o rótulo diferente(...): Clientes cujo rótulo de classificação é diferente de todos os valores especificados"), _NOTA_TEXTOS)),
        Entrada("cnae igual(S)", "CNAE (mapeado pelo Govendas) igual a um de {S}", d,
                (F(31, 27, "cnae igual(...): Clientes cujo id do cnae mapeado pelo govendas é igual a um dos ids especificados"),),
                "No corpus o `é` antes de `igual` (`cnae é igual(...)`) é verbo: o átomo é o mesmo."),
        Entrada("status na receita federal definido como baixada", "empresa baixada na Receita Federal", d, (F(31, 27, "status na receita federal definido como baixada: Empresa baixada"),)),
        Entrada("pessoa fisica", "clientes pessoa física (CPF)", d, (F(31, 27, "Apenas clientes pessoa física (CPF)"),)),
        Entrada("pessoa juridica", "clientes pessoa jurídica (CNPJ)", d, (F(31, 27, "Apenas clientes pessoa jurídica (CNPJ)"),)),
        cliente_filial,
        Entrada("bloqueados", "clientes bloqueados para atendimento", d, (F(31, 27, "Clientes bloqueados para atendimento"),)),
        # --- 6.6 classificação por id
        Entrada("ramo de atividade igual(S)", "ramo de atividade: um de {S}", d, (_RAMO,),
                "O manual (p.32 [28]) exemplifica com ids (\"1\", \"12\"); o corpus usa ids e também nomes. O texto não diz qual."),
        Entrada("ramo de atividade diferente(S)", "ramo de atividade: diferente de {S}", c, (_RAMO, _NOTA_IDS)),
        Entrada("codigo da rota igual(S)", "código da rota: um de {S}", c,
                (F(32, 28, "código da rota diferente(\"4\", \"7\", \"14\"): Filtro por código da rota diferente dos valores"), _NOTA_IDS)),
        Entrada("tipo de cobranca igual(S)", "tipo de cobrança: um de {S}", c,
                (F(32, 28, "tipo de cobranca diferente(...): Filtra por id de cobrança diferente dos valores"), _NOTA_IDS)),
        Entrada("id do cliente principal diferente(S)", "id do cliente principal diferente de {S}", d,
                (F(32, 28, "id do cliente principal diferente(...): Filtro por id do cliente principal diferente do especificado"),),
                "No corpus o `é` antes de `diferente` é verbo: o átomo é o mesmo."),
        # --- 6.7 curva ABC e ciclo de vida
        Entrada("curva a com a empresa", "clientes da curva A de faturamento com a empresa", d, (F(32, 28, "Clientes da curva A de faturamento com a empresa"),)),
        Entrada("curva b com a empresa", "clientes da curva B de faturamento com a empresa", d, (F(32, 28, "Clientes da curva B de faturamento com a empresa"),)),
        Entrada("curva c com a empresa", "clientes da curva C de faturamento com a empresa", d, (F(32, 28, "Clientes da curva C de faturamento com a empresa"),)),
        Entrada("no ciclo de vida prospect com o vendedor", "cliente prospect no ciclo de vida do vendedor", d, (F(33, 29, "Cliente prospect no ciclo de vida do vendedor"),)),
        Entrada("no ciclo de vida prospect com a empresa", "cliente prospect no ciclo de vida da empresa", c,
                (F(33, 29, "no ciclo de vida prospect com o vendedor: Cliente prospect no ciclo de vida do vendedor"), _NOTA_EMPRESA_VENDEDOR)),
        Entrada("no ciclo de vida ativo com a empresa", "cliente ativo no ciclo de vida da empresa, fez alguma compra", c,
                (F(33, 29, "no ciclo de vida ativo com o vendedor: Cliente ativo no ciclo de vida do vendedor, fez alguma compra"), _NOTA_EMPRESA_VENDEDOR)),
        Entrada("no ciclo de vida inativo com a empresa", "cliente inativo no ciclo de vida da empresa", d, (F(33, 29, "Cliente inativo no ciclo de vida da empresa"),)),
        # --- 6.8 frequência histórica
        Entrada("frequencia historica menor que N dias", "frequência histórica do cliente menor que {N} dias", c,
                (F(33, 29, "frequencia historica menor que <<N>> dias ou indefinida: A frequência histórica do cliente é menor que N dias ou não foi possível ser calculada"),
                 F(34, 30, "O filtro “frequencia historica” pode incluir a opção indefinida.")),
                "A forma do corpus não traz `ou indefinida`: só `menor que`."),
        Entrada("frequencia historica maior que N dias", "frequência histórica do cliente maior que {N} dias", d, (F(33, 29, "A frequência histórica do cliente é maior que N dias"),)),
        Entrada("frequencia historica entre N dias e N dias", "frequência histórica do cliente entre {N} e {N} dias", d,
                (F(33, 29, "A frequência histórica do cliente está no intervalor que N dias e Y dias"),)),
        # --- 6.9 segmentação
        Entrada("contido na segmentacao(S)", "cliente pertence às segmentações: {S}", d, (F(34, 30, "O cliente pertence às segmentações especificadas"),)),
        Entrada("nao contido na segmentacao(S)", "cliente não pertence às segmentações: {S}", d, (F(34, 30, "O cliente não pertence à segmentação especificada"),)),
        # --- 6.11 outros
        Entrada("cadastrado faz N dias", "clientes cadastrados no ERP há no mínimo {N} dias", d,
                (F(36, 32, "cadastrado faz 90 dias: Clientes que foram cadastrados no ERP em no mínimo 90 dias («tempo»)"),)),
        Entrada("cadastrado a partir do dia 'N-N-N'", "clientes cadastrados no ERP após o dia {N}-{N}-{N}", d,
                (F(36, 32, "cadastrado a partir do dia '2026-02-10': Clientes que foram cadastrados após um dia especificado"),)),
        Entrada("data da rota na semana", "clientes com data de rota na semana atual", c,
                (F(36, 32, "data da rota no mês anterior: Clientes cuja data de rota compreendem somente o mês anterior"), _NA_SEMANA)),
        # --- sem definição no manual
        Entrada("sem venda", "sem venda", SEM_DEFINICAO, (),
                "114 linhas; 52 na regra padrão do Govendas; em 0 de 97 arquivos coexiste com `no ciclo de vida prospect com a empresa` "
                "no mesmo escopo. O manual só traz `sem venda ou prospects` (p.26 [22]): forma diferente, não assumida."),
        Entrada("sem vendas", "sem vendas", SEM_DEFINICAO, (), "O manual não tem `sem vendas`. Os blocos do corpus se chamam \"clientes sem venda\"."),
        Entrada("sem venda do vendedor", "sem venda do vendedor", SEM_DEFINICAO, (),
                "O manual não tem `sem venda do vendedor`. Os blocos do corpus se chamam \"Primeira compra\", \"Cliente potencial\"."),
    ]
    entradas.append(
        replace(
            cliente_filial,
            chave="e o cliente filial",
            status=ALIAS,
            alias_de="cliente filial",
            nota="12 blocos \"Não agendar filiais\" (regra_116, 129, 145, 172, 175, 180, 201, 206, 208, 209, 210, 244); "
            "5 estão escritos com acento (`quando é o cliente filial`): o verbo \"é\" perde o acento na normalização.",
        )
    )
    return entradas


GLOSSARIO: dict[str, Entrada] = {e.chave: e for e in _entradas()}

# ------------------------------------------------------------------------------ tradução


def decompor(atomo: str) -> tuple[str, list[str], list[str]]:
    """(chave, números, textos entre aspas) de um átomo normalizado."""
    textos = re.findall(r'"([^"]*)"', atomo)
    chave = re.sub(r"S(?:,S)+", "S", re.sub(r'"[^"]*"', "S", atomo))
    numeros = re.findall(r"\d+", chave)
    chave = re.sub(r"\bN dia\b", "N dias", re.sub(r"\d+", "N", chave))
    return chave, numeros, textos


def _preencher(modelo: str, numeros: list[str], textos: list[str]) -> str:
    restantes = iter(numeros)
    return re.sub(r"\{N\}", lambda _: next(restantes), modelo).replace("{S}", ", ".join(textos))


def traduzir_atomo(atomo: str, textos: list[str] | None = None) -> Traducao:
    """Traduz um átomo normalizado. `textos` permite passar os textos entre aspas com a caixa original."""
    chave, numeros, textos_do_atomo = decompor(atomo)
    entrada = GLOSSARIO.get(chave)
    if entrada is None:
        return Traducao(f"[sem tradução: {atomo}]", None, None, False)
    if entrada.status == SEM_DEFINICAO:
        return Traducao(atomo, chave, SEM_DEFINICAO, False, AVISO_SEM_DEFINICAO)
    return Traducao(_preencher(entrada.modelo, numeros, textos or textos_do_atomo), chave, entrada.status, True)


def traduzir_condicao(condicao: Condicao) -> list[Traducao]:
    """Traduz cada átomo de uma linha de `quando`, mantendo a caixa original dos textos entre aspas."""
    originais = iter(re.findall(r'"([^"]*)"', condicao.bruta))
    traducoes = []
    for atomo in separar_atomos(condicao.texto):
        n_textos = len(re.findall(r'"[^"]*"', atomo))
        traducoes.append(traduzir_atomo(atomo, [next(originais, "") for _ in range(n_textos)]))
    return traducoes
