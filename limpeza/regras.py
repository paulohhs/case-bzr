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
    chave_texto,
    calcular_prazo,
    dv_cnj_valido,
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
class Precatorio:
    numero_processo: str
    ente_devedor: str
    valor_face: Decimal
    apresentado_em: date | None
    prazo_pagamento: date | None
    situacao: str  # conciliado | divergente | somente_tribunal | somente_hub
    dv_cnj_valido: bool
    pendencias: list[str] = field(default_factory=list)
    total_pago: Decimal = ZERO
    situacao_prazo: str = "sem_prazo"  # vencido | a_vencer | em_dia | quitado | sem_prazo
    dias_para_prazo: int | None = None  # negativo = dias em atraso

    @property
    def saldo(self) -> Decimal:
        return self.valor_face - self.total_pago


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


def conciliar(
    tribunal: dict[str, LinhaPrecatorio], 
    hub: dict[str, LinhaPrecatorio],
    diario: Diario, *, 
    arquivo_tribunal: str, 
    arquivo_hub: str,
    apresentacoes: dict[str, Apresentacao] | None = None,
    arquivo_apresentacoes: str = "apresentacoes.json"
) -> dict[str, Precatorio]:
    """Junta as fontes pelo processo normalizado.

    Decisões:
    - ente e valor de face: o tribunal é a fonte oficial e prevalece; a divergência
      vira dúvida e o precatório sai com situação "divergente";
    - data de apresentação: vem de apresentacoes.json; o hub é usado só quando o
      processo não está lá. Se as duas fontes discordarem, vale apresentacoes.json
      e o caso vira dúvida;
    - prazo: sempre recalculado a partir da data, nunca copiado do hub.
    """
    resultado: dict[str, Precatorio] = {}
    for processo in sorted(tribunal.keys() | hub.keys()):
        t, h = tribunal.get(processo), hub.get(processo)
        pendencias: list[str] = []

        a = apresentacoes.get(processo) if apresentacoes is not None else None
        data_hub = h.apresentado_em if h else None
        if a and data_hub and a.data != data_hub:
            apresentado = a.data
            pendencias.append(f"data de apresentação divergente: {arquivo_apresentacoes} {a.data}, hub {data_hub}")
            diario.registrar(
                categoria=Categoria.DUVIDA, 
                regra="APRESENTACAO_DIVERGENTE", 
                arquivo=arquivo_apresentacoes, 
                linha=a.linha, 
                registro=processo,
                detalhe=f"{arquivo_apresentacoes} diz {a.data}, hub (linha {h.linha}) diz {data_hub}; "
                f"usada a de {arquivo_apresentacoes} até confirmação")
        elif a:
            apresentado = a.data
        else:
            apresentado = data_hub
            if apresentacoes is not None and data_hub:
                diario.registrar(
                    categoria=Categoria.AVISO, 
                    regra="APRESENTACAO_SO_NO_HUB", 
                    arquivo=arquivo_hub, 
                    linha=h.linha, 
                    registro=processo,
                    detalhe=f"processo ausente em {arquivo_apresentacoes}; usada a data do hub ({data_hub})"
                )

        if t and h:
            situacao = "conciliado"
            ente, valor = t.ente_devedor, t.valor_face
            if chave_texto(t.ente_devedor) == chave_texto(h.ente_devedor):
                if t.ente_devedor != h.ente_devedor:
                    diario.registrar(
                        categoria=Categoria.CORRIGIDO, 
                        regra="ENTE_GRAFIA", 
                        arquivo=arquivo_hub, 
                        linha=h.linha, 
                        registro=processo,
                        detalhe=f"{h.ente_devedor!r} é o mesmo ente que {t.ente_devedor!r} no tribunal "
                        "(só muda acento, caixa ou espaço); adotada a grafia do tribunal"
                    )
            else:
                pendencias.append(f"ente divergente: tribunal {t.ente_devedor!r}, hub {h.ente_devedor!r}")
                diario.registrar(
                    categoria=Categoria.DUVIDA, 
                    regra="ENTE_DIVERGENTE", 
                    arquivo=arquivo_hub, 
                    linha=h.linha, 
                    registro=processo, 
                    detalhe=f"tribunal (linha {t.linha}) diz {t.ente_devedor!r}, hub diz {h.ente_devedor!r}; "
                    "mantido o do tribunal até confirmação"
                )
            if t.valor_face != h.valor_face:
                pendencias.append(f"valor de face divergente: tribunal {t.valor_face}, hub {h.valor_face}")
                diario.registrar(
                    categoria=Categoria.DUVIDA, 
                    regra="VALOR_FACE_DIVERGENTE", 
                    arquivo=arquivo_hub, 
                    linha=h.linha, 
                    registro=processo,
                    detalhe=f"tribunal (linha {t.linha}) {t.valor_face}, hub {h.valor_face}; "
                    "mantido o do tribunal até confirmação"
                )
            if pendencias:
                situacao = "divergente"
        elif t:
            situacao, ente, valor = "somente_tribunal", t.ente_devedor, t.valor_face
            pendencias.append("ausente na exportação do hub" +
                              ("" if apresentado else ": sem data de apresentação, prazo não calculado"))
            diario.registrar(
                categoria=Categoria.DUVIDA, 
                regra="AUSENTE_NO_HUB", 
                arquivo=arquivo_tribunal, 
                linha=t.linha, 
                registro=processo,
                detalhe="precatório do tribunal que não existe no hub; pagamentos dele são rejeitados pela FK do banco"
            )
        else:
            assert h is not None
            situacao, ente, valor = "somente_hub", h.ente_devedor, h.valor_face
            pendencias.append("ausente na lista do tribunal")
            diario.registrar(
                categoria=Categoria.DUVIDA, 
                regra="AUSENTE_NO_TRIBUNAL", 
                arquivo=arquivo_hub, 
                linha=h.linha, 
                registro=processo,
                detalhe="precatório do hub que não está na lista do tribunal"
            )

        prazo =calcular_prazo(apresentado) if apresentado else None
        if h and prazo and h.prazo_informado != prazo:
            informado = h.prazo_informado.isoformat() if h.prazo_informado else "vazio"
            diario.registrar(
                categoria=Categoria.CORRIGIDO, 
                regra="PRAZO_RECALCULADO", 
                arquivo=arquivo_hub, 
                linha=h.linha, 
                registro=processo,
                detalhe=f"apresentado em {apresentado.isoformat()} (data de Brasília): prazo é "
                f"{prazo.isoformat()}, o hub dizia {informado}"
            )
        elif not h and prazo:
            diario.registrar(
                categoria=Categoria.CORRIGIDO, 
                regra="PRAZO_CALCULADO", 
                arquivo=arquivo_apresentacoes, 
                linha=a.linha, 
                registro=processo,
                detalhe=f"precatório fora do hub: apresentado em {apresentado.isoformat()}, "
                f"prazo {prazo.isoformat()}"
            )

        resultado[processo] = Precatorio(
            numero_processo=processo, 
            ente_devedor=ente, 
            valor_face=valor, 
            apresentado_em=apresentado, 
            prazo_pagamento=prazo, 
            situacao=situacao,
            dv_cnj_valido=dv_cnj_valido(processo), 
            pendencias=pendencias
        )

    return resultado
