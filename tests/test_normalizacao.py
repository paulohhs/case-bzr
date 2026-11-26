import unittest

from limpeza.leitura import ArquivoLido, ler_csv


class TestLeituraCsv(unittest.TestCase):
    def _arquivo(self, dados: bytes) -> ArquivoLido:
        from limpeza.leitura import ler_arquivo
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            caminho = Path(d) / "x.csv"
            caminho.write_bytes(dados)
            return ler_arquivo(caminho)

    def test_csv_salvo_pelo_excel_recupera_acentos_e_separador(self):
        bruto = "numero_processo;ente_devedor;valor_face\r\n1;Município de São Paulo;45.000,00\r\n".encode("cp1252")
        arquivo = self._arquivo(bruto)
        self.assertEqual(arquivo.codificacao, "cp1252")
        linhas = ler_csv(arquivo, ["numero_processo", "ente_devedor", "valor_face"])
        self.assertEqual(linhas[0].campos["ente_devedor"], "Município de São Paulo")
        self.assertEqual(linhas[0].campos["valor_face"], "45.000,00")
        self.assertTrue(any("separador" in n for n in arquivo.notas))

    def test_utf8_com_bom(self):
        arquivo = self._arquivo("﻿a,b\n1,2\n".encode("utf-8"))
        self.assertEqual(ler_csv(arquivo, ["a", "b"])[0].campos, {"a": "1", "b": "2"})

    def test_linha_com_campos_a_mais_nao_some(self):
        arquivo = self._arquivo(b"a,b\n1,2,3\n")
        self.assertIn("__erro__", ler_csv(arquivo, ["a", "b"])[0].campos)


if __name__ == "__main__":
    unittest.main()
