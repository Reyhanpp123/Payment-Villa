import pytest


@pytest.fixture(autouse=True)
def env_bersih(monkeypatch):

    # .env asli ikut terbaca saat import; tes tidak boleh memakainya.
    monkeypatch.setenv("BOT_TOKEN", "token-tes")
    monkeypatch.setenv("PUSH_SECRET", "rahasia-push-tes")
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.tes")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "kunci-tes")
    monkeypatch.setenv("CRON_SECRET", "rahasia-cron-tes")
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
