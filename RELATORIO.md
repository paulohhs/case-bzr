# DIAGNÓSTICO

Os números não batem por três causas principais:
- Pagamentos são somados mais de uma vez devido o arquivo diário repetir eventos, a reexecução (em caso de quebra) soma novamente e uma correção vira um novo pagamento;
- Eventos que o script não entendem somem sem aviso;
- Estornos entram somando;

Além disso, foi identificado que existe prazo de pagamento com cálculo errado em pelo menos dois precatórios, onde foi informado vencimento 31/12/2027 mas deveria ser 31/12/2026. A comparação com o tribunal também não funciona, pois ela é feita por texto exato sobre um arquivo alterado pelo Excel, gerando divergências falsas e escondendo as reais.

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

#### Impacto
No caso do processo 0034567 (pagamentos.json - linhas 51-59 - ev-006 e ev-007 respectivamente), um script que só soma registra R$ 10.000,00, mas o total pago correto é R$ 0,00 devido o suposto estorno. O saldo irá aparecer como R$ 2.500 quando o correto é R$ 12.500.
Ainda pior, esse precatório está vencido desde 31/12/2025, então o erro de estorno acaba escondendo uma dívida em atraso.

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


### Formato dos arquivos e divergências (tratado na limpeza)
Nível: médio

Tipo: contexto (consequência: divergências falsas e reais)

O `tribunal.csv` chega em Windows-1252, separado por `;` e com vírgula decimal, diferente da documentação (DOCUMENTACAO_TRIBUNAL.md - linhas 20 e 26), que promete UTF-8, `,` e ponto decimal. O hub ainda traz o ente com grafia diferente (linha 2: `MUNICIPIO DE SAO PAULO` vs `Município de São Paulo` no tribunal) e o número do processo sem máscara (linha 3: `00234562120208260053`). A limpeza corrige encoding, grafia e máscara a cada execução, então isto não é uma causa à parte — é a razão de a conferência manual do passo 3 (que procura o nome e o número exatamente como estão escritos) gerar **divergências falsas** por grafia e **esconder as reais**.

#### Impacto
A operação gasta tempo com falsos alarmes enquanto divergências reais se perdem. Salvar o `tribunal.csv` no Excel agrava: um número sem máscara perde os zeros à esquerda e pode virar notação científica (`00234562120208260053` → `2,34562E+16`). As divergências reais que sobram depois da limpeza:

| Nº processo | tribunal.csv | hub.csv | impacto |
| :--- | :---: | ---: | ---: |
| 0023456-21.2020.8.26.0053 | valor de face 30.000,00 (linha 3) | 31.000,00 (linha 3) | saldo errado |
| 0045678-43.2021.5.02.0011 | ente União (linha 5) | Município de Santos (linha 5) | cobrança vai para ente errado |
| 0056789-54.2017.4.03.6100 | não está na lista | linha 6 | precatório pode já estar pago ou cancelado |
| 0067890-65.2016.8.26.0053 | linha 6 | não está no hub, e tem pagamento (ev-011) | está fora da carteira mesmo recebendo pagamento |

### 5 - Schema do banco incoerente com os dados
Nível: médio;

Tipo: causa (1 e 4)
- O schema não tem `apresentado_em` nem `prazo_pagamento`, mas o hub exporta os dois. Ou o `schema.sql` não é o de produção, ou esses dados vêm de outro lugar.
- `CHAR(20)` não comporta o número mascarado (ver o bloco de formato acima), falta de `UNIQUE (evento_id)` e de `atualizado_em` (ver 1). O `CHECK (valor > 0)` combinado com "ignora e segue" faz o evento sumir em silêncio (ver 4).

# LIMPEZA
O programa usa só a biblioteca padrão, sem dependências. Os originais são lidos em bytes e o SHA-256 de cada um vai para o relatório. O programa recusa gravar na pasta de entrada e confere, ao final, que os originais não mudaram. A mesma entrada gera exatamente a mesma saída (há um teste para isso).

### O que o programa gera (em `saida/`)

| Arquivo | Conteúdo |
|---|---|
| `precatorios_limpos.csv` | Precatórios conciliados, com prazo recalculado, total pago, saldo, situação e pendências |
| `pagamentos_limpos.csv` | Eventos aceitos, um por `evento_id`, com o valor já com sinal |
| `pagamentos_em_duvida.json` | Eventos em quarentena: o original exato e o motivo |
| `relatorio_limpeza.md` / `.json` | Tudo o que foi corrigido, descartado, deixado em dúvida ou sinalizado, com arquivo, linha e motivo |

### Regras e decisões

| Regra | Decisão | Por quê |
|---|---|---|
| Duplicata exata | Fica a primeira ocorrência; as demais são **descartadas** | É reenvio da janela de 7 dias ou reimportação |
| Mesmo `evento_id` com conteúdo diferente | Vale a versão com o `atualizado_em` mais recente, comparando instantes e não textos. Empate com conteúdo diferente vira **dúvida** | É uma correção do tribunal, não um novo pagamento |
| Versão mais nova inválida | **Dúvida**, sem voltar para a versão antiga | A antiga foi corrigida; usá-la seria adivinhar |
| Estorno | Subtrai do total | Senão o total fica inflado (3) |
| Valor negativo, zero ou nulo; processo vazio ou inexistente; tipo desconhecido | **Dúvida** (quarentena), fora dos totais | Pode ser dinheiro real: não descartar nem adivinhar |
| Valor `"2.500,50"` | Corrigido para 2500.50 | Formato brasileiro sem ambiguidade |
| Valor `"1.500"` | **Dúvida** | Pode ser 1500 ou 1,5 |
| Valor com 3 ou mais casas decimais | **Dúvida** | Não arredondar dinheiro em silêncio |
| Data `"10/04/2025"` | Vale DD/MM ou MM/DD conforme a única leitura que não fica depois do `atualizado_em`. Se as duas forem possíveis, **dúvida** | 4 de outubro seria depois da última alteração do registro |
| Processo sem máscara | Recebe a máscara CNJ | Mesmo processo, outro formato |
| Processo com menos de 20 dígitos | **Dúvida**, sem completar zeros | Pode ser truncamento do Excel ou outro erro |
| `tribunal.csv` em Windows-1252, com `;` e vírgula decimal | Lido e corrigido; os acentos são recuperados | São os bytes do Excel, não caracteres perdidos |
| Ente com grafia diferente (acento, caixa, espaço) | Mesmo ente; vale a grafia do tribunal | formato |
| Ente ou valor de face diferentes de verdade | Vale o do tribunal, a situação fica "divergente" e o caso vira **dúvida** | O tribunal é a fonte oficial, mas alguém precisa confirmar |
| Precatório em só uma das fontes | Entra com situação `somente_tribunal` ou `somente_hub` e vira **dúvida** | Não some, e fica visível |
| `apresentado_em` com hora | Vale a data civil em Brasília | 2 |
| Prazo | Sempre recalculado; o do hub não é usado | 2 |
| Dígito verificador CNJ inválido | Aviso, sem descartar | dúvida |

### Resultado nos arquivos recebidos

| Processo | Total pago limpo | Prazo limpo | Situação |
|---|---:|---|---|
| 0012345-10.2019.8.26.0053 | 18.000,50 | **2026-12-31** (o hub dizia 2027) | conciliado |
| 0023456-21.2020.8.26.0053 | 9.200,00 | 2027-12-31 | divergente (valor de face) |
| 0034567-32.2018.8.26.0405 | 0,00 | 2025-12-31 | conciliado |
| 0045678-43.2021.5.02.0011 | 3.000,00 | 2026-12-31 | divergente (ente) |
| 0056789-54.2017.4.03.6100 | 0,00 | **2026-12-31** (o hub dizia 2027) | somente_hub |
| 0067890-65.2016.8.26.0053 | 4.000,00 | não calculado (sem data de apresentação) | somente_tribunal |

Dos 13 eventos recebidos, 8 foram aceitos, 2 descartados (`ev-002` repetido e a versão antiga do `ev-001`) e 3 ficaram em dúvida (`ev-004`, `ev-009`, `ev-010`). Houve 15 correções e 7 dúvidas no total. O detalhe linha a linha está em `saida/relatorio_limpeza.md`.

# PREVENÇÃO
### Processo
1. Garantir que os arquivos do tribunal no Excel não são abertos/salvos. O arquivo pode ser armazenado da mesma forma que chegou, numa pasta somente leitura. A conferência com o hub utiliza este programa, que irá comparar pelo número normalizado e mostrar apenas divergências reais. Quando necessário olhar no Excel, realizar uma cópia;
3. Criação de alertas e revisão diária, com um responsável e prazo definido, garantindo que não ocorra erros sem ninguém saber;
4. Garantir que a importação é idempotente, conseguindo realizar reprocessamento sem preocupações de duplicidades;
5. Alinhar com o tribunal melhor definição de leiaute, levantando questões como estorno e convenção de sinal, controle de versão por atualizado_em, melhoria na definição das datas com fusos e data de apresentação no tribunal.csv (arquivo schema.sql) e a janela real dos dados do arquivo;

Importante encontrar o problema no cálculo de prazo na importação dos pagamentos.

### Script de importação
1. Usar as regras deste pacote (limpeza/normalizacao.py e limpeza/regras.py) como biblioteca, em vez de reimplementá-las.
2. Ler e validar o arquivo inteiro antes de gravar qualquer coisa. Um JSON truncado não importa nada.
3. Uma transação por arquivo: valida o arquivo inteiro, insere os eventos aceitos (o UNIQUE de evento_id barra reenvio) e grava a quarentena. Ou tudo entra, ou nada.
4. Nunca acumular "total pago". O total vem sempre da soma dos eventos.
5. Todo evento tem destino e a conta fecha (aceitos + descartados + em dúvida = lidos).
6. Enviar alerta quando houver dúvidas (--estrito).

### Banco (sql/prevencao.sql, testado no PostgreSQL 16)

O `prevencao.sql` descreve o schema como deveria ser (desenho-alvo), não a migração; o teste está em sql/teste_prevencao.sql. Cada peça previne um problema:

| Peça do schema |	Problema |
| :--- | :---: |
| Tabela pagamento com evento_id UNIQUE e atualizado_em NOT NULL | 1 |
| evento_quarentena com o evento original (jsonb) e os motivos | 4 |
| View precatorio_saldo: total pago com estorno negativo, sem contador | 1, 3 |
| prazo_pagamento como coluna gerada a partir de apresentado_em DATE (data de Brasília) | 2 |
| numero_processo VARCHAR(25) com CHECK do formato CNJ | formato |
| situacao_conciliacao para deixar a divergência visível | divergências |

Versão e deduplicação são resolvidas na limpeza antes da carga (o pagamentos_limpos.csv já traz uma linha por evento_id); o UNIQUE é a trava no banco.

Migrar uma base já existente é um passo à parte: a tabela de pagamentos atual tem duplicatas e não guarda a versão dos eventos, então não dá para limpá-la em SQL — renomeia-se para pagamento_legado e carrega-se a tabela nova a partir de saida/pagamentos_limpos.csv, reprocessando também os arquivos históricos recebidos.

# Dúvidas antes de pôr em produção
### Para o tribunal
A `DOCUMENTACAO_TRIBUNAL.md` parece desatualizada e é a raiz de boa parte das perguntas abaixo: não define o fuso das datas, a convenção de sinal do estorno, a data de apresentação (vem do `apresentacoes.json`, fora do leiaute) nem a janela real dos arquivos (diz 7 dias, mas `pagamentos.json` cobre ~6 meses).

1. Estorno é um tipo oficial? O valor vem sempre positivo? Como saber qual pagamento está sendo estornado?
2. Versões: o `evento_id` se mantém quando o evento é corrigido? É o `atualizado_em` que decide qual versão vale? Um mesmo pagamento pode voltar com outro id?
3. O arquivo `pagamentos.json` deveria ter 7 dias, mas tem eventos de fevereiro a agosto de 2025. Ele é cumulativo? Um evento cancelado some do arquivo ou chega com outro tipo?
4. Por que o processo 0056789 saiu da lista (pago, cancelado, outro tribunal)?
5. Quem gera o arquivo `apresentacoes.json`, com que frequência, e por que ele não está no leiaute? Qual data vale oficialmente e em que fuso?

Os dados do ev-002 e a codificação do arquivo `tribunal.csv` são diferentes do leiaute. A limpeza faz o tratamento dos dois casos, mas é importante verificar se foi erro pontual ou o gerador mudou.

### Para a operação
1. O `schema.sql` é o de produção? Ele não tem `apresentado_em` nem `prazo_pagamento`, e CHAR(20) não comporta o número mascarado que o hub exporta. E o `tribunal.csv` que temos é o anexo original ou a versão salva no Excel — o original está guardado?
2. Temos log de quantas vezes o script foi reexecutado e os arquivos diários antigos? É útil para medir e planejar uma futura correção e, no mesmo sentido de correção, os prazos de pagamentos dos precatórios.
3. A regra "o tribunal prevalece" em ente e valor de face foi adotada na limpeza e precisa de aprovação. Questão: o arquivo `hub.csv` pode ter sido editado após exportação? Os processos 0023456 e 0045678 tem valor de face e ente diferentes de `tribunal.csv`.
4. Quem trata a quarentena e os alertas, e em quanto tempo? Os pagamentos dos eventos ev-004 (valor nulo) e o ev-010 (sem processo, R$ 750) aconteceram? De que valor e em qual processo? E o evento 0067890, que venceu em 31/12/2025 e não aparece no hub, alguém está acompanhando?


