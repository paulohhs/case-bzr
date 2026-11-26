"""Testes da função `limpar`: orquestra o pipeline sobre os arquivos de entrada,
devolve um Resultado e não grava nada. Usa um fixture mínimo e controlado.
"""

import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from limpeza.execucao import Resultado, limpar
from limpeza.regras import Categoria

PROCESSO = "0012345-10.2019.8.26.0053"
REFERENCIA = date(2026, 11, 24)

# Tribunal e hub concordam no valor; o ente só muda a grafia (acento/caixa).
TRIBUNAL_CSV = (
    "numero_processo,ente_devedor,valor_face\n"
    f"{PROCESSO},Município de São Paulo,45000.00\n"
)
HUB_CSV = (
    "processo,ente,valor_face,apresentado_em,prazo_pagamento\n"
    f"{PROCESSO},MUNICIPIO DE SAO PAULO,45000.00,2025-03-10,2027-12-31\n"
)
PAGAMENTOS = [
    {"evento_id": "ev-1", "processo": PROCESSO, "valor": 10000.00,
     "data_pagamento": "2025-03-10", "tipo": "pagamento",
     "atualizado_em": "2025-03-10T10:00:00-03:00"},
]


class TestLimpar(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.entrada = Path(self._tmp.name)
        (self.entrada / "tribunal.csv").write_text(TRIBUNAL_CSV, encoding="utf-8")
        (self.entrada / "hub.csv").write_text(HUB_CSV, encoding="utf-8")
        (self.entrada / "pagamentos.json").write_text(json.dumps(PAGAMENTOS), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _escrever_apresentacoes(self, registros: list[dict]) -> None:
        (self.entrada / "apresentacoes.json").write_text(json.dumps(registros), encoding="utf-8")

    def _regras(self, diario, categoria) -> set[str]:
        return {o.regra for o in diario.da_categoria(categoria)}

    def test_concilia_recalcula_prazo_e_soma_pagamentos(self):
        r = limpar(self.entrada, REFERENCIA)

        self.assertIsInstance(r, Resultado)
        self.assertEqual(set(r.precatorios), {PROCESSO})

        p = r.precatorios[PROCESSO]
        self.assertEqual(p.situacao, "conciliado")                  # ente só muda grafia
        self.assertEqual(p.ente_devedor, "Município de São Paulo")  # adotada a grafia do tribunal
        self.assertEqual(p.total_pago, Decimal("10000.00"))
        self.assertEqual(p.prazo_pagamento, date(2026, 12, 31))     # recalculado (o hub dizia 2027)
        self.assertEqual(p.situacao_prazo, "a_vencer")
        self.assertEqual(p.dias_para_prazo, 37)

    def test_guarda_referencia_e_arquivos_lidos(self):
        r = limpar(self.entrada, REFERENCIA)

        self.assertEqual(r.referencia, REFERENCIA)
        # Sem apresentacoes.json: só os três arquivos de entrada, nessa ordem.
        self.assertEqual([a.nome for a in r.arquivos],
                         ["tribunal.csv", "hub.csv", "pagamentos.json"])

    def test_sem_apresentacoes_gera_aviso_e_nao_tem_duvidas(self):
        r = limpar(self.entrada, REFERENCIA)

        self.assertIn("SEM_ARQUIVO_DE_APRESENTACOES", self._regras(r.diario, Categoria.AVISO))
        self.assertFalse(r.tem_duvidas)  # fixture limpo: nada em dúvida

    def test_nao_grava_nada_na_entrada(self):
        antes = sorted(x.name for x in self.entrada.iterdir())
        limpar(self.entrada, REFERENCIA)
        depois = sorted(x.name for x in self.entrada.iterdir())

        self.assertEqual(antes, depois)

    def test_apresentacoes_e_a_fonte_da_data_sobre_o_hub(self):
        # 03/04 (prazo 2027) sobrepõe a data do hub 10/03 (prazo 2026).
        self._escrever_apresentacoes([{"processo": PROCESSO, "apresentado_em": "2025-04-03"}])

        r = limpar(self.entrada, REFERENCIA)
        p = r.precatorios[PROCESSO]

        self.assertEqual(p.apresentado_em, date(2025, 4, 3))
        self.assertEqual(p.prazo_pagamento, date(2027, 12, 31))
        self.assertEqual(len(r.arquivos), 4)
        self.assertNotIn("SEM_ARQUIVO_DE_APRESENTACOES", self._regras(r.diario, Categoria.AVISO))

    def test_apresentacao_de_processo_inexistente_gera_aviso(self):
        outro = "0099999-99.2020.8.26.0053"
        self._escrever_apresentacoes([{"processo": outro, "apresentado_em": "2025-03-10"}])

        r = limpar(self.entrada, REFERENCIA)

        self.assertNotIn(outro, r.precatorios)
        self.assertIn("APRESENTACAO_SEM_PRECATORIO", self._regras(r.diario, Categoria.AVISO))


if __name__ == "__main__":
    unittest.main()
