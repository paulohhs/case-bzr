import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


"""Regras de normalização de campos (processo CNJ, valores, datas, prazo, texto).

Todas as funções recebem o valor bruto e devolvem um `Normalizado`, com o valor limpo e,
quando houve correção de formato, uma nota explicando o que foi feito. Quando o
valor não pode ser interpretado com segurança, a função levanta `ErroNormalizacao`
com o motivo: quem chama decide se o registro vai para "dúvida" ou "descartado".
"""


try:
    FUSO_TRIBUNAL = ZoneInfo("America/Sao_Paulo")
except ZoneInfoNotFoundError:  # sem base tz no sistema: Brasília está sem horário de verão desde 2019
    FUSO_TRIBUNAL = timezone(timedelta(hours=-3), "BRT")

# Constituição, art. 100, § 5º (redação da EC 114/2021): apresentado até 2 de abril,
# paga até 31/12 do ano seguinte; depois disso, até 31/12 do ano subsequente ao seguinte.
DATA_CORTE_APRESENTACAO = (4, 2)  # (mês, dia), inclusive


class ErroNormalizacao(ValueError):
    """O valor não pode ser interpretado com segurança."""


@dataclass(frozen=True)
class Normalizado[T]:
    valor: T
    nota: str | None = None  # descreve a correção aplicada, se houve


# ---------------------------------------------------------------- processo CNJ

_CNJ_MASCARADO = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")
_SO_DIGITOS_E_SEPARADORES = re.compile(r"[\d.\-\s/]+")


def normalizar_cnj(bruto: object) -> Normalizado[str]:
    """Devolve o número no formato NNNNNNN-DD.AAAA.J.TR.OOOO.

    Aceita o número já mascarado ou só com os 20 dígitos (com ou sem separadores).
    Não completa zeros à esquerda: um número com menos de 20 dígitos pode ter sido
    truncado pelo Excel, mas também pode ser outro erro, então vira dúvida.
    """
    if bruto is None or not str(bruto).strip():
        raise ErroNormalizacao("número do processo vazio")
    
    texto = str(bruto).strip()
    if _CNJ_MASCARADO.fullmatch(texto):
        return Normalizado(texto)
    
    if not _SO_DIGITOS_E_SEPARADORES.fullmatch(texto):
        raise ErroNormalizacao(f"número do processo com caracteres inválidos: {texto!r}")
    
    d = re.sub(r"\D", "", texto)
    if len(d) != 20:
        raise ErroNormalizacao(
            f"número do processo com {len(d)} dígitos (CNJ exige 20): {texto!r}"
        )
    
    mascarado = f"{d[:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:]}"

    return Normalizado(
        valor=mascarado, 
        nota=f"processo sem máscara CNJ {texto!r} normalizado para {mascarado}"
    )


def calcular_dv_cnj(numero_mascarado: str) -> int:
    """Dígito verificador do CNJ (Resolução CNJ 65/2008, módulo 97, ISO 7064)."""
    d = re.sub(r"\D", "", numero_mascarado)
    base = d[:7] + d[9:] + "00"  # NNNNNNN + AAAA + J + TR + OOOO + 00

    return 98 - int(base) % 97


def dv_cnj_valido(numero_mascarado: str) -> bool:
    d = re.sub(r"\D", "", numero_mascarado)

    return int(d[7:9]) == calcular_dv_cnj(numero_mascarado)


# ---------------------------------------------------------------- valores

_BR_COM_DECIMAL = re.compile(r"-?(\d{1,3}(\.\d{3})+|\d+),\d+")  # 2.500,50 | 2500,50
_BR_SO_MILHAR = re.compile(r"-?\d{1,3}(\.\d{3})+")  # 2.500 -> dois mil e quinhentos ou 2,5?
_PONTO_DECIMAL = re.compile(r"-?\d+(\.\d+)?")  # 2500.50 | 2500
CENTAVO = Decimal("0.01")


def normalizar_valor(bruto: object, *, formato_documentado: str = "ponto") -> Normalizado[Decimal]:
    """Converte para Decimal com 2 casas, sem passar por float binário.

    `formato_documentado` é o que o leiaute promete ("ponto"); qualquer outro formato
    aceito gera nota de correção. Rejeita: nulo, booleano, NaN/infinito, texto
    ambíguo ("1.500" pode ser 1500 ou 1,5) e mais de 2 casas decimais.
    """
    nota = None

    match bruto:
        case None:
            raise ErroNormalizacao("valor ausente (null)")
        case bool():
            raise ErroNormalizacao(f"valor booleano: {bruto!r}")
        case int():
            numero = Decimal(bruto)
        case float():
            # repr() devolve o menor texto que reproduz o float: 15000.0 -> "15000.0",
            # evitando Decimal(0.1) = 0.1000000000000000055...
            numero = Decimal(repr(bruto))
        case str():
            texto = bruto.strip().replace("R$", "").replace(" ", "")
            if _BR_COM_DECIMAL.fullmatch(texto):
                numero = Decimal(texto.replace(".", "").replace(",", "."))
                if formato_documentado == "ponto":
                    nota = f"valor em formato brasileiro {bruto!r} convertido para {numero:.2f}"
            elif _BR_SO_MILHAR.fullmatch(texto):
                raise ErroNormalizacao(
                    f"valor ambíguo {bruto!r}: pode ser separador de milhar ou decimal"
                )
            elif _PONTO_DECIMAL.fullmatch(texto):
                numero = Decimal(texto)
            else:
                raise ErroNormalizacao(f"valor ilegível: {bruto!r}")
        case _:
            raise ErroNormalizacao(f"valor de tipo inesperado ({type(bruto).__name__}): {bruto!r}")

    try:
        if not numero.is_finite():
            raise ErroNormalizacao(f"valor não finito: {bruto!r}")
    except InvalidOperation as exc:  # pragma: no cover - defensivo
        raise ErroNormalizacao(f"valor ilegível: {bruto!r}") from exc
    
    if numero != numero.quantize(CENTAVO):
        raise ErroNormalizacao(f"valor com mais de 2 casas decimais: {bruto!r}")
    
    return Normalizado(numero.quantize(CENTAVO), nota)


# ---------------------------------------------------------------- datas

_DATA_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
_DATA_BR = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


def ler_data_hora(bruto: object) -> datetime:
    """Data e hora ISO 8601 com fuso obrigatório (aceita 'Z')."""
    if not isinstance(bruto, str) or not bruto.strip():
        raise ErroNormalizacao(f"data e hora ausente: {bruto!r}")
    
    try:
        momento = datetime.fromisoformat(bruto.strip())
    except ValueError as exc:
        raise ErroNormalizacao(f"data e hora ilegível: {bruto!r}") from exc
    
    if momento.tzinfo is None:
        raise ErroNormalizacao(f"data e hora sem fuso horário: {bruto!r}")
    
    return momento


def data_local(momento: datetime) -> date:
    """Data civil no fuso do tribunal (Brasília)."""

    return momento.astimezone(FUSO_TRIBUNAL).date()


def normalizar_data_pagamento(bruto: object, *, referencia: date | None) -> Normalizado[date]:
    """Data AAAA-MM-DD; aceita DD/MM/AAAA fora do leiaute.

    Num texto com barras, DD/MM e MM/DD só se distinguem quando o dia passa de 12.
    Para desempatar usa `referencia` (a data local de `atualizado_em`): um pagamento
    não pode ser posterior à última alteração do próprio registro. Se as duas leituras
    continuarem possíveis, o valor é ambíguo e vira dúvida.
    """
    if not isinstance(bruto, str) or not bruto.strip():
        raise ErroNormalizacao(f"data de pagamento ausente: {bruto!r}")
    
    texto = bruto.strip()
    if _DATA_ISO.fullmatch(texto):
        try:
            return Normalizado(date.fromisoformat(texto))
        except ValueError as exc:
            raise ErroNormalizacao(f"data inexistente: {texto!r}") from exc

    if not (m := _DATA_BR.fullmatch(texto)):
        raise ErroNormalizacao(f"data ilegível: {texto!r}")
    
    a, b, ano = (int(x) for x in m.groups())
    candidatas: dict[str, date] = {}

    for rotulo, (dia, mes) in {"DD/MM": (a, b), "MM/DD": (b, a)}.items():
        try:
            candidatas[rotulo] = date(ano, mes, dia)
        except ValueError:
            pass

    if referencia is not None:
        candidatas = {k: v for k, v in candidatas.items() if v <= referencia}

    distintas = set(candidatas.values())
    if len(distintas) != 1:
        motivo = "nenhuma leitura possível" if not distintas else "DD/MM e MM/DD são ambas possíveis"
        raise ErroNormalizacao(f"data ambígua {texto!r}: {motivo}")
    
    escolhida = distintas.pop()

    return Normalizado(
        valor=escolhida, 
        nota=f"data fora do leiaute {texto!r} lida como {escolhida.isoformat()}"
    )


def normalizar_data_apresentacao(bruto: object) -> Normalizado[date]:
    """Data de apresentação: aceita AAAA-MM-DD ou data e hora com fuso.

    Com hora, a data que vale é a do calendário de Brasília, não a de UTC:
    2025-04-03T01:00:00Z é 2 de abril às 22h em São Paulo.
    """
    if not isinstance(bruto, str) or not bruto.strip():
        raise ErroNormalizacao(f"data de apresentação ausente: {bruto!r}")
    
    texto = bruto.strip()
    if _DATA_ISO.fullmatch(texto):
        try:
            return Normalizado(date.fromisoformat(texto))
        except ValueError as exc:
            raise ErroNormalizacao(f"data inexistente: {texto!r}") from exc
        
    momento = ler_data_hora(texto)
    local = data_local(momento)

    return Normalizado(
        valor=local, 
        nota=f"apresentado_em com hora e fuso {texto!r}; data no horário de Brasília: {local.isoformat()}"
    )


def calcular_prazo(apresentacao: date) -> date:
    anos = 1 if (apresentacao.month, apresentacao.day) <= DATA_CORTE_APRESENTACAO else 2

    return date(apresentacao.year + anos, 12, 31)


# ---------------------------------------------------------------- texto

def chave_texto(texto: str) -> str:
    """Chave de comparação: sem acento, sem diferença de caixa e de espaços."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) 
        if not unicodedata.combining(c)
    )

    return " ".join(sem_acento.casefold().split())
