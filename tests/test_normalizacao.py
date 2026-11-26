import unittest
from datetime import date
from decimal import Decimal

from limpeza.leitura import ArquivoLido, ler_csv
from limpeza.normalizacao import (
    ErroNormalizacao,
    calcular_dv_cnj,
    calcular_prazo,
    dv_cnj_valido,
    normalizar_cnj,
    normalizar_data_apresentacao,
    normalizar_data_pagamento,
    normalizar_valor,
)


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


class TestPrazo(unittest.TestCase):
    """O prazo define a priorização da carteira: um dia de erro muda o ano."""

    def test_dois_de_abril_entra_no_ano_seguinte(self):
        self.assertEqual(calcular_prazo(date(2025, 4, 2)), date(2026, 12, 31))

    def test_tres_de_abril_vai_para_o_ano_subsequente_ao_seguinte(self):
        self.assertEqual(calcular_prazo(date(2025, 4, 3)), date(2027, 12, 31))

    def test_extremos_do_ano(self):
        self.assertEqual(calcular_prazo(date(2025, 1, 1)), date(2026, 12, 31))
        self.assertEqual(calcular_prazo(date(2025, 12, 31)), date(2027, 12, 31))

    def test_ano_bissexto(self):
        self.assertEqual(calcular_prazo(date(2024, 2, 29)), date(2025, 12, 31))

    def test_utc_depois_da_meia_noite_ainda_e_dois_de_abril_em_brasilia(self):
        # 01:00 UTC de 3/4 = 22:00 de 2/4 em Brasília -> prazo 2026, não 2027.
        apresentado = normalizar_data_apresentacao("2025-04-03T01:00:00Z").valor
        self.assertEqual(apresentado, date(2025, 4, 2))
        self.assertEqual(calcular_prazo(apresentado), date(2026, 12, 31))

    def test_fim_do_dia_em_brasilia_nao_vira_dia_seguinte(self):
        # Converter para UTC daria 3/4 e empurraria o prazo para 2027.
        apresentado = normalizar_data_apresentacao("2025-04-02T23:30:00-03:00").valor
        self.assertEqual(apresentado, date(2025, 4, 2))

    def test_data_pura_nao_gera_nota(self):
        self.assertIsNone(normalizar_data_apresentacao("2025-04-02").nota)

    def test_data_hora_sem_fuso_e_rejeitada(self):
        with self.assertRaises(ErroNormalizacao):
            normalizar_data_apresentacao("2025-04-02T23:30:00")

    def test_data_inexistente_e_rejeitada(self):
        with self.assertRaises(ErroNormalizacao):
            normalizar_data_apresentacao("2025-02-29")


class TestValor(unittest.TestCase):
    """Valor errado vira dinheiro errado no total pago."""

    def test_formato_brasileiro_em_texto(self):
        r = normalizar_valor("2.500,50")
        self.assertEqual(r.valor, Decimal("2500.50"))
        self.assertIsNotNone(r.nota)

    def test_formato_brasileiro_sem_milhar(self):
        self.assertEqual(normalizar_valor("2500,5").valor, Decimal("2500.50"))

    def test_numeros_json(self):
        self.assertEqual(normalizar_valor(15000.0).valor, Decimal("15000.00"))
        self.assertEqual(normalizar_valor(8000).valor, Decimal("8000.00"))
        self.assertIsNone(normalizar_valor(8000).nota)

    def test_float_nao_carrega_erro_binario(self):
        self.assertEqual(normalizar_valor(0.1).valor, Decimal("0.10"))
        self.assertEqual(normalizar_valor(2500.5).valor, Decimal("2500.50"))

    def test_texto_com_ponto_decimal(self):
        self.assertEqual(normalizar_valor("45000.00").valor, Decimal("45000.00"))

    def test_so_separador_de_milhar_e_ambiguo(self):
        for ambiguo in ("1.500", "12.345", "1.234.567"):
            with self.subTest(ambiguo), self.assertRaises(ErroNormalizacao):
                normalizar_valor(ambiguo)

    def test_nulo_booleano_nan_e_lixo_sao_rejeitados(self):
        for ruim in (None, True, float("nan"), float("inf"), "abc", "", [1], "1,2,3"):
            with self.subTest(ruim), self.assertRaises(ErroNormalizacao):
                normalizar_valor(ruim)

    def test_mais_de_duas_casas_nao_e_arredondado_em_silencio(self):
        with self.assertRaises(ErroNormalizacao):
            normalizar_valor(1.005)
        with self.assertRaises(ErroNormalizacao):
            normalizar_valor("10,123")

    def test_negativo_e_aceito_aqui_e_julgado_pela_regra_de_negocio(self):
        self.assertEqual(normalizar_valor(-200).valor, Decimal("-200.00"))


class TestDataPagamento(unittest.TestCase):
    def test_iso(self):
        r = normalizar_data_pagamento("2025-03-10", referencia=None)
        self.assertEqual(r.valor, date(2025, 3, 10))
        self.assertIsNone(r.nota)

    def test_barras_resolvidas_pela_data_de_atualizacao(self):
        # 10/04 como MM/DD seria 4 de outubro, depois da atualização do registro: impossível.
        r = normalizar_data_pagamento("10/04/2025", referencia=date(2025, 4, 10))
        self.assertEqual(r.valor, date(2025, 4, 10))

    def test_barras_ambiguas_sem_desempate_viram_duvida(self):
        with self.assertRaises(ErroNormalizacao):
            normalizar_data_pagamento("03/04/2025", referencia=date(2025, 12, 31))
        with self.assertRaises(ErroNormalizacao):
            normalizar_data_pagamento("03/04/2025", referencia=None)

    def test_barras_com_dia_maior_que_doze_nao_sao_ambiguas(self):
        r = normalizar_data_pagamento("25/04/2025", referencia=None)
        self.assertEqual(r.valor, date(2025, 4, 25))

    def test_dia_igual_ao_mes(self):
        self.assertEqual(normalizar_data_pagamento("04/04/2025", referencia=None).valor, date(2025, 4, 4))


class TestCnj(unittest.TestCase):
    """Número errado quebra o cruzamento entre as bases."""

    def test_mascarado_passa_sem_nota(self):
        r = normalizar_cnj("0012345-10.2019.8.26.0053")
        self.assertEqual(r.valor, "0012345-10.2019.8.26.0053")
        self.assertIsNone(r.nota)

    def test_sem_mascara_e_mascarado_sao_o_mesmo_processo(self):
        r = normalizar_cnj("00234562120208260053")
        self.assertEqual(r.valor, "0023456-21.2020.8.26.0053")
        self.assertIsNotNone(r.nota)

    def test_espacos_em_volta(self):
        self.assertEqual(normalizar_cnj(" 0012345-10.2019.8.26.0053 ").valor, "0012345-10.2019.8.26.0053")

    def test_zeros_a_esquerda_perdidos_nao_sao_completados(self):
        # O Excel tira o zero inicial; completar seria adivinhar.
        with self.assertRaises(ErroNormalizacao):
            normalizar_cnj("234562120208260053")

    def test_vazio_letras_e_notacao_cientifica(self):
        for ruim in (None, "", "   ", "0012345-10.2019.8.26.005X", "2,34562E+16"):
            with self.subTest(ruim), self.assertRaises(ErroNormalizacao):
                normalizar_cnj(ruim)

    def test_digito_verificador(self):
        base = "1234567-{dv}.2020.8.26.0100"
        dv = calcular_dv_cnj(base.format(dv="00"))
        self.assertTrue(dv_cnj_valido(base.format(dv=f"{dv:02d}")))
        self.assertFalse(dv_cnj_valido(base.format(dv=f"{(dv + 1) % 100:02d}")))
        self.assertFalse(dv_cnj_valido("0012345-10.2019.8.26.0053"))
        

if __name__ == "__main__":
    unittest.main()
