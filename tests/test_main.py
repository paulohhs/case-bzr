"""Testes da CLI `main`: código de saída, mensagens e o efeito de --estrito."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from limpeza.__main__ import main

PROCESSO = "0012345-10.2019.8.26.0053"
REFERENCIA = "2026-11-24"  # fixa, para não depender de "hoje"

TRIBUNAL_CSV = (
    "numero_processo,ente_devedor,valor_face\n"
    f"{PROCESSO},Município de São Paulo,45000.00\n"
)
HUB_CSV = (
    "processo,ente,valor_face,apresentado_em,prazo_pagamento\n"
    f"{PROCESSO},MUNICIPIO DE SAO PAULO,45000.00,2025-03-10,2026-12-31\n"
)
PAGAMENTO_OK = {
    "evento_id": "ev-1", "processo": PROCESSO, "valor": 10000.00,
    "data_pagamento": "2025-03-10", "tipo": "pagamento",
    "atualizado_em": "2025-03-10T10:00:00-03:00",
}
# valor nulo -> vai para dúvida (quarentena)
PAGAMENTO_DUVIDOSO = {
    "evento_id": "ev-2", "processo": PROCESSO, "valor": None,
    "data_pagamento": "2025-03-10", "tipo": "pagamento",
    "atualizado_em": "2025-03-11T10:00:00-03:00",
}


class TestMain(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.entrada = base / "entrada"
        self.saida = base / "saida"
        self.entrada.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _escrever(self, *, com_duvida: bool) -> None:
        (self.entrada / "tribunal.csv").write_text(TRIBUNAL_CSV, encoding="utf-8")
        (self.entrada / "hub.csv").write_text(HUB_CSV, encoding="utf-8")
        eventos = [PAGAMENTO_OK] + ([PAGAMENTO_DUVIDOSO] if com_duvida else [])
        (self.entrada / "pagamentos.json").write_text(json.dumps(eventos), encoding="utf-8")

    def _rodar(self, *extra: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        argv = ["--entrada", str(self.entrada), "--saida", str(self.saida),
                "--data-referencia", REFERENCIA, *extra]
        with redirect_stdout(out), redirect_stderr(err):
            codigo = main(argv)
        return codigo, out.getvalue(), err.getvalue()

    def test_sucesso_sem_estrito_retorna_0_e_imprime_resumo(self):
        self._escrever(com_duvida=False)
        codigo, out, err = self._rodar()

        self.assertEqual(codigo, 0)
        self.assertIn(f"Base limpa e relatório em {self.saida}/", out)
        for categoria in ("corrigido", "descartado", "duvida", "aviso"):
            self.assertIn(categoria, out)  # uma linha de contagem por categoria
        self.assertEqual(err, "")
        # gravou mesmo os arquivos da base limpa
        self.assertTrue((self.saida / "relatorio_limpeza.md").exists())

    def test_estrito_com_duvidas_retorna_1_e_avisa_no_stderr(self):
        self._escrever(com_duvida=True)
        codigo, out, err = self._rodar("--estrito")

        self.assertEqual(codigo, 1)
        self.assertIn("ATENÇÃO", err)
        self.assertIn("relatorio_limpeza.md", err)
        # o resumo normal ainda sai no stdout
        self.assertIn("Base limpa e relatório em", out)

    def test_estrito_sem_duvidas_retorna_0(self):
        self._escrever(com_duvida=False)
        codigo, _out, err = self._rodar("--estrito")

        self.assertEqual(codigo, 0)
        self.assertNotIn("ATENÇÃO", err)

    def test_sem_estrito_com_duvidas_ainda_retorna_0(self):
        # Sem --estrito, dúvidas não derrubam o código de saída.
        self._escrever(com_duvida=True)
        codigo, _out, err = self._rodar()

        self.assertEqual(codigo, 0)
        self.assertNotIn("ATENÇÃO", err)

    def test_erro_quando_saida_e_igual_a_entrada_retorna_2(self):
        self._escrever(com_duvida=False)
        out, err = io.StringIO(), io.StringIO()
        argv = ["--entrada", str(self.entrada), "--saida", str(self.entrada),
                "--data-referencia", REFERENCIA]
        with redirect_stdout(out), redirect_stderr(err):
            codigo = main(argv)

        self.assertEqual(codigo, 2)
        self.assertIn("ERRO", err.getvalue())
        self.assertIn("Nada foi gravado", err.getvalue())

    def test_erro_quando_entrada_nao_existe_retorna_2(self):
        # entrada vazia: faltam os arquivos -> FileNotFoundError, tratado como erro.
        codigo, _out, err = self._rodar()

        self.assertEqual(codigo, 2)
        self.assertIn("ERRO", err)


if __name__ == "__main__":
    unittest.main()
