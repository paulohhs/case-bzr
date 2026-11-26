import json
from collections import Counter
from typing import TYPE_CHECKING
from .regras import Categoria, ZERO

if TYPE_CHECKING:
    from .execucao import Resultado


"""Relatório da limpeza em Markdown (para pessoas) e JSON (para máquinas).

Não leva data de geração de propósito: a mesma entrada produz exatamente o mesmo
relatório, o que permite comparar execuções. A rastreabilidade vem do SHA-256
dos arquivos de entrada.
"""


TITULOS = {
    Categoria.CORRIGIDO: ("Corrigido", "Aproveitado depois de corrigir formato ou aplicar uma regra."),
    Categoria.DESCARTADO: ("Descartado", "Redundante: não entra na base e não se perde informação."),
    Categoria.DUVIDA: ("Em dúvida", "Pode ser dado real, mas precisa de confirmação. Fica fora dos totais "
        "(eventos em `pagamentos_em_duvida.json`)."),
    Categoria.AVISO: ("Avisos", "Entrou na base, mas a operação deve saber."),
}


def _celula(texto: object) -> str:
    return str(texto).replace("|", "\\|").replace("\n", " ")


def _prazo(p) -> str:
    match p.situacao_prazo:
        case "vencido":
            return f"**vencido há {-p.dias_para_prazo} dias**"
        case "a_vencer":
            return f"**vence em {p.dias_para_prazo} dias**"
        case "em_dia":
            return "em dia"
        case "quitado":
            return "quitado"
        case _:
            return "sem prazo"


def gerar_markdown(r: "Resultado") -> str:
    linhas: list[str] = ["# Relatório da limpeza", ""]

    linhas += [
        "## Arquivos de entrada", 
        "",
        "| Arquivo | SHA-256 | Codificação lida | Observações |", "|---|---|---|---|"
    ]

    for a in r.arquivos:
        linhas.append(f"| {a.nome} | `{a.sha256[:16]}…` | {a.codificacao} | {_celula('; '.join(a.notas) or '—')} |")

    contagem = Counter(o.categoria for o in r.diario.itens)
    situacoes = Counter(p.situacao for p in r.precatorios.values())
    descartados_pgto = sum(1 for o in r.diario.da_categoria(Categoria.DESCARTADO) if o.arquivo == "pagamentos.json")
    total = sum((p.total_pago for p in r.precatorios.values()), ZERO)
    prazos = Counter(p.situacao_prazo for p in r.precatorios.values())
    em_duvida_valor = []

    for e in r.pagamentos.em_duvida:
        v = e.original.get("valor") if isinstance(e.original, dict) else None
        em_duvida_valor.append(repr(v))

    linhas += [
        "", "## Resumo", "",
        f"- Precatórios na base limpa: **{len(r.precatorios)}** "
        f"({', '.join(f'{k}: {v}' for k, v in sorted(situacoes.items()))})",
        f"- Eventos de pagamento: **{len(r.pagamentos.aceitos)} aceitos**, {descartados_pgto} descartados, "
        f"**{len(r.pagamentos.em_duvida)} em dúvida** (valores brutos: {', '.join(em_duvida_valor) or '—'})",
        f"- Total pago líquido na base limpa: **{total:.2f}**",
        f"- Prazos na data de referência **{r.referencia.isoformat()}**: "
        f"{', '.join(f'{k}: {v}' for k, v in sorted(prazos.items()))}",
        f"- Ocorrências: {', '.join(f'{TITULOS[c][0].lower()}: {contagem.get(c, 0)}' for c in Categoria)}",
        ""
    ]

    linhas += [
        "## Base limpa de precatórios", "",
        "| Processo | Ente devedor | Valor de face | Apresentado em | Prazo | Situação do prazo | Total pago "
        "| Saldo | Situação |",
        "|---|---|---:|---|---|---|---:|---:|---|"
    ]

    for p in r.precatorios.values():
        linhas.append(
            f"| {p.numero_processo} | {_celula(p.ente_devedor)} | {p.valor_face:.2f} | "
            f"{p.apresentado_em or '—'} | {p.prazo_pagamento or '—'} | {_prazo(p)} | "
            f"{p.total_pago:.2f} | {p.saldo:.2f} | "
            f"{p.situacao} |")

    for categoria in Categoria:
        titulo, explicacao = TITULOS[categoria]
        itens = r.diario.da_categoria(categoria)
        linhas += ["", f"## {titulo} ({len(itens)})", "", explicacao, ""]

        if not itens:
            linhas.append("Nada.")
            continue

        linhas += ["| Onde | Registro | Regra | Detalhe |", "|---|---|---|---|"]
        for o in itens:
            onde = f"{o.arquivo}:{o.linha}" if o.linha else o.arquivo
            linhas.append(f"| {onde} | {_celula(o.registro)} | `{o.regra}` | {_celula(o.detalhe)} |")

    return "\n".join(linhas) + "\n"


def gerar_json(r: "Resultado") -> str:
    dados = {
        "data_referencia": r.referencia.isoformat(),
        "arquivos": [
            {
                "nome": a.nome, 
                "sha256": a.sha256, 
                "codificacao": a.codificacao, 
                "notas": a.notas
            } for a in r.arquivos
        ],
        "precatorios": [
            {
                "numero_processo": p.numero_processo, 
                "ente_devedor": p.ente_devedor, 
                "valor_face": f"{p.valor_face:.2f}",
                "apresentado_em": p.apresentado_em.isoformat() if p.apresentado_em else None,
                "prazo_pagamento": p.prazo_pagamento.isoformat() if p.prazo_pagamento else None,
                "total_pago": f"{p.total_pago:.2f}", 
                "saldo": f"{p.saldo:.2f}", 
                "situacao": p.situacao,
                "situacao_prazo": p.situacao_prazo, 
                "dias_para_prazo": p.dias_para_prazo,
                "dv_cnj_valido": p.dv_cnj_valido, 
                "pendencias": p.pendencias
            } for p in r.precatorios.values()
        ],
        "ocorrencias": [
            {
                "categoria": str(o.categoria), 
                "regra": o.regra, 
                "arquivo": o.arquivo, 
                "linha": o.linha,
                "registro": o.registro, 
                "detalhe": o.detalhe
            } for o in r.diario.itens
        ],
    }
    return json.dumps(dados, ensure_ascii=False, indent=2) + "\n"
