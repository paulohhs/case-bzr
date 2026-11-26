"""Testes de `gerar_json` e `gerar_markdown` do relatório da limpeza.

Monta um Resultado controlado em memória para conferir o conteúdo e o
determinismo da saída (a mesma entrada gera exatamente o mesmo relatório).
"""

import json
import unittest
from datetime import date
from decimal import Decimal

from limpeza.execucao import Resultado
from limpeza.leitura import ArquivoLido
from limpeza.regras import (
    Categoria,
    Diario,
    EventoEmDuvida,
    Pagamento,
    Precatorio,
    ResultadoPagamentos,
)
from limpeza.relatorio import gerar_json, gerar_markdown

PROCESSO = "0012345-10.2019.8.26.0053"
REFERENCIA = date(2026, 11, 24)


def _resultado() -> Resultado:
    arquivos = [ArquivoLido("pagamentos.json", "a" * 64, "utf-8", "", notas=["nota x"])]

    prec = Precatorio(
        numero_processo=PROCESSO,
        ente_devedor="Município de São Paulo",
        valor_face=Decimal("45000.00"),
        apresentado_em=date(2025, 3, 10),
        prazo_pagamento=date(2026, 12, 31),
        situacao="conciliado",
        dv_cnj_valido=False,
        pendencias=["uma pendência"],
        total_pago=Decimal("10000.00"),
        situacao_prazo="a_vencer",
        dias_para_prazo=37,
    )

    diario = Diario()
    diario.registrar(Categoria.CORRIGIDO, "ENTE_GRAFIA", "hub.csv", 2, PROCESSO, "grafia diferente")
    diario.registrar(Categoria.DUVIDA, "VALOR_FACE_DIVERGENTE", "hub.csv", 2, PROCESSO, "a|b")  # pipe p/ escape

    pagamentos = ResultadoPagamentos(
        aceitos=[Pagamento("ev-1", PROCESSO, "pagamento", Decimal("10000.00"), date(2025, 3, 10), None, 2)],
        em_duvida=[EventoEmDuvida(9, ["valor nulo"], {"valor": None})],
    )

    return Resultado(arquivos, {PROCESSO: prec}, pagamentos, diario, REFERENCIA)


class TestGerarJson(unittest.TestCase):
    def setUp(self):
        self.r = _resultado()
        self.dados = json.loads(gerar_json(self.r))

    def test_saida_e_json_valido_com_as_secoes(self):
        self.assertEqual(set(self.dados), {"data_referencia", "arquivos", "precatorios", "ocorrencias"})
        self.assertEqual(self.dados["data_referencia"], "2026-11-24")

    def test_arquivos_tem_sha256_completo_e_notas(self):
        arq = self.dados["arquivos"][0]
        self.assertEqual(arq["sha256"], "a" * 64)  # hash inteiro, não truncado
        self.assertEqual(arq["notas"], ["nota x"])

    def test_precatorio_com_decimais_como_texto_e_datas_iso(self):
        p = self.dados["precatorios"][0]
        self.assertEqual(p["valor_face"], "45000.00")
        self.assertEqual(p["total_pago"], "10000.00")
        self.assertEqual(p["saldo"], "35000.00")
        self.assertEqual(p["apresentado_em"], "2025-03-10")
        self.assertEqual(p["prazo_pagamento"], "2026-12-31")
        self.assertEqual(p["situacao_prazo"], "a_vencer")
        self.assertEqual(p["dias_para_prazo"], 37)
        self.assertFalse(p["dv_cnj_valido"])
        self.assertEqual(p["pendencias"], ["uma pendência"])

    def test_ocorrencias_preservam_categoria_regra_e_detalhe(self):
        ocs = self.dados["ocorrencias"]
        self.assertEqual([o["categoria"] for o in ocs], ["corrigido", "duvida"])
        self.assertEqual(ocs[1]["detalhe"], "a|b")  # no JSON o pipe fica cru

    def test_saida_e_deterministica_e_termina_com_newline(self):
        saida = gerar_json(self.r)
        self.assertTrue(saida.endswith("\n"))
        self.assertEqual(saida, gerar_json(_resultado()))


class TestGerarMarkdown(unittest.TestCase):
    def setUp(self):
        self.r = _resultado()
        self.saida = gerar_markdown(self.r)

    def test_tem_titulo_e_secoes_principais(self):
        self.assertTrue(self.saida.startswith("# Relatório da limpeza"))
        for secao in ("## Arquivos de entrada", "## Resumo", "## Base limpa de precatórios"):
            self.assertIn(secao, self.saida)

    def test_linha_do_precatorio_e_prazo_formatado(self):
        self.assertIn(PROCESSO, self.saida)
        self.assertIn("Município de São Paulo", self.saida)
        self.assertIn("45000.00", self.saida)
        self.assertIn("**vence em 37 dias**", self.saida)  # situacao_prazo = a_vencer

    def test_secoes_por_categoria_com_contagem_e_vazio(self):
        self.assertIn("## Corrigido (1)", self.saida)
        self.assertIn("## Em dúvida (1)", self.saida)
        self.assertIn("## Descartado (0)", self.saida)
        self.assertIn("Nada.", self.saida)  # categorias sem itens

    def test_pipe_no_detalhe_e_escapado(self):
        self.assertIn("a\\|b", self.saida)
        self.assertNotIn("| a|b |", self.saida)

    def test_saida_e_deterministica_e_termina_com_newline(self):
        self.assertTrue(self.saida.endswith("\n"))
        self.assertEqual(self.saida, gerar_markdown(_resultado()))


if __name__ == "__main__":
    unittest.main()
