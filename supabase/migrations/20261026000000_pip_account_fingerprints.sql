-- Keep masked display IDs while allowing distinct IBKR accounts that share
-- the same final four digits to be persisted and linked to their positions.

ALTER TABLE public.ibkr_accounts
    ADD COLUMN IF NOT EXISTS account_fingerprint TEXT;

UPDATE public.ibkr_accounts
SET account_fingerprint =
    md5('legacy:' || id::TEXT || ':' || portfolio_id::TEXT)
    || md5('legacy:' || portfolio_id::TEXT || ':' || id::TEXT)
WHERE account_fingerprint IS NULL;

ALTER TABLE public.ibkr_accounts
    ALTER COLUMN account_fingerprint SET NOT NULL;

ALTER TABLE public.ibkr_accounts
    DROP CONSTRAINT IF EXISTS ibkr_accounts_portfolio_masked_id_key;

ALTER TABLE public.ibkr_accounts
    DROP CONSTRAINT IF EXISTS ibkr_accounts_account_fingerprint_check;

ALTER TABLE public.ibkr_accounts
    ADD CONSTRAINT ibkr_accounts_account_fingerprint_check
    CHECK (account_fingerprint ~ '^[0-9a-f]{64}$');

CREATE UNIQUE INDEX IF NOT EXISTS idx_ibkr_accounts_portfolio_fingerprint
    ON public.ibkr_accounts(portfolio_id, account_fingerprint);

COMMENT ON COLUMN public.ibkr_accounts.account_fingerprint IS
    'Stable one-way account key used for upserts; never a display ID or credential.';
