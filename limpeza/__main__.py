import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from .execucao import executar
from .normalizacao import FUSO_TRIBUNAL
from .leitura import ErroArquivo
from .regras import Categoria


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="limpeza", description="Limpeza dos arquivos de precatórios.")
    parser.add_argument("--entrada", type=Path, default=Path("dados"), help="pasta com os arquivos originais")
    parser.add_argument("--saida", type=Path, default=Path("saida"), help="pasta onde gravar a base limpa")
    parser.add_argument("--estrito", action="store_true",
                        help="sai com código 1 se houver registros em dúvida (para alertar a operação)")
    parser.add_argument("--data-referencia", type=date.fromisoformat, default=None, metavar="AAAA-MM-DD",
                        help="data usada para marcar prazos vencidos (padrão: hoje em Brasília)")
    args = parser.parse_args(argv)

    try:
        referencia = args.data_referencia or datetime.now(FUSO_TRIBUNAL).date()
        resultado = executar(args.entrada, args.saida, referencia)
    except (ErroArquivo, ValueError, FileNotFoundError) as exc:
        print(f"ERRO: {exc}. Nada foi gravado.", file=sys.stderr)
        return 2

    for categoria in Categoria:
        print(f"{categoria.value:>10}: {len(resultado.diario.da_categoria(categoria))}")
    print(f"Base limpa e relatório em {args.saida}/")
    if args.estrito and resultado.tem_duvidas:
        print("ATENÇÃO: há registros em dúvida; veja relatorio_limpeza.md", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())