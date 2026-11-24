# DIAGNÓSTICO

Os números não batem devido os seguintes fatores:
- Pagamentos são somados mais de uma vez devido o arquivo diário repetir eventos, a reexecução (em caso de quebra) soma novamente e uma correção vira um novo pagamento;
- Prazo de pagamento está errado em pelo menos dois precatórios, informando prazos de vencimento em 31/12/2027 quando vencem em 31/12/2026.
- Estornos entram somando;
- Eventos que o script não entendem somem sem aviso;
- A comparação com o tribunal não funciona, pois ela é feita por texto exato sobre um arquivo alterado pelo Excel, gerando divergências falsas e escondendo as reais.

## EVIDÊNCIAS DE PROBLEMAS IDENTIFICADOS:

### 1 - Pagamentos contados mais de uma vez
Nível: crítico

Tipo: causa
#### Arquivo: schema.sql
- Linhas 8-16
    - problema: tabela pagamento não tem UNIQUE na coluna evento_id e também não armazena a coluna atualizado_em, fazendo o banco aceitar repetições de registros e não saber qual versão é a válida;

#### Arquivo: pagamentos.json
- Linhas: 2 e 66
    - evento_id: ev-001;
    - problema: o evento aparece 2 vezes, uma com valor 15000.0 (atualizado em 10/03/2025 - 10:00) e outra com valor 15500.0 (atualizado em 11/03/2025 - 09:00). Deveria ser tratado como atualização/correção e não um segundo registro;
- Linhas: 10 e 26
    - evento_id: ev-002;
    - problema: o evento aparece 2 vezes, com valores idênticos;

O arquivo diário traz os últimos 7 dias, então cada evento chega em até 7 arquivos seguidos. O script soma cada valor ao total existente e, quando falha, é executado novamente com os mesmos dados. Devido a falta de idempotencia no script os eventos importados antes da falha são somados novamente.

#### Impacto
Os problemas mencionados faz com que o total pago fique inflado e o saldo a pagar encolhido. No processo 0012345-10.2019.8.26.0053, o total correto é R$ 18.000,50 (15.500 + 2.500,50) somando os eventos que devem ser considerados. Ao somar todos os eventos do processo existentes neste arquivo (pagamentos.json), o total vira quase o dobro, R$ 35.501,00. Devido a janela de 7 dias, um mesmo evento pode ser somado até 7 vezes e, um precatório que parece quitado sai da priorização e para de ser cobrado.

### 2 - Prazo de pagamento calculado errado

#### Arquivo: hub.csv

Nível: crítico

Tipo: causa
- Linha: 2
    - processo: 0012345-10.2019.8.26;
    - problema: o dia 2 de abril foi considerado fora do limite. O processo foi apresentado em 2025-04-02 e está com prazo de pagamento para 2027-12-31 mas, pela regra, quem é apresentado até 2 de abril tem prazo até 31/12 do ano seguinte, ou seja, o prazo correto seria 2026-12-31;
- Linha: 6
    - processo: 0056789-54.2017.4.03.6100;
    - problema: o sistema utilizou a data em UTC, padrão internacional e não o horário de Brasilia. O processo foi apresentado 2025-04-03T01:00:00Z, que é equivalente a 2 de abril às 22h no horário de Brasília, então o hub deveria considerar o prazo de pagamento como 2026-12-31, diferente do apresentado que é 2027-12-31;
- Coluna: apresentado_em
    - linhas: 2-6;
    - problema: mistura de datas puras e datas com hora em fusos diferentes;

#### Impacto
A equipe utiliza esses prazos para a priorização da carteira, logo esse é o problema mais urgente. Os dois precatórios citados acima somam R$ 67.000 de valor de face com vencimento correto em 31/12/2026, mas o sistema está mostrando o vencimento como se fosse 31/12/2027.

### 3 - Estorno somado como pagamento
Nível: alto

Tipo: causa
#### Arquivo: pagamentos.json

- Linha: 58;
    - evento_id: ev-007;
    - problema: pagamento do tipo "estorno" no valor de 5000. Indica estorno do evento_id ev-006 (linha 50, mesmo processo e valor, um dia antes);
    - DUVIDA: NÃO DEVERIA VIR COMO TIPO "PAGAMENTO" E VALOR "-5000"?;
- Linha: 82;
    - evento_id: ev-009;
    - problema: pagamento com valor -200. Um possível estorno com tipo errado ("pagamento" no lugar de "estorno") e valor inconsistente ao critério do schema (schema.sql - linha 13);

#### Arquivos: DOCUMENTACAO_TRIBUNAL.MD | schema.sql
- problema: a documentação (DOCUMENTACAO_TRIBUNAL.MD - linha 15) diz que o tipo é sempre "pagamento". O schema (schema.sql - linha 12) aceita "estorno", mas o fluxo é de soma;
- DUVIDA: O CORRETO É A COLUNA "TIPO" DO SQL ACEITAR APENAS "PAGAMENTO"?

#### Impacto
No caso do processo 0034567 (pagamentos.json - linhas 51-59 - ev-006 e ev-007 respectivamente), um script que só soma registra R$ 10.000,00, mas o total pago correto é R$ 0,00 devido o suposto estorno. O saldo irá aparecer como R$ 2.500 quando o correto é R$ 12.500.
Ainda pior, esse precatório está vencido desde 31/12/2025, então o erro de estorno acaba escondendo uma dívida em traso.

### 4 - Eventos descartados sem aviso
Nível: alto

Tipo: causa
#### Arquivo: pagamentos.json
- Linhas 10 e 26: 
    - evento_id: ev-002;
    - problema: valor informado no formato de texto e data_pagamento diferente do leiaute definido;
- Linha 34: 
    - evento_id: ev-004;
    - problema: valor nulo;
- Linha 82: 
    - evento_id: ev-009;
    - problema: valor -200;
- Linha 90: 
    - evento_id: ev-010;
    - problema: processo vazio com valor de R$ 750;
- Linha 98: 
    - evento_id: ev-11;
    - problema: A chave estrangeira (REFERENCES precatorio) rejeita o evento, então o valor de R$ 4.000 para o processo 0067890 (linha 99) existe no arquivo tribunal.csv mas não existe em hub.csv;

#### Impacto
No processo 0067890 (linha 98), os R$ 4.000 pagos não aparecem em lugar nenhum, ou seja, pagamentos reais estão deixando de ser registrados e ninguém fica sabendo.


### 5 - Comparação tribunal x hub quebrado por formato
Nível: médio

Tipo: causa
#### Arquivo: tribunal.csv
- Todas as linhas estão formatadas erradas, em Windows-1252, separado por ';' e com valores com ',' como separador decimal, diferente da documentação (DOCUMENTACAO_TRIBUNAL.MD - linhas 20 e 26) que promete UTF-8, separado por ',' e como separador decimal '.'.

#### Arquivo hub.csv
- Linha 2:
    - problema: a coluna ente contém valor com formatação diferente que a apresentada no arquivo tribunal.csv;
    - valor no arquivo: MUNICIPIO DE SAO PAULO;
    - valor em tribunal.csv: Município de São Paulo;
- Linha: 3;
    - problema: número de processo sem máscara (fora do formato CNJ), diferente do que é apresentado no arquivo tribunal.csv;
    - valor no arquivo: 00234562120208260053;
    - valor em tribunal.csv no padrão CNJ: 0023456-21.2020.8.26.0053;
- O passo 3 do fluxo operacional apresentado procura pelo nome do ente e o número do processo exatamente como estão escritos, logo, os casos citados acima não serão considerados em uma busca;

#### Impacto
Devido divergências de grafia a operação gasta tempo com falsos alarmes enquanto problemas reais se perdem no meio deles. Salvar no Excel também pode ser um problema, pois um número de processo sem máscara perde os zeros à esquerda e pode virar notação científica. Por exemplo:
- Número do processo sem máscara: 00234562120208260053;
- Número do processo no formato esperado: 0023456-21.2020.8.26.0053;
- Como pode ficar al salvar no Excel: 2,34562E+16;

### 6 - Divergências reais
Nível: médio;

Tipo: consequência (5)

Divergências invisíveis

| Nº processo | tribunal.csv | hub.csv | impacto |
| :--- | :---: | ---: | ---: |
| 0023456-21.2020.8.26.0053 | valor de face 30.000,00 (linha 3) | 31.000,00 (linha 3) | saldo errado |
| 0045678-43.2021.5.02.0011 | ente União (linha 5) | Município de Santos (linha 5) | cobrança vai para ente errado |
| 0056789-54.2017.4.03.6100 | não está na lista | linha 6 | precatório pode já estar pago ou cancelado |
| 0067890-65.2016.8.26.0053 | linha 6 | não está no hub, e tem pagamento (ev-011) | está fora da carteira mesmo recebendo pagamento |

### 7 - Documentação do tribunal desatualizada
Nível: médio;

Tipo: causa (1, 3, e 4)
- Linha 15: tipo é sempre "pagamento", mas o tipo "estorno" existe e não tem sua convenção de sinal definida;
- Linha 11: evento_id como identificador único, mas o mesmo id vem com valores diferentes e, apesar de ser único, existe as "versões" ... TOoooooDOooooooooooooooo
- Não define o fuso das datas e é importante para o cálculo correto dos prazos. Por exemplo, 2025-04-03T01:00:00Z é dia 3 em UTC, mas dia 2 em Brasília;
- Não define o campo com data de apresentação para tribunal.csv nem precatorio.csv. Ela vem de um arquivo separado, `apresentacoes.json`, que não é mencionado no leiaute nem no fluxo e traz o registro do precatório `0056789` que não aparece na lista do tribunal;
- O processo diz que recebe um arquivo com dados dos últimos 7 dias, mas em pagamentos.json foi identificado um intervalo de quase 6 meses, 20/02 - 10/08/2025 pra ser mais exato;

#### Impacto
A documentação errada faz com que as pessoas trabalhem com falsas convicções e, ao aparecer um problema, ninguém sabe se o erro está no hub, script ou tribunal.



