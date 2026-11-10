-- Additive. Apply only to the isolated *_lumi_test database. No existing order is modified.
BEGIN;
DO $$ BEGIN
  IF current_database() !~ '_lumi_test$' THEN RAISE EXCEPTION 'Isolated HML required'; END IF;
END $$;
CREATE TABLE IF NOT EXISTS lumi_payment_attempts (
  token text PRIMARY KEY REFERENCES lumi_orders(token),
  public_data jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
COMMIT;
