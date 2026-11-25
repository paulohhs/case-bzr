import tempfile
import unittest
from pathlib import Path

from limpeza.leitura import ArquivoLido, ler_arquivo


CENARIOS = {
    # UTF-8 limpo - nenhum aviso deve aparecer.
    "limpo_utf8.csv": "processo,ente\n0001,Sao Paulo\n".encode("utf-8"),

    # Excel em português - Windows-1252 + CRLF - 'ã'/'ã' viram bytes != UTF-8.
    "excel_cp1252.csv": "processo;ente\r\n0001;Município de São Paulo\r\n".encode("cp1252"),

    # UTF-8 com BOM no início (EF BB BF) - BOM deve ser removida.
    "com_bom.csv": b"\xef\xbb\xbf" + "processo,ente\n0001,São Paulo\n".encode("utf-8"),

    # Acento perdido antes de chegar na leitura (U+FFFD: �).
    "corrompido.csv": "processo,ente\n0001,S�o Paulo\n".encode("utf-8"),
}


def _escrever_cenarios(destino: Path) -> None:
    """Grava os bytes de cada cenário em `destino`."""
    for nome, dados in CENARIOS.items():
        (destino / nome).write_bytes(dados)


class TestLerArquivo(unittest.TestCase):
    def setUp(self):
        # Pasta temporária apagada no tearDown
        self._tmp = tempfile.TemporaryDirectory()
        self.entrada = Path(self._tmp.name)
        _escrever_cenarios(self.entrada)

    def tearDown(self):
        self._tmp.cleanup()

    def test_utf8_limpo_sem_notas(self):
        caminho = self.entrada / "limpo_utf8.csv"
        arquivo = ler_arquivo(caminho)
        self.assertEqual(arquivo.codificacao, "utf-8")
        self.assertEqual(arquivo.notas, [])
        self.assertIn("Sao Paulo", arquivo.texto)

    def test_cp1252_recupera_acento_e_anota(self):
        arquivo = ler_arquivo(self.entrada / "excel_cp1252.csv")
        self.assertEqual(arquivo.codificacao, "cp1252")
        self.assertIn("São Paulo", arquivo.texto)
        texto_notas = " | ".join(arquivo.notas)
        self.assertIn("padrão do Excel", texto_notas)
        self.assertIn("CRLF", texto_notas)

    def test_bom_removida(self):
        arquivo = ler_arquivo(self.entrada / "com_bom.csv")
        self.assertFalse(arquivo.texto.startswith("﻿"))
        self.assertTrue(arquivo.texto.startswith("processo"))
        self.assertTrue(any("BOM" in n for n in arquivo.notas))

    def test_caractere_de_substituicao_vira_aviso(self):
        arquivo = ler_arquivo(self.entrada / "corrompido.csv")
        self.assertIn("�", arquivo.texto)
        self.assertTrue(any("U+FFFD" in n for n in arquivo.notas))

    def test_keyword_only_precisa_de_nome(self):
        with self.assertRaises(TypeError):
            ler_arquivo(self.entrada / "limpo_utf8.csv", "utf-8")


def _mostrar(arquivo: ArquivoLido) -> None:
    print(f"\n=== {arquivo.nome} ===")
    print(f"  codificacao : {arquivo.codificacao}")
    print(f"  sha256      : {arquivo.sha256[:16]}…")
    print(f"  texto       : {arquivo.texto!r}")
    if arquivo.notas:
        print("  notas       :")
        for n in arquivo.notas:
            print(f"     - {n}")
    else:
        print("  notas       : (nenhuma)")


if __name__ == "__main__":
    # Impressão de cada cenário para inspeção visual
    with tempfile.TemporaryDirectory() as tmp:
        entrada = Path(tmp)
        _escrever_cenarios(entrada)
        for nome in CENARIOS:
            arquivo = ler_arquivo(entrada / nome)   # <== BREAKPOINT (debug do script)
            _mostrar(arquivo)
