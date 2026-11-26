import unittest
from datetime import date
from decimal import Decimal

from limpeza.leitura import ObjetoJson
from limpeza.regras import (
    Categoria,
    Diario,
    ler_apresentacoes,
    LinhaPrecatorio,
    conciliar,
)


PROC = "0012345-10.2019.8.26.0053"


def apresentacoes(*itens):
    diario = Diario()
    objetos = [ObjetoJson(i, i + 1, d) for i, d in enumerate(itens)]
    return ler_apresentacoes(objetos, "apresentacoes.json", diario), diario


def linha(apresentado=None, prazo=None, linha_=2):
    return LinhaPrecatorio(PROC, "Município de São Paulo", Decimal("45000.00"), linha_, apresentado, prazo)


def juntar(tribunal, hub, apres):
    diario = Diario()
    r = conciliar(tribunal, hub, diario, arquivo_tribunal="tribunal.csv", arquivo_hub="hub.csv",
                  apresentacoes=apres)
    return r[PROC], diario


class TestLeituraApresentacoes(unittest.TestCase):
    def test_fuso_e_mascara_normalizados(self):
        r, d = apresentacoes({"processo": "00123451020198260053", "apresentado_em": "2025-04-03T01:00:00Z"})
        self.assertEqual(r[PROC].data, date(2025, 4, 2))
        self.assertEqual({o.regra for o in d.da_categoria(Categoria.CORRIGIDO)},
                         {"PROCESSO_SEM_MASCARA", "APRESENTACAO_COM_FUSO"})

    def test_data_invalida_vira_duvida(self):
        r, d = apresentacoes({"processo": PROC, "apresentado_em": "31/12/2023"})
        self.assertEqual(r, {})
        self.assertEqual(d.da_categoria(Categoria.DUVIDA)[0].regra, "APRESENTACAO_INVALIDA")

    def test_mesmo_processo_com_datas_diferentes_vira_duvida(self):
        r, d = apresentacoes({"processo": PROC, "apresentado_em": "2025-04-02"},
                             {"processo": PROC, "apresentado_em": "2025-04-03"})
        self.assertEqual(r[PROC].data, date(2025, 4, 2))
        self.assertEqual(d.da_categoria(Categoria.DUVIDA)[0].regra, "APRESENTACAO_DUPLICADA_DIVERGENTE")


class TestFonteDaData(unittest.TestCase):
    def test_processo_fora_do_hub_ganha_prazo(self):
        apres, _ = apresentacoes({"processo": PROC, "apresentado_em": "2023-12-31"})
        p, _ = juntar({PROC: linha()}, {}, apres)
        self.assertEqual(p.prazo_pagamento, date(2025, 12, 31))
        self.assertEqual(p.situacao, "somente_tribunal")

    def test_divergencia_com_o_hub_usa_apresentacoes_e_vira_duvida(self):
        apres, _ = apresentacoes({"processo": PROC, "apresentado_em": "2025-04-02"})
        p, d = juntar({PROC: linha()}, {PROC: linha(date(2025, 4, 3))}, apres)
        self.assertEqual(p.prazo_pagamento, date(2026, 12, 31))
        self.assertEqual(p.situacao, "divergente")
        self.assertIn("APRESENTACAO_DIVERGENTE", [o.regra for o in d.da_categoria(Categoria.DUVIDA)])

    def test_processo_sem_apresentacao_usa_o_hub_com_aviso(self):
        p, d = juntar({PROC: linha()}, {PROC: linha(date(2025, 4, 3))}, {})
        self.assertEqual(p.apresentado_em, date(2025, 4, 3))
        self.assertIn("APRESENTACAO_SO_NO_HUB", [o.regra for o in d.da_categoria(Categoria.AVISO)])

    def test_sem_arquivo_de_apresentacoes_usa_o_hub_sem_aviso(self):
        p, d = juntar({PROC: linha()}, {PROC: linha(date(2025, 4, 3))}, None)
        self.assertEqual(p.apresentado_em, date(2025, 4, 3))
        self.assertEqual(d.da_categoria(Categoria.AVISO), [])


if __name__ == "__main__":
    unittest.main()
