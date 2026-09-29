import os

from dotenv import load_dotenv


load_dotenv()


class Settings:

    def __init__(self, bot_token, push_secret, supabase_url, supabase_key):

        self.bot_token = bot_token
        self.push_secret = push_secret
        self.supabase_url = supabase_url.rstrip("/")
        self.supabase_key = supabase_key


def load_settings():

    nilai = {
        "BOT_TOKEN": os.getenv("BOT_TOKEN"),
        "PUSH_SECRET": os.getenv("PUSH_SECRET"),
        "SUPABASE_URL": os.getenv("SUPABASE_URL"),
        "SUPABASE_SECRET_KEY": os.getenv("SUPABASE_SECRET_KEY"),
    }

    kosong = [nama for nama, isi in nilai.items() if not isi]

    if kosong:
        raise RuntimeError(
            "Variabel ini belum diset: " + ", ".join(kosong)
        )

    return Settings(
        nilai["BOT_TOKEN"],
        nilai["PUSH_SECRET"],
        nilai["SUPABASE_URL"],
        nilai["SUPABASE_SECRET_KEY"],
    )
