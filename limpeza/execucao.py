import csv
import json

from datetime import date
from pathlib import Path
from decimal import Decimal

from .leitura import ler_arquivo, ler_csv, ler_json_lista, sha256
from .relatorio import gerar_markdown, gerar_json
from .regras import (
    Categoria,
    Diario,
    aplicar_totais,
    classificar_prazos,
    conciliar,
    ler_apresentacoes,
    ler_hub,
    ler_tribunal,
    processar_pagamentos,
)
from .objetos_de_valor import Resultado


ARQ_PAGAMENTOS = "pagamentos.json"
ARQ_TRIBUNAL = "tribunal.csv"
ARQ_HUB = "hub.csv"
ARQ_APRESENTACOES = "apresentacoes.json"  # opcional


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


def _dinheiro(valor: Decimal) -> str:
    return f"{valor:.2f}"


def gravar(resultado: Resultado, saida: Path) -> list[Path]:
    saida.mkdir(parents=True, exist_ok=True)
    gerados: list[Path] = []

    caminho = saida / "precatorios_limpos.csv"
    with caminho.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(
            [
                "numero_processo", 
                "ente_devedor", 
                "valor_face", 
                "apresentado_em", 
                "prazo_pagamento",
                "situacao_prazo", 
                "dias_para_prazo", 
                "total_pago", 
                "saldo", 
                "situacao", 
                "dv_cnj_valido", 
                "pendencias"
            ]
        )
        for p in resultado.precatorios.values():
            w.writerow(
                [
                    p.numero_processo, 
                    p.ente_devedor, 
                    _dinheiro(p.valor_face),
                    p.apresentado_em.isoformat() if p.apresentado_em else "",
                    p.prazo_pagamento.isoformat() if p.prazo_pagamento else "",
                    p.situacao_prazo, 
                    "" if p.dias_para_prazo is None else p.dias_para_prazo,
                    _dinheiro(p.total_pago), 
                    _dinheiro(p.saldo), 
                    p.situacao,
                    "sim" if p.dv_cnj_valido else "nao", 
                    " | ".join(p.pendencias)
                ]
            )

    gerados.append(caminho)

    caminho = saida / "pagamentos_limpos.csv"
    with caminho.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow([
            "evento_id", 
            "numero_processo", 
            "tipo", 
            "valor", 
            "valor_com_sinal", 
            "data_pagamento",
            "atualizado_em", 
            "linha_origem"
        ])

        for p in resultado.pagamentos.aceitos:
            w.writerow([
                p.evento_id, 
                p.numero_processo, 
                p.tipo, 
                _dinheiro(p.valor), 
                _dinheiro(p.valor_assinado),
                p.data_pagamento.isoformat(), 
                p.atualizado_em.isoformat() if p.atualizado_em else "",
                p.linha
            ])
            
    gerados.append(caminho)

    caminho = saida / "pagamentos_em_duvida.json"
    quarentena = [
        {"linha_origem": e.linha, "motivos": e.motivos, "evento_original": e.original}
        for e in resultado.pagamentos.em_duvida
    ]

    caminho.write_text(json.dumps(quarentena, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gerados.append(caminho)

    caminho = saida / "relatorio_limpeza.md"
    caminho.write_text(gerar_markdown(resultado), encoding="utf-8")
    gerados.append(caminho)

    caminho = saida / "relatorio_limpeza.json"
    caminho.write_text(gerar_json(resultado), encoding="utf-8")
    gerados.append(caminho)
    return gerados


def executar(entrada: Path, saida: Path, referencia: date) -> Resultado:
    entrada, saida = entrada.resolve(), saida.resolve()
    if saida == entrada:
        raise ValueError("a saída não pode ser a pasta dos arquivos originais")
    
    originais = {
        n: sha256(entrada / n) 
        for n in (ARQ_TRIBUNAL, ARQ_HUB, ARQ_PAGAMENTOS, ARQ_APRESENTACOES)
        if (entrada / n).exists()
    }

    resultado = limpar(entrada, referencia)
    gravar(resultado, saida)

    # Garantia de que os originais não foram tocados.
    for nome, hash_antes in originais.items():
        if sha256(entrada / nome) != hash_antes:  # pragma: no cover - não deve acontecer
            raise RuntimeError(f"{nome} mudou durante a execução")
    return resultado
