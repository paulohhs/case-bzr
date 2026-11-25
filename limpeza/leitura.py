import hashlib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ArquivoLido:
    nome: str
    sha256: str
    codificacao: str
    texto: str
    notas: list[str] = field(default_factory=list)


def sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def ler_arquivo(caminho: Path, *, codificacao_documentada: str = "utf-8") -> ArquivoLido:
    dados = caminho.read_bytes()
    notas: list[str] = []
    try:
        texto = dados.decode("utf-8")
        codificacao = "utf-8"
    except UnicodeDecodeError:
        # Como esse decode não falha só é utilizado após erro
        # na tentativa de decodificar como UTF-8.
        texto = dados.decode("cp1252")
        codificacao = "cp1252"
        notas.append(
            f"codificação diferente do leiaute ({codificacao_documentada.upper()}); "
            "lido como padrão do Excel em português"
        )
    if texto.startswith("﻿"):
        texto = texto[1:]
        notas.append("arquivo com BOM (marca de ordem de bytes) no início, removida")
    if "�" in texto:
        notas.append(
            "o arquivo contém o caractere de substituição U+FFFD: acentos foram perdidos "
            "antes de chegar aqui e não podem ser recuperados"
        )
    if b"\r\n" in dados:
        notas.append("quebras de linha CRLF (Windows)")
        
    return ArquivoLido(caminho.name, hashlib.sha256(dados).hexdigest(), codificacao, texto, notas)
