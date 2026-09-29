-- Grup tujuan pengingat. Hanya satu baris.
create table if not exists pengingat_tujuan (
    id smallint primary key default 1 check (id = 1),
    chat_id bigint not null,
    updated_at timestamptz not null default now()
);

-- Satu status per bulan iuran: terkirim atau skip.
create table if not exists pengingat (
    bulan text primary key,
    status text not null,
    message_id bigint,
    updated_at timestamptz not null default now()
);

alter table pengingat_tujuan enable row level security;
alter table pengingat enable row level security;
