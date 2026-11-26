import io
import csv
import hashlib
import json
from pathlib import Path
from .objetos_de_valor import (
    ArquivoLido, 
    LinhaCsv, 
    ObjetoJson,
)
from .exceptions import ErroArquivo


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


def _linhas_dos_objetos(texto: str) -> list[int]:
    """Linha de início de cada elemento da lista de topo, para citar evidência."""
    linhas: list[int] = []
    profundidade, linha = 0, 1
    em_string = escape = esperando_elemento = False

    for c in texto:
        if c == "\n":
            linha += 1

        if em_string:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                em_string = False
            continue

        if profundidade == 1 and esperando_elemento and c not in " \t\r\n,]":
            linhas.append(linha)
            esperando_elemento = False

        if c == '"':
            em_string = True
        elif c in "[{":
            profundidade += 1
            if profundidade == 1:
                esperando_elemento = True
        elif c in "]}":
            profundidade -= 1
        elif c == "," and profundidade == 1:
            esperando_elemento = True

    return linhas


def ler_json_lista(arquivo: ArquivoLido) -> list[ObjetoJson]:
    try:
        dados = json.loads(arquivo.texto)
    except json.JSONDecodeError as exc:
        # Arquivo truncado ou corrompido: não importa nada para não deixar metade aplicada.
        raise ErroArquivo(f"{arquivo.nome}: JSON inválido na linha {exc.lineno}, coluna {exc.colno}: {exc.msg}") from exc
    
    if not isinstance(dados, list):
        raise ErroArquivo(f"{arquivo.nome}: esperava uma lista de eventos, veio {type(dados).__name__}")
    
    linhas = _linhas_dos_objetos(arquivo.texto)
    if len(linhas) != len(dados):  # pragma: no cover - defensivo
        linhas = [0] * len(dados)
    
    return [ObjetoJson(i, linhas[i], obj) for i, obj in enumerate(dados)]
