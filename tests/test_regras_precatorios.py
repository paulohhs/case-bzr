"""Testes das funções de leitura/indexação de precatórios em regras.py:
_normalizar_linha_precatorio, _indexar, ler_tribunal e ler_hub.
"""

import unittest
from datetime import date
from decimal import Decimal

from limpeza.leitura import LinhaCsv
from limpeza.regras import (
    Categoria,
    Diario,
    LinhaPrecatorio,
    _indexar,
    _normalizar_linha_precatorio,
    ler_hub,
    ler_tribunal,
)

PROCESSO = "0012345-10.2019.8.26.0053"

# Nomes de coluna de cada fonte (iguais aos usados por ler_tribunal/ler_hub).
COLS_TRIBUNAL = dict(col_processo="numero_processo", col_ente="ente_devedor", col_valor="valor_face")


def _linha(numero: int, **campos: str) -> LinhaCsv:
    return LinhaCsv(numero, campos)


def _linha_tribunal(numero: int, processo=PROCESSO, ente="Município de São Paulo", valor="45000.00") -> LinhaCsv:
    return _linha(numero, numero_processo=processo, ente_devedor=ente, valor_face=valor)


class TestNormalizarLinhaPrecatorio(unittest.TestCase):
    def setUp(self):
        self.diario = Diario()

    def _normalizar(self, linha: LinhaCsv):
        return _normalizar_linha_precatorio(linha, "tribunal.csv", self.diario, **COLS_TRIBUNAL)

    def _regras_duvida(self) -> set[str]:
        return {o.regra for o in self.diario.da_categoria(Categoria.DUVIDA)}

    def test_linha_valida_vira_linha_precatorio(self):
        p = self._normalizar(_linha_tribunal(2))

        self.assertIsInstance(p, LinhaPrecatorio)
        self.assertEqual(p.numero_processo, PROCESSO)
        self.assertEqual(p.ente_devedor, "Município de São Paulo")
        self.assertEqual(p.valor_face, Decimal("45000.00"))
        self.assertEqual(p.linha, 2)
        self.assertEqual(self.diario.itens, [])  # nada a registrar

    def test_processo_sem_mascara_e_valor_br_entram_como_corrigido(self):
        # Linha válida, mas com duas correções de formato: continua virando LinhaPrecatorio.
        p = self._normalizar(_linha_tribunal(3, processo="00123451020198260053", valor="45.000,00"))

        self.assertIsInstance(p, LinhaPrecatorio)
        self.assertEqual(p.numero_processo, PROCESSO)
        self.assertEqual(p.valor_face, Decimal("45000.00"))
        regras = {o.regra for o in self.diario.da_categoria(Categoria.CORRIGIDO)}
        self.assertEqual(regras, {"PROCESSO_SEM_MASCARA", "VALOR_FORMATO_BR"})
        self.assertEqual(self.diario.da_categoria(Categoria.DUVIDA), [])

    def test_linha_malformada_vira_duvida(self):
        p = self._normalizar(_linha(9, __erro__="3 campos, esperado 4"))

        self.assertIsNone(p)
        self.assertIn("LINHA_MALFORMADA", self._regras_duvida())

    def test_processo_invalido_vira_duvida(self):
        p = self._normalizar(_linha_tribunal(4, processo="123"))

        self.assertIsNone(p)
        self.assertIn("PROCESSO_INVALIDO", self._regras_duvida())

    def test_ente_vazio_vira_duvida(self):
        p = self._normalizar(_linha_tribunal(5, ente=""))

        self.assertIsNone(p)
        self.assertIn("ENTE_AUSENTE", self._regras_duvida())

    def test_valor_ilegivel_vira_duvida(self):
        p = self._normalizar(_linha_tribunal(6, valor="abc"))

        self.assertIsNone(p)
        self.assertIn("VALOR_FACE_INVALIDO", self._regras_duvida())

    def test_valor_nao_positivo_vira_duvida(self):
        p = self._normalizar(_linha_tribunal(7, valor="0.00"))

        self.assertIsNone(p)
        self.assertIn("VALOR_FACE_NAO_POSITIVO", self._regras_duvida())


class TestIndexar(unittest.TestCase):
    def setUp(self):
        self.diario = Diario()

    def _prec(self, linha: int, valor="45000.00", ente="Município de São Paulo") -> LinhaPrecatorio:
        return LinhaPrecatorio(PROCESSO, ente, Decimal(valor), linha)

    def test_duplicata_identica_e_descartada_mantendo_a_primeira(self):
        primeira, segunda = self._prec(2), self._prec(5)

        indice = _indexar([primeira, segunda], "tribunal.csv", self.diario)

        self.assertEqual(set(indice), {PROCESSO})
        self.assertIs(indice[PROCESSO], primeira)  # fica a primeira ocorrência
        descartes = self.diario.da_categoria(Categoria.DESCARTADO)
        self.assertEqual(len(descartes), 1)
        self.assertEqual(descartes[0].regra, "PRECATORIO_DUPLICADO")
        self.assertEqual(self.diario.da_categoria(Categoria.DUVIDA), [])

    def test_duplicata_divergente_vira_duvida_mantendo_a_primeira(self):
        primeira, segunda = self._prec(2, valor="45000.00"), self._prec(5, valor="31000.00")

        indice = _indexar([primeira, segunda], "tribunal.csv", self.diario)

        self.assertIs(indice[PROCESSO], primeira)
        duvidas = self.diario.da_categoria(Categoria.DUVIDA)
        self.assertEqual(len(duvidas), 1)
        self.assertEqual(duvidas[0].regra, "PRECATORIO_DUPLICADO_DIVERGENTE")
        self.assertEqual(self.diario.da_categoria(Categoria.DESCARTADO), [])

    def test_processos_distintos_entram_todos(self):
        outro = LinhaPrecatorio("0023456-21.2020.8.26.0053", "União", Decimal("10000.00"), 3)
        indice = _indexar([self._prec(2), outro], "tribunal.csv", self.diario)

        self.assertEqual(set(indice), {PROCESSO, "0023456-21.2020.8.26.0053"})
        self.assertEqual(self.diario.itens, [])


class TestLerTribunal(unittest.TestCase):
    def setUp(self):
        self.diario = Diario()

    def test_linhas_validas_indexadas_por_processo(self):
        linhas = [
            _linha_tribunal(2),
            _linha_tribunal(3, processo="0023456-21.2020.8.26.0053", ente="União", valor="10000.00"),
        ]
        indice = ler_tribunal(linhas, "tribunal.csv", self.diario)

        self.assertEqual(set(indice), {PROCESSO, "0023456-21.2020.8.26.0053"})
        self.assertEqual(indice[PROCESSO].valor_face, Decimal("45000.00"))
        self.assertEqual(self.diario.itens, [])

    def test_linha_invalida_nao_entra_no_indice_e_vira_duvida(self):
        linhas = [_linha_tribunal(2), _linha_tribunal(3, processo="xxx")]
        indice = ler_tribunal(linhas, "tribunal.csv", self.diario)

        self.assertEqual(set(indice), {PROCESSO})
        self.assertIn("PROCESSO_INVALIDO", {o.regra for o in self.diario.da_categoria(Categoria.DUVIDA)})


class TestLerHub(unittest.TestCase):
    def setUp(self):
        self.diario = Diario()

    def _linha_hub(self, numero=2, processo=PROCESSO, ente="Município de São Paulo",
                   valor="45000.00", apresentado_em="2025-03-10", prazo="2026-12-31") -> LinhaCsv:
        return _linha(numero, processo=processo, ente=ente, valor_face=valor,
                      apresentado_em=apresentado_em, prazo_pagamento=prazo)

    def test_le_apresentacao_e_prazo_informado(self):
        indice = ler_hub([self._linha_hub()], "hub.csv", self.diario)

        p = indice[PROCESSO]
        self.assertEqual(p.apresentado_em, date(2025, 3, 10))
        self.assertEqual(p.prazo_informado, date(2026, 12, 31))

    def test_apresentacao_com_fuso_vira_corrigido_e_usa_data_de_brasilia(self):
        # 2025-04-03T01:00:00Z é 2 de abril às 22h em São Paulo.
        linha = self._linha_hub(apresentado_em="2025-04-03T01:00:00Z")
        indice = ler_hub([linha], "hub.csv", self.diario)

        self.assertEqual(indice[PROCESSO].apresentado_em, date(2025, 4, 2))
        self.assertIn("APRESENTACAO_COM_FUSO", {o.regra for o in self.diario.da_categoria(Categoria.CORRIGIDO)})

    def test_apresentacao_invalida_vira_aviso_sem_derrubar_a_linha(self):
        linha = self._linha_hub(apresentado_em="data-ruim")
        indice = ler_hub([linha], "hub.csv", self.diario)

        p = indice[PROCESSO]  # a linha continua no índice
        self.assertIsNone(p.apresentado_em)
        self.assertIn("APRESENTACAO_INVALIDA", {o.regra for o in self.diario.da_categoria(Categoria.AVISO)})


if __name__ == "__main__":
    unittest.main()
