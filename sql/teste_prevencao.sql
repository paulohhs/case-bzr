-- Teste do schema-alvo num banco descartável. Rodar de dentro de sql/:
--   createdb teste_prevencao && psql -d teste_prevencao -f teste_prevencao.sql
-- Os erros na seção "erros esperados" são o comportamento correto.
\set ON_ERROR_STOP on
\i prevencao.sql

-- Dados já limpos (uma linha por evento_id), como a limpeza os entrega.
INSERT INTO precatorio (numero_processo, ente_devedor, valor_face, apresentado_em) VALUES
 ('0012345-10.2019.8.26.0053','Municipio de Sao Paulo',45000,'2025-04-02'),  -- no corte -> 2026
 ('0023456-21.2020.8.26.0053','Municipio de Sao Paulo',31000,'2025-04-03'),  -- depois  -> 2027
 ('0034567-32.2018.8.26.0405','Estado de Sao Paulo',   12500,'2024-02-29');  -- bissexto

\echo '--- prazo gerado pelo banco a partir de apresentado_em:'
SELECT numero_processo, apresentado_em, prazo_pagamento FROM precatorio ORDER BY id;

INSERT INTO pagamento (evento_id, precatorio_id, tipo, valor, pago_em, atualizado_em) VALUES
 ('ev-001',1,'pagamento',15500,'2025-03-10','2025-03-11T09:00:00-03:00'),
 ('ev-006',3,'pagamento', 5000,'2025-02-20','2025-02-20T10:00:00-03:00'),
 ('ev-007',3,'estorno',   5000,'2025-02-21','2025-02-21T10:00:00-03:00');

\echo '--- posicao (estorno subtrai; total derivado dos eventos):'
SELECT numero_processo, ente_devedor, total_pago, saldo, prazo_pagamento FROM precatorio_saldo ORDER BY id;

\echo '--- erros esperados (cada comando abaixo deve falhar):'
\set ON_ERROR_STOP off
-- [1] evento_id repetido nao entra duas vezes (UNIQUE)
INSERT INTO pagamento (evento_id,precatorio_id,tipo,valor,pago_em,atualizado_em)
 VALUES ('ev-001',1,'pagamento',15500,'2025-03-10','2025-03-11T09:00:00-03:00');
-- [3] valor <= 0 (CHECK valor > 0)
INSERT INTO pagamento (evento_id,precatorio_id,tipo,valor,pago_em,atualizado_em)
 VALUES ('ev-9',1,'pagamento',-200,'2025-07-20',now());
-- tipo invalido (CHECK tipo IN ('pagamento','estorno'))
INSERT INTO pagamento (evento_id,precatorio_id,tipo,valor,pago_em,atualizado_em)
 VALUES ('ev-8',1,'ajuste',10,'2025-07-20',now());
-- pagamento para precatorio inexistente (FK)
INSERT INTO pagamento (evento_id,precatorio_id,tipo,valor,pago_em,atualizado_em)
 VALUES ('ev-x',999,'pagamento',10,'2025-07-20',now());
-- formato CNJ invalido (CHECK do formato)
INSERT INTO precatorio (numero_processo, ente_devedor, valor_face) VALUES ('123','X',10);
-- valor_face nao positivo (CHECK valor_face > 0)
INSERT INTO precatorio (numero_processo, ente_devedor, valor_face) VALUES ('0099999-99.2020.8.26.0053','X',-1);
-- [2] prazo e coluna gerada: nao se escreve nela
UPDATE precatorio SET prazo_pagamento='2030-12-31' WHERE id=1;
