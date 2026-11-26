from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .leitura import ArquivoLido, ler_arquivo, ler_csv, ler_json_lista
from .regras import (
    Categoria,
    Diario,
    Precatorio,
    ResultadoPagamentos,
    aplicar_totais,
    classificar_prazos,
    conciliar,
    ler_apresentacoes,
    ler_hub,
    ler_tribunal,
    processar_pagamentos,
)


ARQ_PAGAMENTOS = "pagamentos.json"
ARQ_TRIBUNAL = "tribunal.csv"
ARQ_HUB = "hub.csv"
ARQ_APRESENTACOES = "apresentacoes.json"  # opcional


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


def limpar(entrada: Path, referencia: date) -> Resultado:
    """Executa as regras sobre os arquivos de `entrada`, sem gravar nada.

    `referencia` é a data usada para dizer se um prazo está vencido.
    """
    diario = Diario()
    tribunal_arq = ler_arquivo(entrada / ARQ_TRIBUNAL)
    hub_arq = ler_arquivo(entrada / ARQ_HUB)
    pagamentos_arq = ler_arquivo(entrada / ARQ_PAGAMENTOS)
    arquivos = [tribunal_arq, hub_arq, pagamentos_arq]

    apresentacoes = None
    if (entrada / ARQ_APRESENTACOES).exists():
        apresentacoes_arq = ler_arquivo(entrada / ARQ_APRESENTACOES)
        arquivos.append(apresentacoes_arq)
        apresentacoes = ler_apresentacoes(
            objetos=ler_json_lista(apresentacoes_arq), 
            arquivo=ARQ_APRESENTACOES, 
            diario=diario
        )
    else:
        diario.registrar(
            categoria=Categoria.AVISO, 
            regra="SEM_ARQUIVO_DE_APRESENTACOES", 
            arquivo=ARQ_APRESENTACOES, 
            linha=None, 
            registro="-",
            detalhe="arquivo não encontrado; datas de apresentação tiradas só do hub"
        )

    linhas_tribunal_csv = ler_csv(
        arquivo=tribunal_arq, 
        colunas=["numero_processo", "ente_devedor", "valor_face"]
    )
    tribunal = ler_tribunal(
        linhas=linhas_tribunal_csv, 
        arquivo=ARQ_TRIBUNAL, 
        diario=diario
    )

    linhas_hub_csv = ler_csv(
        arquivo=hub_arq, 
        colunas=["processo", "ente", "valor_face", "apresentado_em", "prazo_pagamento"]
    )
    hub = ler_hub(
        linhas=linhas_hub_csv, 
        arquivo=ARQ_HUB, 
        diario=diario
    )
    
    precatorios = conciliar(
        tribunal=tribunal, 
        hub=hub, 
        diario=diario, 
        arquivo_tribunal=ARQ_TRIBUNAL, 
        arquivo_hub=ARQ_HUB, 
        apresentacoes=apresentacoes, 
        arquivo_apresentacoes=ARQ_APRESENTACOES
    )
    
    for processo, a in (apresentacoes or {}).items():
        if processo not in precatorios:
            diario.registrar(
                categoria=Categoria.AVISO, 
                regra="APRESENTACAO_SEM_PRECATORIO", 
                arquivo=ARQ_APRESENTACOES, 
                linha=a.linha, 
                registro=processo,
                detalhe="data de apresentação de um processo que não está no tribunal nem no hub"
            )

    invalidos = [p for p in precatorios.values() if not p.dv_cnj_valido]
    if invalidos:
        diario.registrar(
            categoria=Categoria.AVISO, 
            regra="DV_CNJ_INVALIDO", 
            arquivo="todos", 
            linha=None, 
            registro=f"{len(invalidos)} processos",
            detalhe=f"{len(invalidos)} de {len(precatorios)} processos têm dígito verificador CNJ inválido "
            "(módulo 97). Não foram descartados: confirmar se os números são reais"
        )

    pagamentos = processar_pagamentos(
        objetos=ler_json_lista(pagamentos_arq), 
        processos_conhecidos=set(precatorios), 
        arquivo=ARQ_PAGAMENTOS, 
        diario=diario
    )

    aplicar_totais(
        precatorios=precatorios, 
        pagamentos=pagamentos.aceitos, 
        arquivo=ARQ_PAGAMENTOS, 
        diario=diario
    )

    classificar_prazos(
        precatorios=precatorios, 
        referencia=referencia, 
        diario=diario
    )

    return Resultado(arquivos, precatorios, pagamentos, diario, referencia)
