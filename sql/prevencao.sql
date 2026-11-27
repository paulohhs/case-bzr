-- =====================================================================
-- Prevenção: o schema como DEVERIA ser (desenho-alvo), não a migração.
-- PostgreSQL 14+ (testado no 16). Cobre os 4 problemas do diagnóstico.
--
-- Premissa: a grafia do ente é unificada pela limpeza (adota a do tribunal),
-- então ente_devedor é texto simples e toda carga vem de saida/*.csv.
-- =====================================================================

CREATE TABLE precatorio (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    numero_processo VARCHAR(25) NOT NULL UNIQUE                 -- CHAR(20) truncava o nº mascarado
        CHECK (numero_processo ~ '^\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}$'),
    ente_devedor    TEXT NOT NULL,                             -- grafia já unificada na limpeza
    valor_face      NUMERIC(15,2) NOT NULL CHECK (valor_face > 0),
    apresentado_em  DATE,                                      -- data civil em Brasília
    prazo_pagamento DATE GENERATED ALWAYS AS (                 -- [2] o banco calcula, a aplicação não grava
        make_date(
            EXTRACT(YEAR FROM apresentado_em)::int
            + CASE WHEN (EXTRACT(MONTH FROM apresentado_em), EXTRACT(DAY FROM apresentado_em)) <= (4, 2)
                   THEN 1 ELSE 2 END,
            12, 31)
    ) STORED,
    situacao_conciliacao TEXT NOT NULL DEFAULT 'pendente'      -- divergência real fica visível
        CHECK (situacao_conciliacao IN ('pendente','conciliado','divergente','somente_tribunal','somente_hub'))
    -- sem coluna total_pago: [1] o total vem da view, nunca de um contador acumulado
);

CREATE TABLE pagamento (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    evento_id     TEXT          NOT NULL UNIQUE,               -- [1] UNIQUE barra o reenvio duplicado
    precatorio_id BIGINT        NOT NULL REFERENCES precatorio (id),
    tipo          TEXT          NOT NULL CHECK (tipo IN ('pagamento','estorno')),
    valor         NUMERIC(15,2) NOT NULL CHECK (valor > 0),    -- [3] o sinal vem do tipo, não do valor
    pago_em       DATE          NOT NULL,
    atualizado_em TIMESTAMPTZ   NOT NULL                       -- versão informada pelo tribunal
);
CREATE INDEX pagamento_precatorio ON pagamento (precatorio_id);

-- [4] O que não pode ser importado não some: fica aqui, com motivo.
CREATE TABLE evento_quarentena (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recebido_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    evento_id   TEXT,
    motivos     TEXT[] NOT NULL,
    payload     JSONB  NOT NULL                                -- o evento exatamente como veio
);

-- [1][3] Posição derivada dos eventos: estorno subtrai, total nunca é um contador.
CREATE VIEW precatorio_saldo AS
SELECT pr.id, pr.numero_processo, pr.ente_devedor, pr.valor_face,
       pr.apresentado_em, pr.prazo_pagamento, pr.situacao_conciliacao,
       COALESCE(SUM(CASE pg.tipo WHEN 'estorno' THEN -pg.valor ELSE pg.valor END), 0)::numeric(15,2) AS total_pago,
       (pr.valor_face - COALESCE(SUM(CASE pg.tipo WHEN 'estorno' THEN -pg.valor ELSE pg.valor END), 0))::numeric(15,2) AS saldo
FROM precatorio pr
LEFT JOIN pagamento pg ON pg.precatorio_id = pr.id
GROUP BY pr.id;
