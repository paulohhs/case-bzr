import unittest
from datetime import date

from limpeza.leitura import ObjetoJson
from limpeza.regras import (
    Categoria,
    Diario,
    ler_apresentacoes,
)


PROC = "0012345-10.2019.8.26.0053"


def apresentacoes(*itens):
    diario = Diario()
    objetos = [ObjetoJson(i, i + 1, d) for i, d in enumerate(itens)]
    return ler_apresentacoes(objetos, "apresentacoes.json", diario), diario


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


if __name__ == "__main__":
    unittest.main()
