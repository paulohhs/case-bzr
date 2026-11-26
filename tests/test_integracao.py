"""Roda a limpeza nos arquivos reais e confere o resultado esperado do diagnóstico."""

import shutil
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from limpeza.execucao import executar
from limpeza.leitura import sha256
from limpeza.regras import Categoria

DADOS = Path(__file__).resolve().parent.parent / "dados"
ORIGINAIS = ("tribunal.csv", "hub.csv", "pagamentos.json", "apresentacoes.json")
REFERENCIA = date(2026, 11, 26)


class TestArquivosReais(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.hashes = {n: sha256(DADOS / n) for n in ORIGINAIS}
        cls.r = executar(DADOS, cls.tmp / "saida", REFERENCIA)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def p(self, processo):
        return self.r.precatorios[processo]

    def test_totais_pagos(self):
        esperado = {
            "0012345-10.2019.8.26.0053": "18000.50",  # 15.500 (versão nova) + 2.500,50 (uma vez só)
            "0023456-21.2020.8.26.0053": "9200.00",   # 8.000 + 1.200 (processo sem máscara); null fora
            "0034567-32.2018.8.26.0405": "0.00",      # pagamento estornado
            "0045678-43.2021.5.02.0011": "3000.00",
            "0056789-54.2017.4.03.6100": "0.00",      # -200 em dúvida
            "0067890-65.2016.8.26.0053": "4000.00",   # existe no tribunal, falta no hub
        }
        for processo, valor in esperado.items():
            with self.subTest(processo):
                self.assertEqual(self.p(processo).total_pago, Decimal(valor))

    def test_prazos_corrigidos(self):
        self.assertEqual(self.p("0012345-10.2019.8.26.0053").prazo_pagamento, date(2026, 12, 31))
        self.assertEqual(self.p("0056789-54.2017.4.03.6100").prazo_pagamento, date(2026, 12, 31))
        self.assertEqual(self.p("0023456-21.2020.8.26.0053").prazo_pagamento, date(2027, 12, 31))

    def test_data_de_apresentacao_vem_do_arquivo_de_apresentacoes(self):
        # O 0067890 não está no hub: a data só existe em apresentacoes.json.
        p = self.p("0067890-65.2016.8.26.0053")
        self.assertEqual(p.apresentado_em, date(2023, 12, 31))
        self.assertEqual(p.prazo_pagamento, date(2025, 12, 31))

    def test_situacao_dos_prazos_na_data_de_referencia(self):
        esperado = {
            "0012345-10.2019.8.26.0053": ("a_vencer", date(2026, 12, 31)),
            "0023456-21.2020.8.26.0053": ("em_dia", date(2027, 12, 31)),
            "0034567-32.2018.8.26.0405": ("vencido", date(2025, 12, 31)),
            "0045678-43.2021.5.02.0011": ("a_vencer", date(2026, 12, 31)),
            "0056789-54.2017.4.03.6100": ("a_vencer", date(2026, 12, 31)),
            "0067890-65.2016.8.26.0053": ("vencido", date(2025, 12, 31)),
        }
        for processo, (situacao, prazo) in esperado.items():
            with self.subTest(processo):
                dias = (prazo - REFERENCIA).days
                self.assertEqual(
                    (self.p(processo).situacao_prazo, self.p(processo).dias_para_prazo),
                    (situacao, dias),
                )

    def test_conciliacao(self):
        situacoes = {k: v.situacao for k, v in self.r.precatorios.items()}
        self.assertEqual(situacoes["0012345-10.2019.8.26.0053"], "conciliado")  # só grafia diferente
        self.assertEqual(situacoes["0023456-21.2020.8.26.0053"], "divergente")  # valor de face
        self.assertEqual(situacoes["0045678-43.2021.5.02.0011"], "divergente")  # ente
        self.assertEqual(situacoes["0056789-54.2017.4.03.6100"], "somente_hub")
        self.assertEqual(situacoes["0067890-65.2016.8.26.0053"], "somente_tribunal")

    def test_acentos_do_csv_do_excel_recuperados(self):
        self.assertEqual(self.p("0034567-32.2018.8.26.0405").ente_devedor, "Estado de São Paulo")

    def test_eventos_em_duvida(self):
        duvidas = {o.registro for o in self.r.diario.da_categoria(Categoria.DUVIDA) if o.arquivo == "pagamentos.json"}
        self.assertEqual(duvidas, {"ev-004", "ev-009", "ev-010"})

    def test_originais_intactos(self):
        for nome, h in self.hashes.items():
            self.assertEqual(sha256(DADOS / nome), h)

    def test_saida_identica_em_nova_execucao(self):
        segunda = self.tmp / "saida2"
        executar(DADOS, segunda, REFERENCIA)
        for arquivo in (self.tmp / "saida").iterdir():
            with self.subTest(arquivo.name):
                self.assertEqual(arquivo.read_bytes(), (segunda / arquivo.name).read_bytes())

    def test_saida_na_pasta_de_entrada_e_recusada(self):
        with self.assertRaises(ValueError):
            executar(DADOS, DADOS, REFERENCIA)


if __name__ == "__main__":
    unittest.main()
