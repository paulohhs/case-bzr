import io
import csv
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


class ErroArquivo(Exception):
    """O arquivo inteiro está ilegível: nada dele deve ser importado."""


@dataclass
class LinhaCsv:
    linha: int  # número da linha no arquivo, contando o cabeçalho como 1
    campos: dict[str, str]


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


def ler_csv(arquivo: ArquivoLido, colunas: list[str], *, separador_documentado: str = ",") -> list[LinhaCsv]:
    linhas_texto = arquivo.texto.splitlines()
    if not linhas_texto:
        raise ErroArquivo(f"{arquivo.nome}: arquivo vazio")
    cabecalho = linhas_texto[0]
    # O separador vem do cabeçalho, que não tem números: no corpo, a vírgula
    # decimal do Excel confundiria um detector automático.
    separador = ";" if cabecalho.count(";") > cabecalho.count(",") else ","
    if separador != separador_documentado:
        arquivo.notas.append(
            f"separador {separador!r} em vez de {separador_documentado!r} como diz o leiaute"
        )

    leitor = csv.reader(io.StringIO(arquivo.texto), delimiter=separador)
    nomes = [n.strip() for n in next(leitor)]
    faltando = [c for c in colunas if c not in nomes]
    if faltando:
        raise ErroArquivo(f"{arquivo.nome}: colunas ausentes no cabeçalho: {faltando} (veio {nomes})")

    resultado: list[LinhaCsv] = []
    for numero, valores in enumerate(leitor, start=2):
        if not any(v.strip() for v in valores):
            continue  # linha em branco
        if len(valores) != len(nomes):
            # Devolve mesmo assim, com marcador, para virar dúvida e não sumir.
            resultado.append(LinhaCsv(numero, {"__erro__": f"{len(valores)} campos, esperado {len(nomes)}"}))
            continue
        resultado.append(LinhaCsv(numero, dict(zip(nomes, (v.strip() for v in valores)))))
    return resultado
