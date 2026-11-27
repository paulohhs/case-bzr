# CASE-BZR
## Case técnico
Projeto desenvolvido em Python 3.14.4, sem dependências externas, utilizando apenas bibliotecas nativas.

Tem como objetivo ler arquivos originais e realizar uma "limpeza" para produzir uma base confiável, junto com um relatório do que foi corrigido, descartado ou ficou em dúvida e por quê.

### Utilização de IA
Foi utilizado IA para criar um plano de implementação e apoio durante o implementação do plano.

### Como rodar

```bash
uv python install 3.14.4          # ou use qualquer Python 3.14.4
python3.14 -m limpeza --entrada dados --saida saida            # gera a base limpa e o relatório
python3.14 -m limpeza --entrada dados --saida saida --estrito  # sai com código 1 se houver dúvidas

```

### Executar testes
```bash
# Testes unitários e de integração
python3.14 -m unittest discover -s tests -t .

# Teste sql - necessário alterar o caminho do primeiro comando para o caminho do local do projeto sem '{}'
docker run --rm --name pg_teste -e POSTGRES_PASSWORD=x -e POSTGRES_DB=teste \
  -v "{COLOCAR_AQUI_O_CAMINHO_DO_PROJETO}/case-bzr/sql":/sql:ro -d postgres:16 \ # sobe um Postgres descartável com a pasta sql/ montada (somente leitura)
&& until docker exec pg_teste pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done \ # espera o banco ficar pronto
&& docker exec -w /sql pg_teste psql -U postgres -d teste -f teste_prevencao.sql; \ # roda o teste
docker rm -f pg_teste # remove o container
