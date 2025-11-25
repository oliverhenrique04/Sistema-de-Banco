-- População & Consultas & Avançado

-- 10 usuários (COM TIPO_PESSOA)
INSERT INTO tb_usuario (nome, email, telefone, doc_cpf_cnpj, tipo_pessoa)
SELECT
  'Usuário ' || g,
  'user' || g || '@demo.com',
  '+55 11 9' || LPAD((10000000+g)::text,8,'0'),
  '0000000000' || g::text,
  CASE WHEN g <= 5 THEN 'PF' ELSE 'PJ' END
FROM generate_series(1,10) g;

-- Endereços
INSERT INTO tb_endereco (id_usuario, logradouro, numero, bairro, cidade, estado, cep)
SELECT id_usuario,
       'Rua ' || id_usuario, (10+id_usuario)::text, 'Centro', 'São Paulo', 'SP', '01000-000'
FROM tb_usuario;

-- Comerciantes
INSERT INTO tb_comerciante (nome_fantasia, cnpj, mcc)
SELECT 'Loja '||g, '1111111111'||g::text, '5999'
FROM generate_series(1,10) g;

-- Adicionado empresas específicas para categorias essenciais e lazer
INSERT INTO tb_comerciante (nome_fantasia, cnpj, mcc) VALUES
('Super Mercado Central', '222222222201', '5411'),
('Imobiliaria Novo Lar', '333333333301', '6513'),
('Internet & TV SA', '444444444401', '4814'), -- ID 13
('Cinema Pop', '555555555501', '7832'),
('Uber BR', '666666666601', '4121'),
('Cia de Eletricidade', '777777777701', '4900'), -- ID 11
('Saneamento Basico', '888888888801', '4900'); -- ID 12

-- Contas
INSERT INTO tb_conta (id_usuario, numero_conta, agencia, saldo_cents)
SELECT id_usuario, LPAD(id_usuario::text, 8, '0'), '0001', 100000
FROM tb_usuario;

-- Empréstimos
INSERT INTO tb_emprestimo (id_conta, principal_cents, juros_aa_pct, prazo_meses, status)
SELECT c.id_conta, 500000 + (i*10000), 35.0, 12 + (i % 12), 'approved'
FROM tb_conta c
JOIN LATERAL (SELECT floor(random()*10)::int i) r ON true
LIMIT 10;

-- Parcelas
WITH base AS (
  SELECT e.id_emprestimo, e.principal_cents, e.prazo_meses, e.iniciado_em
  FROM tb_emprestimo e
)
INSERT INTO tb_parcela (id_emprestimo, num_parcela, vencimento, valor_cents)
SELECT b.id_emprestimo, n, (b.iniciado_em + make_interval(months => n))::date, (b.principal_cents / b.prazo_meses)
FROM base b, LATERAL generate_series(1, b.prazo_meses) n;

-- Transações
INSERT INTO tb_transacao (id_conta_de, id_conta_para, id_comerciante, tipo, valor_cents, status, referencia, criado_em, confirmado_em)
SELECT
  CASE WHEN t % 4 IN (0,1) THEN c1.id_conta ELSE NULL END,
  CASE WHEN t % 4 = 1 THEN c2.id_conta ELSE NULL END,
  CASE WHEN t % 4 = 0 THEN m.id_comerciante ELSE NULL END,
  CASE WHEN t % 4 = 0 THEN 'payment'
       WHEN t % 4 = 1 THEN 'transfer'
       WHEN t % 4 = 2 THEN 'deposit'
       ELSE 'withdrawal' END::transaction_type,
  (1000 + (t*17))::bigint,
  CASE WHEN t % 10 = 0 THEN 'failed' ELSE 'confirmed' END::transaction_status,
  'REF-' || t,
  now() - (t || ' hours')::interval,
  CASE WHEN t % 10 = 0 THEN NULL ELSE now() - ((t-1) || ' hours')::interval END
FROM generate_series(1,120) t
CROSS JOIN LATERAL (SELECT c.id_conta FROM tb_conta c ORDER BY random() LIMIT 1) c1
CROSS JOIN LATERAL (SELECT c.id_conta FROM tb_conta c ORDER BY random() LIMIT 1) c2
CROSS JOIN LATERAL (SELECT m.id_comerciante FROM tb_comerciante m ORDER BY random() LIMIT 1) m;

-- Views
CREATE OR REPLACE VIEW vw_contas_saldo AS
SELECT c.id_conta, u.nome AS titular, c.numero_conta, c.agencia, c.saldo_cents, c.status
FROM tb_conta c JOIN tb_usuario u ON u.id_usuario = c.id_usuario;

CREATE OR REPLACE VIEW vw_faturamento_mensal AS
SELECT
  m.id_comerciante,
  m.nome_fantasia,
  date_trunc('month', t.criado_em)::date AS mes,
  SUM(CASE WHEN t.status='confirmed' THEN t.valor_cents ELSE 0 END) AS total_cents,
  COUNT(*) FILTER (WHERE t.status='confirmed') AS qtde
FROM tb_transacao t
JOIN tb_comerciante m ON m.id_comerciante = t.id_comerciante
WHERE t.tipo='payment'
GROUP BY m.id_comerciante, m.nome_fantasia, date_trunc('month', t.criado_em);

CREATE OR REPLACE VIEW vw_emprestimos_em_atraso AS
SELECT e.*, c.id_usuario
FROM tb_emprestimo e
JOIN tb_conta c ON c.id_conta = e.id_conta
WHERE EXISTS (
  SELECT 1 FROM tb_parcela p
  WHERE p.id_emprestimo = e.id_emprestimo
    AND p.pago = FALSE
    AND p.vencimento < CURRENT_DATE
);

-- Triggers & Functions
CREATE OR REPLACE FUNCTION fn_auditoria() RETURNS trigger AS $$
BEGIN
  IF (TG_OP = 'INSERT') THEN
    INSERT INTO tb_auditoria (tabela, operacao, id_registro, dados_depois)
    VALUES (TG_TABLE_NAME, TG_OP, NEW::text, to_jsonb(NEW));
    RETURN NEW;
  ELSIF (TG_OP = 'UPDATE') THEN
    INSERT INTO tb_auditoria (tabela, operacao, id_registro, dados_antes, dados_depois)
    VALUES (TG_TABLE_NAME, TG_OP, NEW::text, to_jsonb(OLD), to_jsonb(NEW));
    RETURN NEW;
  ELSE
    INSERT INTO tb_auditoria (tabela, operacao, id_registro, dados_antes)
    VALUES (TG_TABLE_NAME, TG_OP, OLD::text, to_jsonb(OLD));
    RETURN OLD;
  END IF;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_transacao ON tb_transacao;
CREATE TRIGGER trg_audit_transacao
AFTER INSERT OR UPDATE OR DELETE ON tb_transacao
FOR EACH ROW EXECUTE FUNCTION fn_auditoria();

DROP TRIGGER IF EXISTS trg_audit_emprestimo ON tb_emprestimo;
CREATE TRIGGER trg_audit_emprestimo
AFTER INSERT OR UPDATE OR DELETE ON tb_emprestimo
FOR EACH ROW EXECUTE FUNCTION fn_auditoria();

CREATE OR REPLACE FUNCTION fn_valida_saldo() RETURNS trigger AS $$
DECLARE
  saldo_atual BIGINT;
BEGIN
  IF NEW.tipo IN ('withdrawal','transfer','payment','fee', 'loan_repayment') AND NEW.status = 'confirmed' THEN
    IF NEW.id_conta_de IS NULL THEN
      RAISE EXCEPTION 'Transação requer conta de origem';
    END IF;
    SELECT saldo_cents INTO saldo_atual FROM tb_conta WHERE id_conta = NEW.id_conta_de FOR UPDATE;
    IF saldo_atual < NEW.valor_cents THEN
      RAISE EXCEPTION 'Saldo insuficiente (conta %, saldo %, valor %)', NEW.id_conta_de, saldo_atual, NEW.valor_cents;
    END IF;
    UPDATE tb_conta SET saldo_cents = saldo_cents - NEW.valor_cents WHERE id_conta = NEW.id_conta_de;
    IF NEW.id_conta_para IS NOT NULL THEN
      UPDATE tb_conta SET saldo_cents = saldo_cents + NEW.valor_cents WHERE id_conta = NEW.id_conta_para;
    END IF;
  ELSIF NEW.tipo IN ('deposit','loan_disbursement') AND NEW.status='confirmed' THEN
    IF NEW.id_conta_para IS NULL THEN
      RAISE EXCEPTION 'Transação de crédito requer conta de destino';
    END IF;
    UPDATE tb_conta SET saldo_cents = saldo_cents + NEW.valor_cents WHERE id_conta = NEW.id_conta_para;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_valida_saldo ON tb_transacao;
CREATE TRIGGER trg_valida_saldo
AFTER INSERT ON tb_transacao
FOR EACH ROW EXECUTE FUNCTION fn_valida_saldo();

CREATE OR REPLACE FUNCTION fn_atualiza_status_emprestimo() RETURNS trigger AS $$
DECLARE
  qtd_restantes INT;
BEGIN
  SELECT COUNT(*) INTO qtd_restantes FROM tb_parcela WHERE id_emprestimo = NEW.id_emprestimo AND pago = FALSE;
  UPDATE tb_emprestimo
    SET status = CASE WHEN qtd_restantes = 0 THEN 'paid'
                      WHEN EXISTS (SELECT 1 FROM tb_parcela WHERE id_emprestimo = NEW.id_emprestimo AND pago = FALSE AND vencimento < CURRENT_DATE) THEN 'in_arrears'
                      ELSE status END
  WHERE id_emprestimo = NEW.id_emprestimo;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_status_parcela ON tb_parcela;
CREATE TRIGGER trg_status_parcela
AFTER UPDATE OF pago ON tb_parcela
FOR EACH ROW EXECUTE FUNCTION fn_atualiza_status_emprestimo();

CREATE OR REPLACE FUNCTION fn_pmt(principal BIGINT, juros_aa NUMERIC, meses INT)
RETURNS BIGINT AS $$
DECLARE
  j_m NUMERIC := (power(1 + juros_aa/100, 1.0/12) - 1);
  pmt NUMERIC;
BEGIN
  IF meses <= 0 THEN RAISE EXCEPTION 'Meses inválidos'; END IF;
  IF j_m = 0 THEN
    pmt := principal / meses;
  ELSE
    pmt := principal * (j_m * power(1+j_m, meses)) / (power(1+j_m, meses) - 1);
  END IF;
  RETURN round(pmt);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

CREATE OR REPLACE PROCEDURE sp_conceder_emprestimo(p_id_emprestimo BIGINT)
LANGUAGE plpgsql
AS $$
DECLARE
  v_conta BIGINT;
  v_principal BIGINT;
  v_juros NUMERIC;
  v_prazo INT;
  v_valor_parcela BIGINT;
  i INT;
BEGIN
  SELECT id_conta, principal_cents, juros_aa_pct, prazo_meses
    INTO v_conta, v_principal, v_juros, v_prazo
  FROM tb_emprestimo WHERE id_emprestimo = p_id_emprestimo FOR UPDATE;

  IF NOT FOUND THEN RAISE EXCEPTION 'Empréstimo % não encontrado', p_id_emprestimo; END IF;

  v_valor_parcela := fn_pmt(v_principal, v_juros, v_prazo);

  UPDATE tb_emprestimo SET status='disbursed', iniciado_em = CURRENT_DATE WHERE id_emprestimo = p_id_emprestimo;

  DELETE FROM tb_parcela WHERE id_emprestimo = p_id_emprestimo;
  FOR i IN 1..v_prazo LOOP
    INSERT INTO tb_parcela (id_emprestimo, num_parcela, vencimento, valor_cents)
    VALUES (p_id_emprestimo, i, (CURRENT_DATE + make_interval(months=>i))::date, v_valor_parcela);
  END LOOP;

  INSERT INTO tb_transacao (id_conta_para, tipo, valor_cents, status, referencia)
  VALUES (v_conta, 'loan_disbursement', v_principal, 'confirmed', 'EMPR-'||p_id_emprestimo);
END;
$$;

CREATE OR REPLACE PROCEDURE sp_pagar_parcela(p_id_parcela BIGINT, p_id_conta BIGINT)
LANGUAGE plpgsql
AS $$
DECLARE
  v_valor BIGINT;
  v_emp BIGINT;
BEGIN
  SELECT valor_cents, id_emprestimo INTO v_valor, v_emp
  FROM tb_parcela WHERE id_parcela = p_id_parcela FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Parcela não encontrada'; END IF;

  INSERT INTO tb_transacao (id_conta_de, id_conta_para, tipo, valor_cents, status, referencia)
  VALUES (p_id_conta, (SELECT id_conta FROM tb_emprestimo WHERE id_emprestimo=v_emp), 'loan_repayment', v_valor, 'confirmed', 'PARC-'||p_id_parcela);

  UPDATE tb_parcela SET pago = TRUE, pago_em = now() WHERE id_parcela = p_id_parcela;
END;
$$;

CREATE OR REPLACE PROCEDURE sp_quitar_emprestimo(p_id_emprestimo BIGINT, p_id_conta_pagadora BIGINT)
LANGUAGE plpgsql
AS $$
DECLARE
  v_valor_total BIGINT;
  v_conta_credora BIGINT;
BEGIN
  SELECT e.id_conta, COALESCE(SUM(p.valor_cents), 0)
    INTO v_conta_credora, v_valor_total
  FROM tb_emprestimo e
  LEFT JOIN tb_parcela p ON e.id_emprestimo = p.id_emprestimo AND p.pago = FALSE
  WHERE e.id_emprestimo = p_id_emprestimo
  GROUP BY e.id_conta;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Empréstimo % não encontrado.', p_id_emprestimo;
  END IF;

  IF v_valor_total = 0 THEN
    RAISE EXCEPTION 'Empréstimo % já quitado ou não possui parcelas pendentes.', p_id_emprestimo;
  END IF;

  INSERT INTO tb_transacao (id_conta_de, id_conta_para, tipo, valor_cents, status, referencia)
  VALUES (p_id_conta_pagadora, v_conta_credora, 'loan_repayment', v_valor_total, 'confirmed', 'QUITAR-EMP-'||p_id_emprestimo);

  UPDATE tb_parcela SET pago = TRUE, pago_em = now()
  WHERE id_emprestimo = p_id_emprestimo AND pago = FALSE;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_conta_usuario ON tb_conta(id_usuario, numero_conta);

ANALYZE;

-- Segurança
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='finpay_admin') THEN
    CREATE ROLE finpay_admin LOGIN PASSWORD 'admin123';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='finpay_operador') THEN
    CREATE ROLE finpay_operador LOGIN PASSWORD 'oper123';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='finpay_auditor') THEN
    CREATE ROLE finpay_auditor LOGIN PASSWORD 'audit123';
  END IF;
END$$;

GRANT CONNECT ON DATABASE finpay TO finpay_admin, finpay_operador, finpay_auditor;
GRANT USAGE ON SCHEMA public TO finpay_admin, finpay_operador, finpay_auditor;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO finpay_admin;
GRANT SELECT, INSERT ON tb_transacao, tb_emprestimo, tb_parcela, tb_conta TO finpay_operador;
REVOKE UPDATE, DELETE ON tb_auditoria FROM finpay_operador;
GRANT SELECT ON tb_auditoria, vw_faturamento_mensal, vw_contas_saldo TO finpay_auditor;