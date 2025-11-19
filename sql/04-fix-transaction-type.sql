-- 04-fix-transaction-type.sql — corrige o valor '...posit' para 'deposit' no enum transaction_type

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_type t
    WHERE t.typname = 'transaction_type'
  ) THEN
    IF EXISTS (
      SELECT 1
      FROM pg_enum e
      JOIN pg_type t ON e.enumtypid = t.oid
      WHERE t.typname = 'transaction_type'
        AND e.enumlabel = '...posit'
    ) THEN
      ALTER TYPE transaction_type RENAME VALUE '...posit' TO 'deposit';
    END IF;
  END IF;
END$$;
