class ErroArquivo(Exception):
    """O arquivo inteiro está ilegível: nada dele deve ser importado."""


class ErroNormalizacao(ValueError):
    """O valor não pode ser interpretado com segurança."""
