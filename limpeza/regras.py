from dataclasses import dataclass, field
from enum import StrEnum


class Categoria(StrEnum):
    CORRIGIDO = "corrigido"
    DESCARTADO = "descartado"
    DUVIDA = "duvida"
    AVISO = "aviso"


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
        detalhe: str
    ) -> None:
        self.itens.append(
            Ocorrencia(
                categoria=categoria, 
                regra=regra, 
                arquivo=arquivo, 
                linha=linha, 
                registro=registro, 
                detalhe=detalhe
            )
        )

    def da_categoria(self, categoria: Categoria) -> list[Ocorrencia]:
        return [o for o in self.itens if o.categoria == categoria]
    