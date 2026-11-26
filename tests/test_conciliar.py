"""Testes da função `conciliar` de regras.py: conciliação tribunal x hub,
fonte da data de apresentação e recálculo de prazo.
"""

import unittest
from datetime import date
from decimal import Decimal

from limpeza.regras import (
    Apresentacao,
    Categoria,
    Diario,
    LinhaPrecatorio,
    conciliar,
)

PROCESSO = "0012345-10.2019.8.26.0053"
APRESENTADO = date(2025, 3, 10)      # (3,10) <= (2 de abril) -> prazo em 2026-12-31
PRAZO_CORRETO = date(2026, 12, 31)


def _lp(ente, valor, linha=2, apresentado=None, prazo=None) -> LinhaPrecatorio:
    return LinhaPrecatorio(PROCESSO, ente, Decimal(valor), linha, apresentado, prazo)


class _Base(unittest.TestCase):
    def setUp(self):
        self.diario = Diario()

    def _conciliar(self, tribunal, hub, apresentacoes=None):
        return conciliar(
            tribunal, hub, self.diario,
            arquivo_tribunal="tribunal.csv", arquivo_hub="hub.csv",
            apresentacoes=apresentacoes,
        )

    def _regras(self, categoria: Categoria) -> set[str]:
        return {o.regra for o in self.diario.da_categoria(categoria)}


class TestEnte(_Base):
    def test_ente_so_de_grafia_vira_corrigido_e_segue_conciliado(self):
        tribunal = {PROCESSO: _lp("Município de São Paulo", "45000.00", apresentado=APRESENTADO)}
        hub = {PROCESSO: _lp("MUNICIPIO DE SAO PAULO", "45000.00", apresentado=APRESENTADO)}

        r = self._conciliar(tribunal, hub)[PROCESSO]

        self.assertEqual(r.situacao, "conciliado")
        self.assertEqual(r.ente_devedor, "Município de São Paulo")  # adotada a grafia do tribunal
        self.assertEqual(r.pendencias, [])
        self.assertIn("ENTE_GRAFIA", self._regras(Categoria.CORRIGIDO))
        self.assertNotIn("ENTE_DIVERGENTE", self._regras(Categoria.DUVIDA))

    def test_ente_realmente_diferente_vira_duvida_e_divergente(self):
        tribunal = {PROCESSO: _lp("União", "45000.00", apresentado=APRESENTADO)}
        hub = {PROCESSO: _lp("Município de Santos", "45000.00", apresentado=APRESENTADO)}

        r = self._conciliar(tribunal, hub)[PROCESSO]

        self.assertEqual(r.situacao, "divergente")
        self.assertEqual(r.ente_devedor, "União")  # mantido o do tribunal
        self.assertTrue(any("ente divergente" in p for p in r.pendencias))
        self.assertIn("ENTE_DIVERGENTE", self._regras(Categoria.DUVIDA))


class TestValorFace(_Base):
    def test_valor_de_face_diferente_vira_duvida_e_divergente(self):
        tribunal = {PROCESSO: _lp("União", "30000.00", apresentado=APRESENTADO)}
        hub = {PROCESSO: _lp("União", "31000.00", apresentado=APRESENTADO)}

        r = self._conciliar(tribunal, hub)[PROCESSO]

        self.assertEqual(r.situacao, "divergente")
        self.assertEqual(r.valor_face, Decimal("30000.00"))  # mantido o do tribunal
        self.assertTrue(any("valor de face divergente" in p for p in r.pendencias))
        self.assertIn("VALOR_FACE_DIVERGENTE", self._regras(Categoria.DUVIDA))


class TestPresencaEmUmaFonte(_Base):
    def test_somente_tribunal(self):
        tribunal = {PROCESSO: _lp("União", "45000.00")}

        r = self._conciliar(tribunal, {})[PROCESSO]

        self.assertEqual(r.situacao, "somente_tribunal")
        self.assertIn("AUSENTE_NO_HUB", self._regras(Categoria.DUVIDA))

    def test_somente_hub(self):
        hub = {PROCESSO: _lp("União", "45000.00", apresentado=APRESENTADO)}

        r = self._conciliar({}, hub)[PROCESSO]

        self.assertEqual(r.situacao, "somente_hub")
        self.assertIn("AUSENTE_NO_TRIBUNAL", self._regras(Categoria.DUVIDA))


class TestFonteDaData(_Base):
    def test_sem_apresentacoes_usa_a_data_do_hub(self):
        hub = {PROCESSO: _lp("União", "45000.00", apresentado=APRESENTADO)}
        r = self._conciliar({PROCESSO: _lp("União", "45000.00")}, hub, apresentacoes=None)[PROCESSO]

        self.assertEqual(r.apresentado_em, APRESENTADO)
        self.assertNotIn("APRESENTACAO_SO_NO_HUB", self._regras(Categoria.AVISO))

    def test_apresentacoes_prevalece_sobre_o_hub_e_registra_divergencia(self):
        data_hub = date(2025, 4, 3)        # (4,3) daria prazo 2027
        data_apres = APRESENTADO           # vale esta -> prazo 2026
        tribunal = {PROCESSO: _lp("União", "45000.00")}
        hub = {PROCESSO: _lp("União", "45000.00", apresentado=data_hub)}
        apres = {PROCESSO: Apresentacao(PROCESSO, data_apres, linha=4)}

        r = self._conciliar(tribunal, hub, apresentacoes=apres)[PROCESSO]

        self.assertEqual(r.apresentado_em, data_apres)  # fonte: apresentacoes.json
        self.assertIn("APRESENTACAO_DIVERGENTE", self._regras(Categoria.DUVIDA))
        self.assertTrue(any("data de apresentação divergente" in p for p in r.pendencias))

    def test_processo_fora_das_apresentacoes_usa_hub_com_aviso(self):
        # apresentacoes existe (não é None) mas não tem este processo.
        tribunal = {PROCESSO: _lp("União", "45000.00")}
        hub = {PROCESSO: _lp("União", "45000.00", apresentado=APRESENTADO)}

        r = self._conciliar(tribunal, hub, apresentacoes={})[PROCESSO]

        self.assertEqual(r.apresentado_em, APRESENTADO)
        self.assertIn("APRESENTACAO_SO_NO_HUB", self._regras(Categoria.AVISO))


class TestPrazoRecalculado(_Base):
    def test_prazo_e_recalculado_ignorando_o_valor_do_hub(self):
        # O hub diz 2027, mas a data (10/03) manda o prazo ser 2026.
        tribunal = {PROCESSO: _lp("União", "45000.00", apresentado=APRESENTADO)}
        hub = {PROCESSO: _lp("União", "45000.00", apresentado=APRESENTADO, prazo=date(2027, 12, 31))}

        r = self._conciliar(tribunal, hub)[PROCESSO]

        self.assertEqual(r.prazo_pagamento, PRAZO_CORRETO)  # recalculado, não copiado
        self.assertIn("PRAZO_RECALCULADO", self._regras(Categoria.CORRIGIDO))

    def test_prazo_calculado_para_processo_fora_do_hub(self):
        tribunal = {PROCESSO: _lp("União", "45000.00")}
        apres = {PROCESSO: Apresentacao(PROCESSO, APRESENTADO, linha=4)}

        r = self._conciliar(tribunal, {}, apresentacoes=apres)[PROCESSO]

        self.assertEqual(r.situacao, "somente_tribunal")
        self.assertEqual(r.prazo_pagamento, PRAZO_CORRETO)
        self.assertIn("PRAZO_CALCULADO", self._regras(Categoria.CORRIGIDO))

    def test_sem_data_de_apresentacao_nao_ha_prazo(self):
        tribunal = {PROCESSO: _lp("União", "45000.00")}

        r = self._conciliar(tribunal, {})[PROCESSO]

        self.assertIsNone(r.apresentado_em)
        self.assertIsNone(r.prazo_pagamento)
        self.assertNotIn("PRAZO_RECALCULADO", self._regras(Categoria.CORRIGIDO))
        self.assertNotIn("PRAZO_CALCULADO", self._regras(Categoria.CORRIGIDO))


if __name__ == "__main__":
    unittest.main()
