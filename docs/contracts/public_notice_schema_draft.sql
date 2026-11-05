-- Draft for the public notice track. Not yet an Alembic migration.
-- This does not model supplier invoices or contract unit prices.

CREATE TABLE public_notices (
    ocid text PRIMARY KEY,
    tender_id text,
    tender_title text,
    source_year integer NOT NULL
);

CREATE TABLE public_awards (
    ocid text NOT NULL REFERENCES public_notices(ocid),
    award_id text NOT NULL,
    amount numeric,
    currency text,
    PRIMARY KEY (ocid, award_id),
    CHECK (amount IS NULL OR amount >= 0),
    CHECK (currency IS NULL OR length(currency) = 3)
);
CREATE TABLE public_award_suppliers (
    ocid text NOT NULL,
    award_id text NOT NULL,
    supplier_id text NOT NULL,
    supplier_name text,
    PRIMARY KEY (ocid, award_id, supplier_id),
    FOREIGN KEY (ocid, award_id)
        REFERENCES public_awards (ocid, award_id)
);


-- Source metadata for public award references. URLs are unverified.
CREATE TABLE public_award_documents (
    ocid text NOT NULL,
    award_id text NOT NULL,
    document_id text NOT NULL CHECK (document_id ~ '[^[:space:]]'),
    url text NOT NULL CHECK (url ~ '[^[:space:]]'),
    document_type text,
    format text,
    PRIMARY KEY (ocid, award_id, document_id),
    CONSTRAINT public_award_documents_award_fk
        FOREIGN KEY (ocid, award_id)
        REFERENCES public_awards (ocid, award_id)
);
