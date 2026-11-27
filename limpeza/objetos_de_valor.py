from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class Categoria(StrEnum):
    CORRIGIDO = "corrigido"
    DESCARTADO = "descartado"
    DUVIDA = "duvida"
    AVISO = "aviso"


@dataclass
class Resultado:
    arquivos: list[ArquivoLido]
    precatorios: dict[str, Precatorio]
    pagamentos: ResultadoPagamentos
    diario: Diario
    referencia: date

    @property
    def tem_duvidas(self) -> bool:
        return bool(self.diario.da_categoria(Categoria.DUVIDA))


@dataclass
class ArquivoLido:
    nome: str
    sha256: str
    codificacao: str
    texto: str
    notas: list[str] = field(default_factory=list)


@dataclass
class LinhaCsv:
    linha: int  # número da linha no arquivo, contando o cabeçalho como 1
    campos: dict[str, str]


@dataclass
class ObjetoJson:
    indice: int  # posição na lista (0-based)
    linha: int  # linha do arquivo onde o objeto começa
    dados: object


@dataclass(frozen=True)
class Ocorrencia:
    categoria: Categoria
    regra: str
    arquivo: str
    linha: int | None
    registro: str
    detalhe: str


@dataclass
class Diario:
    # Diário de ocorrências utilizado por todas as regras
    itens: list[Ocorrencia] = field(default_factory=list)

    def registrar(
        self,
        categoria: Categoria,
        regra: str,
        arquivo: str,
        linha: int | None,
        registro: str,
        detalhe: str,
    ) -> None:
        self.itens.append(
            Ocorrencia(
                categoria=categoria,
                regra=regra,
                arquivo=arquivo,
                linha=linha,
                registro=registro,
                detalhe=detalhe,
            )
        )

    def da_categoria(self, categoria: Categoria) -> list[Ocorrencia]:
        return [o for o in self.itens if o.categoria == categoria]


@dataclass
class LinhaPrecatorio:
    """Uma linha de uma das fontes (tribunal ou hub), já normalizada."""
    numero_processo: str
    ente_devedor: str
    valor_face: Decimal
    linha: int
    apresentado_em: date | None = None
    prazo_informado: date | None = None


@dataclass
class Apresentacao:
    numero_processo: str
    data: date  # data civil em Brasília
    linha: int


@dataclass
class Precatorio:
    numero_processo: str
    ente_devedor: str
    valor_face: Decimal
    apresentado_em: date | None
    prazo_pagamento: date | None
    situacao: str  # conciliado | divergente | somente_tribunal | somente_hub
    dv_cnj_valido: bool
    pendencias: list[str] = field(default_factory=list)
    total_pago: Decimal = Decimal("0.00")
    situacao_prazo: str = "sem_prazo"  # vencido | a_vencer | em_dia | quitado | sem_prazo
    dias_para_prazo: int | None = None  # negativo = dias em atraso

    @property
    def saldo(self) -> Decimal:
        return self.valor_face - self.total_pago


@dataclass
class Pagamento:
    evento_id: str
    numero_processo: str
    tipo: str
    valor: Decimal  # como veio (positivo)
    data_pagamento: date
    atualizado_em: datetime | None
    linha: int

    @property
    def valor_assinado(self) -> Decimal:
        return -self.valor if self.tipo == "estorno" else self.valor


@dataclass
class EventoEmDuvida:
    linha: int
    motivos: list[str]
    original: object


@dataclass
class ResultadoPagamentos:
    aceitos: list[Pagamento] = field(default_factory=list)
    em_duvida: list[EventoEmDuvida] = field(default_factory=list)
    