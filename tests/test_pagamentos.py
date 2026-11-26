import unittest

from decimal import Decimal

from limpeza.leitura import ObjetoJson
from limpeza.regras import Categoria, Diario, processar_pagamentos


PROC = "0012345-10.2019.8.26.0053"


def evento(evento_id="ev-1", valor=100, tipo="pagamento", processo=PROC, data="2025-03-10",
           atualizado="2025-03-10T10:00:00-03:00"):
    return {"evento_id": evento_id, "processo": processo, "valor": valor, "data_pagamento": data,
            "tipo": tipo, "atualizado_em": atualizado}


def regras(diario, categoria):
    return [o.regra for o in diario.da_categoria(categoria)]


def total(resultado):
    return sum((p.valor_assinado for p in resultado.aceitos), Decimal(0))


def rodar(*eventos, conhecidos=frozenset({PROC})):
    objetos = [ObjetoJson(i, i + 1, e) for i, e in enumerate(eventos)]
    diario = Diario()
    return processar_pagamentos(objetos, set(conhecidos), "pagamentos.json", diario), diario


class TestDuplicidade(unittest.TestCase):
    def test_reenvio_da_janela_de_sete_dias_conta_uma_vez(self):
        r, d = rodar(evento(), evento(), evento())
        self.assertEqual(total(r), Decimal("100.00"))
        self.assertEqual(regras(d, Categoria.DESCARTADO), ["DUPLICATA_EXATA"] * 2)

    def test_processar_duas_vezes_o_mesmo_arquivo_e_idempotente(self):
        lote = [evento("ev-1", 100), evento("ev-2", 50)]
        r1, _ = rodar(*lote)
        r2, _ = rodar(*lote, *lote)  # reimportação depois de falha
        self.assertEqual(total(r1), total(r2))

    def test_ordem_das_chaves_nao_engana_a_deteccao(self):
        a = evento()
        b = dict(reversed(list(a.items())))
        r, _ = rodar(a, b)
        self.assertEqual(len(r.aceitos), 1)


class TestVersoes(unittest.TestCase):
    def test_versao_mais_recente_vale(self):
        r, d = rodar(evento(valor=15000, atualizado="2025-03-10T10:00:00-03:00"),
                     evento(valor=15500, atualizado="2025-03-11T09:00:00-03:00"))
        self.assertEqual(total(r), Decimal("15500.00"))
        self.assertEqual(regras(d, Categoria.DESCARTADO), ["VERSAO_SUBSTITUIDA"])

    def test_vale_a_mais_recente_mesmo_vindo_antes_no_arquivo(self):
        r, _ = rodar(evento(valor=15500, atualizado="2025-03-11T09:00:00-03:00"),
                     evento(valor=15000, atualizado="2025-03-10T10:00:00-03:00"))
        self.assertEqual(total(r), Decimal("15500.00"))

    def test_compara_instantes_e_nao_texto(self):
        # 12:00Z = 09:00 em Brasília: a versão das 10:00-03:00 é a mais recente.
        r, _ = rodar(evento(valor=1, atualizado="2025-03-10T12:00:00Z"),
                     evento(valor=2, atualizado="2025-03-10T10:00:00-03:00"))
        self.assertEqual(total(r), Decimal("2.00"))

    def test_empate_de_atualizacao_com_conteudo_diferente_vira_duvida(self):
        r, d = rodar(evento(valor=1), evento(valor=2))
        self.assertEqual(r.aceitos, [])
        self.assertEqual(len(r.em_duvida), 2)
        self.assertIn("CONFLITO_DE_VERSAO", regras(d, Categoria.DUVIDA))

    def test_versao_nova_invalida_nao_ressuscita_a_antiga(self):
        r, _ = rodar(evento(valor=100, atualizado="2025-03-10T10:00:00-03:00"),
                     evento(valor=None, atualizado="2025-03-11T10:00:00-03:00"))
        self.assertEqual(r.aceitos, [])
        self.assertEqual(len(r.em_duvida), 1)


if __name__ == "__main__":
    unittest.main()
