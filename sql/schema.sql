-- Docker-friendly schema (no DROP/CREATE DATABASE here)
-- Run inside the already-created database 'finpay'

-- ============== TIPOS E DOMÍNIOS =========================
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'account_status') THEN
    CREATE TYPE account_status AS ENUM ('active','blocked','closed');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'transaction_type') THEN
    CREATE TYPE transaction_type AS ENUM ('payment','transfer','deposit','withdrawal','loan_disbursement','loan_repayment','fee');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'transaction_status') THEN
    CREATE TYPE transaction_status AS ENUM ('pending','confirmed','failed','reversed');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'loan_status') THEN
    CREATE TYPE loan_status AS ENUM ('draft','approved','disbursed','in_arrears','paid','cancelled');
  END IF;
END$$;

-- ================== TABELAS PRINCIPAIS ====================
CREATE TABLE IF NOT EXISTS tb_usuario (
  id_usuario        BIGSERIAL PRIMARY KEY,
  nome              VARCHAR(120) NOT NULL,
  email             VARCHAR(120) NOT NULL UNIQUE,
  telefone          VARCHAR(20),
  doc_cpf_cnpj      VARCHAR(20) NOT NULL UNIQUE,
  criado_em         TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tb_endereco (
  id_endereco       BIGSERIAL PRIMARY KEY,
  id_usuario        BIGINT NOT NULL REFERENCES tb_usuario(id_usuario) ON DELETE CASCADE,
  logradouro        VARCHAR(120) NOT NULL,
  numero            VARCHAR(20),
  complemento       VARCHAR(60),
  bairro            VARCHAR(60),
  cidade            VARCHAR(60),
  estado            VARCHAR(2),
  cep               VARCHAR(12),
  criado_em         TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tb_conta (
  id_conta          BIGSERIAL PRIMARY KEY,
  id_usuario        BIGINT NOT NULL REFERENCES tb_usuario(id_usuario) ON DELETE RESTRICT,
  numero_conta      VARCHAR(20) NOT NULL UNIQUE,
  agencia           VARCHAR(10) NOT NULL,
  saldo_cents       BIGINT NOT NULL DEFAULT 0,
  status            account_status NOT NULL DEFAULT 'active',
  criado_em         TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tb_comerciante (
  id_comerciante    BIGSERIAL PRIMARY KEY,
  nome_fantasia     VARCHAR(120) NOT NULL,
  cnpj              VARCHAR(20) NOT NULL UNIQUE,
  mcc               VARCHAR(8),
  criado_em         TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tb_transacao (
  id_transacao      BIGSERIAL PRIMARY KEY,
  id_conta_de       BIGINT REFERENCES tb_conta(id_conta),
  id_conta_para     BIGINT REFERENCES tb_conta(id_conta),
  id_comerciante    BIGINT REFERENCES tb_comerciante(id_comerciante),
  tipo              transaction_type NOT NULL,
  valor_cents       BIGINT NOT NULL CHECK (valor_cents >= 0),
  status            transaction_status NOT NULL DEFAULT 'pending',
  referencia        VARCHAR(60),
  criado_em         TIMESTAMP NOT NULL DEFAULT now(),
  confirmado_em     TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tb_emprestimo (
  id_emprestimo     BIGSERIAL PRIMARY KEY,
  id_conta          BIGINT NOT NULL REFERENCES tb_conta(id_conta) ON DELETE RESTRICT,
  principal_cents   BIGINT NOT NULL CHECK (principal_cents > 0),
  juros_aa_pct      NUMERIC(6,3) NOT NULL CHECK (juros_aa_pct >= 0),
  prazo_meses       INT NOT NULL CHECK (prazo_meses > 0 AND prazo_meses <= 60),
  status            loan_status NOT NULL DEFAULT 'draft',
  iniciado_em       DATE NOT NULL DEFAULT CURRENT_DATE,
  criado_em         TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tb_parcela (
  id_parcela        BIGSERIAL PRIMARY KEY,
  id_emprestimo     BIGINT NOT NULL REFERENCES tb_emprestimo(id_emprestimo) ON DELETE CASCADE,
  num_parcela       INT NOT NULL,
  vencimento        DATE NOT NULL,
  valor_cents       BIGINT NOT NULL CHECK (valor_cents >= 0),
  pago              BOOLEAN NOT NULL DEFAULT FALSE,
  pago_em           TIMESTAMP,
  UNIQUE (id_emprestimo, num_parcela)
);

-- =============== AUDITORIA ================================
CREATE TABLE IF NOT EXISTS tb_auditoria (
  id_auditoria      BIGSERIAL PRIMARY KEY,
  tabela            TEXT NOT NULL,
  operacao          TEXT NOT NULL,
  id_registro       TEXT,
  usuario_bd        TEXT DEFAULT CURRENT_USER,
  momento           TIMESTAMP NOT NULL DEFAULT now(),
  dados_antes       JSONB,
  dados_depois      JSONB
);

-- ================== ÍNDICES INICIAIS =====================
CREATE INDEX IF NOT EXISTS idx_transacao_status ON tb_transacao(status);
CREATE INDEX IF NOT EXISTS idx_transacao_tipo_data ON tb_transacao (tipo, criado_em);
