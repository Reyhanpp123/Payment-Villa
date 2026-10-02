-- Batas spam tombol Tagih per user Telegram.
create table if not exists tagih_batas (
    user_id bigint primary key,
    last_tagih_at timestamptz,
    suspended_until timestamptz,
    alert_ditampilkan boolean not null default false,
    updated_at timestamptz not null default now()
);

alter table tagih_batas enable row level security;
