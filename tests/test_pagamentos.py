import unittest

from datetime import date
from decimal import Decimal

from limpeza.leitura import ObjetoJson
from limpeza.regras import (
    Categoria,
    Diario,
    Pagamento,
    Precatorio,
    aplicar_totais,
    processar_pagamentos,
)


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


def precatorio(valor_face="45000.00"):
    return Precatorio(PROC, "União", Decimal(valor_face), None, None, "conciliado", True)


def pagamento(valor, tipo="pagamento", evento_id="ev-1", linha=2):
    return Pagamento(evento_id, PROC, tipo, Decimal(str(valor)), date(2025, 3, 10), None, linha)


def aplicar(prec, *pagamentos):
    diario = Diario()
    aplicar_totais({PROC: prec}, list(pagamentos), "pagamentos.json", diario)
    return diario


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


class TestSinal(unittest.TestCase):
    def test_estorno_subtrai(self):
        r, _ = rodar(evento("ev-6", 5000), evento("ev-7", 5000, tipo="estorno", data="2025-03-10"))
        self.assertEqual(total(r), Decimal("0.00"))

    def test_pagamento_negativo_vai_para_duvida(self):
        r, d = rodar(evento(valor=-200))
        self.assertEqual(r.aceitos, [])
        self.assertIn("valor negativo", d.da_categoria(Categoria.DUVIDA)[0].detalhe)

    def test_estorno_negativo_vai_para_duvida(self):
        r, _ = rodar(evento(valor=-200, tipo="estorno"))
        self.assertEqual(r.aceitos, [])

    def test_tipo_desconhecido_vai_para_duvida(self):
        r, _ = rodar(evento(tipo="ajuste"))
        self.assertEqual(r.aceitos, [])


class TestQuarentena(unittest.TestCase):
    """Nada é ignorado em silêncio: o que não entra fica registrado com motivo."""

    def test_todo_evento_lido_tem_destino(self):
        eventos = [evento("a"), evento("a"), evento("b", valor=None), evento("c", processo=""),
                   evento("d", processo="0099999-99.2020.8.26.0053"), {"sem": "id"}, "lixo"]
        r, d = rodar(*eventos)
        descartados = len(d.da_categoria(Categoria.DESCARTADO))
        self.assertEqual(len(r.aceitos) + len(r.em_duvida) + descartados, len(eventos))

    def test_processo_desconhecido_nao_entra(self):
        r, _ = rodar(evento(processo="0099999-99.2020.8.26.0053"))
        self.assertEqual(r.aceitos, [])
        self.assertIn("não existe", r.em_duvida[0].motivos[0])

    def test_processo_sem_mascara_e_associado(self):
        r, _ = rodar(evento(processo="00123451020198260053"))
        self.assertEqual(r.aceitos[0].numero_processo, PROC)

    def test_possivel_reenvio_com_id_novo_gera_aviso_sem_descartar(self):
        r, d = rodar(evento("ev-1"), evento("ev-99"))
        self.assertEqual(len(r.aceitos), 2)
        self.assertIn("POSSIVEL_DUPLICATA_COM_ID_NOVO", regras(d, Categoria.AVISO))


class TestAplicarTotais(unittest.TestCase):
    """Soma dos eventos no precatório e avisos de total negativo e acima do face."""

    def test_total_negativo_vira_aviso_e_pendencia(self):
        # Estorno sem pagamento correspondente: 0 - 5000 = -5000.
        prec = precatorio("45000.00")
        d = aplicar(prec, pagamento(5000, tipo="estorno"))
        self.assertEqual(prec.total_pago, Decimal("-5000.00"))
        self.assertIn("TOTAL_NEGATIVO", regras(d, Categoria.AVISO))
        self.assertTrue(any("negativo" in p for p in prec.pendencias))

    def test_pago_acima_do_face_vira_aviso(self):
        prec = precatorio("10000.00")
        d = aplicar(prec, pagamento(8000, evento_id="ev-1"), pagamento(5000, evento_id="ev-2"))
        self.assertEqual(prec.total_pago, Decimal("13000.00"))
        self.assertIn("PAGO_ACIMA_DO_FACE", regras(d, Categoria.AVISO))

    def test_total_dentro_da_faixa_nao_avisa(self):
        prec = precatorio("10000.00")
        d = aplicar(prec, pagamento(8000))
        self.assertEqual(prec.total_pago, Decimal("8000.00"))
        self.assertEqual(regras(d, Categoria.AVISO), [])
        self.assertEqual(prec.pendencias, [])

    def test_total_igual_ao_face_nao_avisa(self):
        # A comparação é estritamente maior: pagar exatamente o face não avisa.
        prec = precatorio("10000.00")
        d = aplicar(prec, pagamento(10000))
        self.assertEqual(prec.total_pago, Decimal("10000.00"))
        self.assertEqual(regras(d, Categoria.AVISO), [])


if __name__ == "__main__":
    unittest.main()
