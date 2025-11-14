
-- 03-migrations.sql — adicionar senha_hash e salario_mensal_cents
-- Executado na criação inicial (ou aplique manualmente se já existir).

-- senha_hash no usuário (texto para hash bcrypt)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='tb_usuario' AND column_name='senha_hash'
  ) THEN
    ALTER TABLE tb_usuario ADD COLUMN senha_hash TEXT NOT NULL DEFAULT '';
  END IF;
END$$;

-- Salário mensal na conta
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='tb_conta' AND column_name='salario_mensal_cents'
  ) THEN
    ALTER TABLE tb_conta ADD COLUMN salario_mensal_cents BIGINT NOT NULL DEFAULT 0;
  END IF;
END$$;

-- View utilitária para achar conta por usuário
CREATE OR REPLACE VIEW vw_conta_por_usuario AS
SELECT u.id_usuario, c.id_conta, c.saldo_cents, c.salario_mensal_cents, c.status, c.numero_conta
FROM tb_usuario u
JOIN tb_conta c ON c.id_usuario = u.id_usuario;
