"""Modelo de dados do parser GOBR (camadas 1 e 2: estrutura dos blocos e cláusulas).

Os filtros `quando` NÃO são interpretados: ficam como linhas de texto normalizado.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Problema:
    """Aviso ou erro, com a linha (1-based) do arquivo."""

    arquivo: str
    linha: int
    mensagem: str
    trecho: str = ""


@dataclass(frozen=True)
class Condicao:
    """Uma linha lógica do `quando` (linhas físicas de listas entre parênteses vêm coladas)."""

    conector: str | None  # None na linha do `quando`; "e" ou "ou" nas seguintes
    texto: str  # normalizado, sem a palavra `quando` nem o conector
    assinatura: str  # `texto` com os números trocados por N
    linha: int
    bruta: str  # linha original inteira


@dataclass(frozen=True)
class Escopo:
    tipo: str  # "time" | "carteira" | "segmentacao"
    nomes: tuple[str, ...]  # nomes como escritos (caixa e acentos preservados)
    ligador: str | None  # "e" quando a linha começa com `e da ...`
    linha: int


@dataclass(frozen=True)
class SemChoque:
    alvo: str  # "time" | "carteira"
    nomes: tuple[str, ...]
    bruta: str
    linha: int


@dataclass(frozen=True)
class FiltroTemporal:
    """Filtro do capítulo 5 do manual (`na segunda`, `a partir do dia 16`, `na ultima semana`...).

    Dizem QUANDO a regra roda (data/hora de execução). Não confundir com `preferencia`
    (em que dia agendar) nem com o `restrito` da seção 7.5.

    Combinação (manual 5.1): filtros da mesma categoria valem como "ou" (`no dia 2 e no dia 12`
    = dia 2 ou dia 12) e categorias diferentes como "e". O parser só registra os filtros.

    `bruta` é o texto do filtro já normalizado (sem acentos, minúsculas). `valor` por categoria:
      dia_do_mes     {"forma", "inicio", "fim"}; inicio/fim são int ou "ultimo" (último dia do mês)
      dia_da_semana  tuple de "seg".."dom"
      semana_do_mes  1..4 ou "ultima"
      quinzena       1 ou 2
      mes_do_ano     tuple de meses 1..12 (bimestre, trimestre e semestre já expandidos)
      horario        {"forma": "as" | "de_hora_em_hora", "horarios": tuple, "inicio": str|None, "fim": str|None}
    """

    categoria: str
    bruta: str
    valor: object
    linha: int = 0


@dataclass(frozen=True)
class Frequencia:
    """Frequência normalizada. `tipo=None` significa forma não reconhecida (só `bruta` vale)."""

    bruta: str
    tipo: str | None = None  # "dias" | "periodo" | "dinamica" | "estatistica" | "remover"
    dias: int | None = None  # tipo dias: N; tipo periodo: equivalente em dias
    periodo: str | None = None  # "diaria" | "semanal" | "quinzenal" | "mensal" | "bimestral" | ...
    data_pivo: str | None = None  # de quinzenal('dd-mm-yyyy') e bimestral('dd-mm-yyyy')
    fonte: str | None = None  # tipo dinamica: "govendas" | "vendedor" | "historico" | "qualquer_vendedor"
    ajuste_dias: int = 0  # `mais N dias` = +N, `menos N dias` = -N (vale para qualquer fonte dinâmica)
    # tipo estatistica: a frequência MÉDIA dos clientes ativos/inativos da empresa ou do vendedor.
    # Valores: "ativos_empresa" | "inativos_empresa" | "ativos_vendedor" | "inativos_vendedor".
    estatistica: str | None = None
    minimo_dias: int | None = None  # `no minimo de N dias` ou `no minimo mensal()` (= 30)
    maximo_dias: int | None = None  # `no maximo de N dias` ou `no maximo semanal()` (= 7)
    alternativas: tuple[Frequencia, ...] = ()  # cadeia `ou` de fallbacks

    @property
    def reconhecida(self) -> bool:
        return self.tipo is not None


@dataclass(frozen=True)
class ItemPreferencia:
    dia: str  # "seg" | "ter" | "qua" | "qui" | "sex" | "sab" | "dom" | "uteis"
    intensidade: int  # menor = 1, normal/sem modificador = 2, maior = 3


@dataclass(frozen=True)
class Preferencia:
    bruta: str
    itens: tuple[ItemPreferencia, ...] = ()
    # Mapa seg..dom -> 0..3 quando estática (dia não citado = 0, `uteis` = seg..sex).
    # None com fonte dinâmica (`do vendedor`, `do historico`) ou `remover`.
    dias: dict[str, int] | None = None
    fonte: str | None = None  # None | "vendedor" | "historico"
    remover: bool = False
    alternativas: tuple[Preferencia, ...] = ()  # cadeia `ou`
    reconhecida: bool = True


@dataclass(kw_only=True)
class Bloco:
    nome: str
    linha_ini: int
    linha_fim: int
    incompleto: bool = False  # houve erro dentro do bloco
    nao_reconhecidas: tuple[tuple[int, str], ...] = ()  # (linha, texto) de linhas sem cláusula conhecida

    @property
    def rotulo(self) -> str:
        raise NotImplementedError


@dataclass(kw_only=True)
class Time(Bloco):
    vendedores: str = ""  # texto bruto depois de `vendedores`

    @property
    def rotulo(self) -> str:
        return "time"


@dataclass(kw_only=True)
class Carteira(Bloco):
    tipo: str = "exclusiva"  # "exclusiva" | "livre"
    clientes: tuple[str, ...] = ()  # textos brutos depois de `clientes`
    quando: tuple[Condicao, ...] = ()

    @property
    def rotulo(self) -> str:
        return f"carteira {self.tipo}"


@dataclass(kw_only=True)
class Segmentacao(Bloco):
    clientes: tuple[str, ...] = ()
    quando: tuple[Condicao, ...] = ()

    @property
    def rotulo(self) -> str:
        return "segmentacao"


@dataclass(kw_only=True)
class Parametros(Bloco):
    ordem: int = 0  # posição entre os blocos de regra (parametros e limpar parametros)
    escopos: tuple[Escopo, ...] = ()
    quando: tuple[Condicao, ...] = ()
    frequencia: Frequencia | None = None
    preferencia: Preferencia | None = None
    fixo: bool = False
    roteirizavel: bool = False
    nao_agendar: bool = False
    sem_choque: tuple[SemChoque, ...] = ()
    filtros_temporais: tuple[FiltroTemporal, ...] = ()

    @property
    def catch_all(self) -> bool:
        """Sem `quando`: pega os clientes restantes do seu escopo."""
        return not self.quando

    @property
    def depende_do_calendario(self) -> bool:
        """A regra só roda em certas datas ou horários (tem algum filtro temporal)."""
        return bool(self.filtros_temporais)

    @property
    def rotulo(self) -> str:
        return "parametros"


@dataclass(kw_only=True)
class LimparParametros(Bloco):
    ordem: int = 0
    escopos: tuple[Escopo, ...] = ()

    @property
    def rotulo(self) -> str:
        return "limpar parametros"


@dataclass(kw_only=True)
class BlocoBruto(Bloco):
    """`alerta` e `tags`: reconhecidos, mas não interpretados nesta camada."""

    tipo: str = "alerta"
    linhas: tuple[str, ...] = ()

    @property
    def rotulo(self) -> str:
        return self.tipo


@dataclass
class ArquivoGobr:
    caminho: str
    version: str | None = None
    blocos: list[Bloco] = field(default_factory=list)
    avisos: list[Problema] = field(default_factory=list)
    erros: list[Problema] = field(default_factory=list)

    def _de_tipo(self, cls):
        return [b for b in self.blocos if isinstance(b, cls)]

    @property
    def times(self) -> list[Time]:
        return self._de_tipo(Time)

    @property
    def carteiras(self) -> list[Carteira]:
        return self._de_tipo(Carteira)

    @property
    def segmentacoes(self) -> list[Segmentacao]:
        return self._de_tipo(Segmentacao)

    @property
    def parametros(self) -> list[Parametros]:
        return self._de_tipo(Parametros)

    @property
    def limpezas(self) -> list[LimparParametros]:
        return self._de_tipo(LimparParametros)
