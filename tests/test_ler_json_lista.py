"""Testes de `ler_json_lista`: parse da lista de topo, numeração de linhas e erros."""

import unittest

from limpeza.leitura import ArquivoLido, ErroArquivo, ObjetoJson, ler_json_lista


def _arquivo(texto: str, nome: str = "pagamentos.json") -> ArquivoLido:
    """ArquivoLido mínimo: `ler_json_lista` só usa `.texto` e `.nome`."""
    return ArquivoLido(nome=nome, sha256="x" * 64, codificacao="utf-8", texto=texto)


class TestLerJsonLista(unittest.TestCase):
    def test_lista_valida_preserva_indice_e_dados(self):
        objetos = ler_json_lista(_arquivo('[{"a": 1}, {"b": 2}]'))

        self.assertEqual(len(objetos), 2)
        self.assertTrue(all(isinstance(o, ObjetoJson) for o in objetos))
        self.assertEqual([o.indice for o in objetos], [0, 1])
        self.assertEqual([o.dados for o in objetos], [{"a": 1}, {"b": 2}])

    def test_lista_vazia_retorna_lista_vazia(self):
        self.assertEqual(ler_json_lista(_arquivo("[]")), [])

    def test_elementos_nao_precisam_ser_objetos(self):
        # `dados` é `object`: a função não exige dicts, só uma lista no topo.
        objetos = ler_json_lista(_arquivo('[1, "dois", null, [3]]'))
        self.assertEqual([o.dados for o in objetos], [1, "dois", None, [3]])

    def test_linha_de_inicio_de_cada_objeto(self):
        texto = '[\n  {"a": 1},\n  {"b": 2}\n]'
        #        linha 1     linha 2        linha 3
        objetos = ler_json_lista(_arquivo(texto))
        self.assertEqual([o.linha for o in objetos], [2, 3])

    def test_tudo_em_uma_linha_so(self):
        objetos = ler_json_lista(_arquivo('[{"a": 1},{"b": 2}]'))
        self.assertEqual([o.linha for o in objetos], [1, 1])

    def test_virgulas_e_colchetes_dentro_de_string_nao_confundem_linhas(self):
        # Vírgula, ']' e '}' dentro de uma string não podem iniciar um "novo elemento".
        texto = '[\n  {"t": "tem , e ] e } dentro"},\n  {"n": 2}\n]'
        objetos = ler_json_lista(_arquivo(texto))
        self.assertEqual(len(objetos), 2)
        self.assertEqual([o.linha for o in objetos], [2, 3])

    def test_aspas_escapadas_nao_fecham_a_string(self):
        # Se o escape fosse ignorado, o '\"' fecharia a string e o ',' seguinte
        # contaria um elemento a mais. Regressão do contador de linhas.
        texto = '[\n  {"t": "a\\",b"},\n  {"n": 2}\n]'
        objetos = ler_json_lista(_arquivo(texto))
        self.assertEqual(len(objetos), 2)
        self.assertEqual([o.linha for o in objetos], [2, 3])
        self.assertEqual(objetos[0].dados, {"t": 'a",b'})

    def test_json_invalido_vira_erro_arquivo(self):
        with self.assertRaises(ErroArquivo) as ctx:
            ler_json_lista(_arquivo('[{"a": 1}', nome="pagamentos.json"))
        mensagem = str(ctx.exception)
        self.assertIn("pagamentos.json", mensagem)
        self.assertIn("JSON inválido", mensagem)

    def test_topo_nao_e_lista_vira_erro_arquivo(self):
        for texto in ('{"a": 1}', "42", '"texto"'):
            with self.subTest(texto=texto):
                with self.assertRaises(ErroArquivo) as ctx:
                    ler_json_lista(_arquivo(texto))
                self.assertIn("esperava uma lista", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
