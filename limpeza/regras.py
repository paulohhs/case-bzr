import json

from collections import defaultdict
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
    ler_data_hora,
    data_local,
    normalizar_data_pagamento,
)
from .objetos_de_valor import (
    Ocorrencia,
    LinhaPrecatorio,
    Apresentacao,
    Precatorio,
    Pagamento,
    EventoEmDuvida,
    ResultadoPagamentos,
)


ZERO = Decimal("0.00")
TIPOS_VALIDOS = {"pagamento", "estorno"}
JANELA_PRAZO_PROXIMO_DIAS = 60


class Categoria(StrEnum):
    CORRIGIDO = "corrigido"
    DESCARTADO = "descartado"
    DUVIDA = "duvida"
    AVISO = "aviso"


def _canonico(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def _id_evento(obj: object) -> str | None:
    if isinstance(obj, dict) and isinstance(obj.get("evento_id"), str) and obj["evento_id"].strip():
        return obj["evento_id"].strip()
    
    return None


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


def processar_pagamentos(
    objetos: list[ObjetoJson], 
    processos_conhecidos: set[str],
    arquivo: str, 
    diario: Diario
) -> ResultadoPagamentos:
    resultado = ResultadoPagamentos()

    def duvida(
        o: ObjetoJson, 
        regra: str, 
        registro: str, 
        motivos: list[str]
    ) -> None:
        diario.registrar(
            categoria=Categoria.DUVIDA, 
            regra=regra, 
            arquivo=arquivo, 
            linha=o.linha, 
            registro=registro, 
            detalhe="; ".join(motivos)
        )
        resultado.em_duvida.append(EventoEmDuvida(o.linha, motivos, o.dados))

    # 1. Sem identificador não há como deduplicar nem versionar.
    com_id: list[ObjetoJson] = []
    for o in objetos:
        if _id_evento(o.dados) is None:
            duvida(
                o=o, 
                regra="EVENTO_SEM_ID", 
                registro="?", 
                motivos=["evento sem evento_id: não dá para saber se é repetido"]
            )
        else:
            com_id.append(o)

    # 2. Duplicata exata: o arquivo traz 7 dias e é reenviado todo dia, e a
    #    reimportação depois de falha repete tudo. Fica só a primeira ocorrência.
    vistos: dict[str, ObjetoJson] = {}
    unicos: list[ObjetoJson] = []

    for o in com_id:
        chave = _canonico(o.dados)
        if chave in vistos:
            diario.registrar(
                categoria=Categoria.DESCARTADO, 
                regra="DUPLICATA_EXATA", 
                arquivo=arquivo, 
                linha=o.linha, 
                registro=_id_evento(o.dados),
                detalhe=f"idêntico ao registro da linha {vistos[chave].linha}"
            )
        else:
            vistos[chave] = o
            unicos.append(o)

    # 3. Mesmo evento_id com conteúdo diferente: é uma correção. Vale a versão com
    #    atualizado_em mais recente, seja qual for a ordem no arquivo.
    grupos: dict[str, list[ObjetoJson]] = defaultdict(list)
    for o in unicos:
        grupos[_id_evento(o.dados)].append(o)

    vencedores: list[ObjetoJson] = []
    for evento_id, versoes in grupos.items():
        if len(versoes) == 1:
            vencedores.append(versoes[0])
            continue

        try:
            datadas = [(ler_data_hora(v.dados.get("atualizado_em")), v) for v in versoes]
        except ErroNormalizacao as exc:
            for v in versoes:
                duvida(
                    o=v, 
                    regra="CONFLITO_DE_VERSAO", 
                    registro=evento_id,
                    motivos=[f"{len(versoes)} versões do evento e não dá para ordená-las ({exc})"]
                )
            continue

        mais_recente = max(m for m, _ in datadas)
        empatadas = [v for m, v in datadas if m == mais_recente]

        if len(empatadas) > 1:
            for v in versoes:
                duvida(
                    o=v, 
                    regra="CONFLITO_DE_VERSAO", 
                    registro=evento_id,
                    motivos=[f"{len(empatadas)} versões diferentes com o mesmo atualizado_em {mais_recente.isoformat()}"]
                )
            continue
        
        vencedor = empatadas[0]
        vencedores.append(vencedor)
        for m, v in datadas:
            if v is vencedor:
                continue
            diario.registrar(
                categoria=Categoria.DESCARTADO, 
                regra="VERSAO_SUBSTITUIDA", 
                arquivo=arquivo, 
                linha=v.linha, 
                registro=evento_id,
                detalhe=f"substituída pela versão da linha {vencedor.linha} "
                         f"(atualizado_em {m.isoformat()} → {mais_recente.isoformat()}; "
                         f"valor {v.dados.get('valor')!r} → {vencedor.dados.get('valor')!r})"
            )

    # 4. Validação campo a campo da versão que vale.
    for o in sorted(vencedores, key=lambda x: x.indice):
        d: dict = o.dados
        evento_id = _id_evento(d)
        motivos: list[str] = []
        correcoes: list[tuple[str, str]] = []

        processo = None
        try:
            n = normalizar_cnj(d.get("processo"))
            processo = n.valor
            if n.nota:
                correcoes.append(("PROCESSO_SEM_MASCARA", n.nota))
        except ErroNormalizacao as exc:
            motivos.append(str(exc))

        valor = None
        try:
            v = normalizar_valor(d.get("valor"))
            valor = v.valor
            if v.nota:
                correcoes.append(("VALOR_FORMATO_BR", v.nota))
        except ErroNormalizacao as exc:
            motivos.append(str(exc))

        tipo = str(d.get("tipo") or "").strip().casefold()
        if tipo not in TIPOS_VALIDOS:
            motivos.append(f"tipo desconhecido: {d.get('tipo')!r}")

        atualizado = None
        try:
            atualizado = ler_data_hora(d.get("atualizado_em"))
        except ErroNormalizacao as exc:
            diario.registrar(
                categoria=Categoria.AVISO, 
                regra="ATUALIZADO_EM_INVALIDO", 
                arquivo=arquivo, 
                linha=o.linha, 
                registro=evento_id, 
                detalhe=str(exc)
            )

        data_pgto = None
        try:
            dp = normalizar_data_pagamento(
                bruto=d.get("data_pagamento"),
                referencia=data_local(atualizado) if atualizado else None
            )
            data_pgto = dp.valor

            if dp.nota:
                correcoes.append(("DATA_FORMATO_BR", dp.nota))
        except ErroNormalizacao as exc:
            motivos.append(str(exc))

        if valor is not None and tipo in TIPOS_VALIDOS:
            if valor == ZERO:
                motivos.append("valor zero")
            elif valor < ZERO and tipo == "pagamento":
                motivos.append(f"pagamento com valor negativo ({valor}): pode ser um estorno com o tipo errado")
            elif valor < ZERO and tipo == "estorno":
                motivos.append(f"estorno com valor negativo ({valor}): a convenção de sinal não está documentada")

        if processo and processo not in processos_conhecidos:
            motivos.append(f"processo {processo} não existe nem no tribunal nem no hub")

        if motivos:
            regra = "PROCESSO_AUSENTE" if not d.get("processo") else "EVENTO_INVALIDO"
            duvida(o, regra, evento_id, motivos)
            continue

        for regra, nota in correcoes:
            diario.registrar(
                categoria=Categoria.CORRIGIDO, 
                regra=regra, 
                arquivo=arquivo, 
                linha=o.linha, 
                registro=evento_id, 
                detalhe=nota
            )

        if tipo == "estorno":
            diario.registrar(
                categoria=Categoria.CORRIGIDO, 
                regra="ESTORNO_SUBTRAIDO", 
                arquivo=arquivo, 
                linha=o.linha, 
                registro=evento_id, 
                detalhe=f"tipo 'estorno' (não previsto no leiaute v2.1) subtrai {valor} do total pago"
            )

        if atualizado and data_pgto > data_local(atualizado):
            diario.registrar(
                categoria=Categoria.AVISO, 
                regra="PAGAMENTO_APOS_ATUALIZACAO", 
                arquivo=arquivo, 
                linha=o.linha, 
                registro=evento_id, 
                detalhe=f"data de pagamento {data_pgto} posterior a atualizado_em {atualizado.isoformat()}"
            )
            
        resultado.aceitos.append(Pagamento(evento_id, processo, tipo, valor, data_pgto, atualizado, o.linha))

    # 5. Mesmo processo, tipo, valor e data com ids diferentes pode ser reenvio com id novo.
    por_conteudo: dict[tuple, list[Pagamento]] = defaultdict(list)
    for p in resultado.aceitos:
        por_conteudo[(p.numero_processo, p.tipo, p.valor, p.data_pagamento)].append(p)

    for grupo in por_conteudo.values():
        if len(grupo) > 1:
            ids = ", ".join(f"{p.evento_id} (linha {p.linha})" for p in grupo)

            for p in grupo[1:]:
                diario.registrar(
                    categoria=Categoria.AVISO, 
                    regra="POSSIVEL_DUPLICATA_COM_ID_NOVO", 
                    arquivo=arquivo, 
                    linha=p.linha, 
                    registro=p.evento_id, 
                    detalhe=f"mesmo processo, tipo, valor e data que {ids}; mantidos, confirmar com o tribunal"
                )
                
    return resultado


def aplicar_totais(
    precatorios: dict[str, Precatorio], 
    pagamentos: list[Pagamento],
    arquivo: str, diario: Diario
) -> None:
    for p in pagamentos:
        precatorios[p.numero_processo].total_pago += p.valor_assinado

    for prec in precatorios.values():
        if prec.total_pago < ZERO:
            prec.pendencias.append(f"total pago negativo ({prec.total_pago}): estorno sem pagamento correspondente")
            
            diario.registrar(
                categoria=Categoria.AVISO, 
                regra="TOTAL_NEGATIVO", 
                arquivo=arquivo, 
                linha=None, 
                registro=prec.numero_processo, 
                detalhe=f"total pago {prec.total_pago}"
            )
        elif prec.total_pago > prec.valor_face:
            diario.registrar(
                categoria=Categoria.AVISO, 
                regra="PAGO_ACIMA_DO_FACE", 
                arquivo=arquivo, 
                linha=None, 
                registro=prec.numero_processo, 
                detalhe=f"total pago {prec.total_pago} maior que o valor de face {prec.valor_face} "
                         "(pode ser correção monetária, conferir)"
            )


def classificar_prazos(
    precatorios: dict[str, Precatorio], 
    referencia: date, 
    diario: Diario
) -> None:
    """Marca cada precatório como vencido, a vencer (até 60 dias), em dia, quitado ou sem prazo.

    Roda depois dos totais, porque só importa o prazo de quem ainda tem saldo. O
    último dia conta como dentro do prazo: vencido é só quando a referência passou dele.
    """
    for p in precatorios.values():
        if p.prazo_pagamento is None:
            p.situacao_prazo = "sem_prazo"
            continue
        
        p.dias_para_prazo = (p.prazo_pagamento - referencia).days
        if p.saldo <= ZERO:
            p.situacao_prazo = "quitado"
        elif p.dias_para_prazo < 0:
            p.situacao_prazo = "vencido"
            atraso = -p.dias_para_prazo
            p.pendencias.append(f"prazo vencido em {p.prazo_pagamento} ({atraso} dias), saldo {p.saldo:.2f}")
            
            diario.registrar(
                categoria=Categoria.AVISO, 
                regra="PRAZO_VENCIDO", 
                arquivo="base limpa", 
                linha=None, 
                registro=p.numero_processo,
                detalhe=f"prazo {p.prazo_pagamento} vencido há {atraso} dias em {referencia}; "
                         f"saldo {p.saldo:.2f}"
            )
        elif p.dias_para_prazo <= JANELA_PRAZO_PROXIMO_DIAS:
            p.situacao_prazo = "a_vencer"
            diario.registrar(
                categoria=Categoria.AVISO, 
                regra="PRAZO_PROXIMO", 
                arquivo="base limpa", 
                linha=None, 
                registro=p.numero_processo,
                detalhe=f"prazo {p.prazo_pagamento} vence em {p.dias_para_prazo} dias; saldo {p.saldo:.2f}"
            )
        else:
            p.situacao_prazo = "em_dia"
