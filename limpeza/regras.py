from dataclasses import dataclass, field
from enum import StrEnum
from datetime import date
from decimal import Decimal

from .leitura import LinhaCsv, ObjetoJson
from .normalizacao import (
    ErroNormalizacao,
    normalizar_cnj,
    normalizar_data_apresentacao,
    normalizar_valor,
)


ZERO = Decimal("0.00")


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
    

def _normalizar_linha_precatorio(
    linha: LinhaCsv, 
    arquivo: str, 
    diario: Diario, 
    *,
    col_processo: str, 
    col_ente: str, 
    col_valor: str
) -> LinhaPrecatorio | None:
    campos = linha.campos
    if "__erro__" in campos:
        diario.registrar(
            categoria=Categoria.DUVIDA, 
            regra="LINHA_MALFORMADA", 
            arquivo=arquivo, 
            linha=linha.linha, 
            registro="?", 
            detalhe=campos["__erro__"]
        )        
        return None
    
    bruto = campos[col_processo]
    try:
        processo = normalizar_cnj(bruto)
    except ErroNormalizacao as exc:
        diario.registrar(
            categoria=Categoria.DUVIDA, 
            regra="PROCESSO_INVALIDO", 
            arquivo=arquivo, 
            linha=linha.linha, 
            registro=bruto or "(vazio)", 
            detalhe=str(exc)
        )
        return None
    
    if processo.nota:
        diario.registrar(
            categoria=Categoria.CORRIGIDO, 
            regra="PROCESSO_SEM_MASCARA", 
            arquivo=arquivo, 
            linha=linha.linha, 
            registro=processo.valor, 
            detalhe=processo.nota
        )

    ente = campos[col_ente]
    if not ente:
        diario.registrar(
            categoria=Categoria.DUVIDA, 
            regra="ENTE_AUSENTE", 
            arquivo=arquivo, 
            linha=linha.linha, 
            registro=processo.valor, 
            detalhe="ente devedor vazio"
        )
        return None
    if "�" in ente:
        diario.registrar(
            categoria=Categoria.AVISO, 
            regra="ENTE_COM_ACENTO_PERDIDO", 
            arquivo=arquivo, 
            linha=linha.linha, 
            registro=processo.valor,
            detalhe=f"nome do ente com caracteres perdidos: {ente!r}"
        )

    try:
        valor = normalizar_valor(campos[col_valor])
    except ErroNormalizacao as exc:
        diario.registrar(
            categoria=Categoria.DUVIDA, 
            regra="VALOR_FACE_INVALIDO", 
            arquivo=arquivo, 
            linha=linha.linha, 
            registro=processo.valor, 
            detalhe=str(exc)
        )
        return None
    
    if valor.nota:
        diario.registrar(
            categoria=Categoria.CORRIGIDO, 
            regra="VALOR_FORMATO_BR", 
            arquivo=arquivo, 
            linha=linha.linha, 
            registro=processo.valor, 
            detalhe=valor.nota
        )
    if valor.valor <= ZERO:
        diario.registrar(
            categoria=Categoria.DUVIDA, 
            regra="VALOR_FACE_NAO_POSITIVO", 
            arquivo=arquivo, 
            linha=linha.linha, 
            registro=processo.valor,
            detalhe=f"valor de face {valor.valor}"
        )
        return None
    
    return LinhaPrecatorio(
        numero_processo=processo.valor, 
        ente_devedor=ente, 
        valor_face=valor.valor, 
        linha=linha.linha
    )


def _indexar(
    linhas: list[LinhaPrecatorio], arquivo: str, diario: Diario
) -> dict[str, LinhaPrecatorio]:
    """Indexa por processo. Repetição idêntica é descartada; com dados diferentes, vira dúvida."""
    indice: dict[str, LinhaPrecatorio] = {}

    for item in linhas:
        anterior = indice.get(item.numero_processo)
        if anterior is None:
            indice[item.numero_processo] = item
            continue

        mesmos = (anterior.ente_devedor, anterior.valor_face, anterior.apresentado_em) == (
            item.ente_devedor, item.valor_face, item.apresentado_em)

        dados_registro = dict(
            categoria=Categoria.DUVIDA, 
            regra="PRECATORIO_DUPLICADO_DIVERGENTE", 
            arquivo=arquivo, 
            linha=item.linha,
            registro=item.numero_processo,
            detalhe=f"mesmo processo da linha {anterior.linha} com dados diferentes; mantida a linha {anterior.linha}"
        )

        if mesmos:
            dados_registro["categoria"] = Categoria.DESCARTADO
            dados_registro["regra"] = "PRECATORIO_DUPLICADO"
            dados_registro["detalhe"] = f"repete a linha {anterior.linha} com os mesmos dados"

        diario.registrar(**dados_registro)

    return indice


def ler_tribunal(
    linhas: list[LinhaCsv], 
    arquivo: str, 
    diario: Diario
) -> dict[str, LinhaPrecatorio]:
    normalizadas = [
        p for linha in linhas
        if (p := _normalizar_linha_precatorio(
                linha=linha, 
                arquivo=arquivo, 
                diario=diario, 
                col_processo="numero_processo", 
                col_ente="ente_devedor", 
                col_valor="valor_face"
            )
        )
    ]
    return _indexar(
        linhas=normalizadas, 
        arquivo=arquivo, 
        diario=diario
    )


def ler_hub(
    linhas: list[LinhaCsv], 
    arquivo: str, 
    diario: Diario
) -> dict[str, LinhaPrecatorio]:
    normalizadas: list[LinhaPrecatorio] = []
    for linha in linhas:
        p = _normalizar_linha_precatorio(
            linha=linha, 
            arquivo=arquivo, 
            diario=diario, 
            col_processo="processo",                                 
            col_ente="ente", 
            col_valor="valor_face"
        )
        if p is None:
            continue

        try:
            apresentado = normalizar_data_apresentacao(bruto=linha.campos["apresentado_em"])
            p.apresentado_em = apresentado.valor
            if apresentado.nota:
                diario.registrar(
                    categoria=Categoria.CORRIGIDO, 
                    regra="APRESENTACAO_COM_FUSO", 
                    arquivo=arquivo, 
                    linha=linha.linha,
                    registro=p.numero_processo, 
                    detalhe=apresentado.nota
                )
        except ErroNormalizacao as exc:
            diario.registrar(
                categoria=Categoria.AVISO, 
                regra="APRESENTACAO_INVALIDA", 
                arquivo=arquivo, 
                linha=linha.linha, 
                registro=p.numero_processo,
                detalhe=f"{exc}; prazo não calculado"
            )
            
        try:
            p.prazo_informado = date.fromisoformat(linha.campos["prazo_pagamento"])
        except ValueError:
            pass  # o prazo é recalculado de qualquer forma

        normalizadas.append(p)

    return _indexar(normalizadas, arquivo, diario)


def ler_apresentacoes(
    objetos: list[ObjetoJson], 
    arquivo: str, 
    diario: Diario
) -> dict[str, Apresentacao]:
    """Datas de apresentação por processo (apresentacoes.json, arquivo não documentado no leiaute)."""
    indice: dict[str, Apresentacao] = {}

    for o in objetos:
        d = o.dados
        if not isinstance(d, dict):
            diario.registrar(
                categoria=Categoria.DUVIDA, 
                regra="REGISTRO_INVALIDO", 
                arquivo=arquivo, 
                linha=o.linha, 
                registro="?",
                detalhe=f"esperava um objeto, veio {type(d).__name__}"
            )
            continue

        try:
            processo = normalizar_cnj(d.get("processo"))
        except ErroNormalizacao as exc:
            diario.registrar(
                categoria=Categoria.DUVIDA, 
                regra="PROCESSO_INVALIDO", 
                arquivo=arquivo, 
                linha=o.linha,
                registro=str(d.get("processo") or "(vazio)"), 
                detalhe=str(exc)
            )
            continue

        if processo.nota:
            diario.registrar(
                categoria=Categoria.CORRIGIDO, 
                regra="PROCESSO_SEM_MASCARA", 
                arquivo=arquivo, 
                linha=o.linha, 
                registro=processo.valor,
                detalhe=processo.nota
            )
        try:
            data = normalizar_data_apresentacao(d.get("apresentado_em"))
        except ErroNormalizacao as exc:
            diario.registrar(
                categoria=Categoria.DUVIDA, 
                regra="APRESENTACAO_INVALIDA", 
                arquivo=arquivo, 
                linha=o.linha, 
                registro=processo.valor, 
                detalhe=str(exc)
            )
            continue

        if data.nota:
            diario.registrar(
                categoria=Categoria.CORRIGIDO, 
                regra="APRESENTACAO_COM_FUSO", 
                arquivo=arquivo, 
                linha=o.linha, 
                registro=processo.valor, 
                detalhe=data.nota
            )

        anterior = indice.get(processo.valor)

        if anterior is None:
            indice[processo.valor] = Apresentacao(processo.valor, data.valor, o.linha)
        elif anterior.data == data.valor:
            diario.registrar(
                categoria=Categoria.DESCARTADO, 
                regra="APRESENTACAO_DUPLICADA", 
                arquivo=arquivo, 
                linha=o.linha, 
                registro=processo.valor,
                detalhe=f"repete a linha {anterior.linha}"
            )
        else:
            diario.registrar(
                categoria=Categoria.DUVIDA, 
                regra="APRESENTACAO_DUPLICADA_DIVERGENTE", 
                arquivo=arquivo, 
                linha=o.linha, 
                registro=processo.valor,
                detalhe=f"linha {anterior.linha} diz {anterior.data}, esta diz {data.valor}; "
                f"mantida a linha {anterior.linha}"
            )
            
    return indice
