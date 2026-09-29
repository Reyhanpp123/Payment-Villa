-- Satu layar bot per orang per chat.
-- Dipakai supaya tombol di grup tidak mengubah sesi orang lain.

create table if not exists sesi (
    chat_id bigint not null,
    user_id bigint not null,
    message_id bigint,
    updated_at timestamptz not null default now(),
    primary key (chat_id, user_id)
);

alter table sesi enable row level security;
