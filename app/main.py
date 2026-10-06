import json
import os
import secrets
import traceback
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.flow import handle_update, pembayaran_selesai
from app.pengingat import kirim_pengingat
from app.rules import menu
from app.settings import load_settings
from app.store import Store
from app.tg import Telegram


app = FastAPI()


def chat_dari(update):

    callback = update.get("callback_query") or {}
    message = callback.get("message") or update.get("message") or {}
    chat = message.get("chat") or {}

    return chat.get("id")


async def baca_push(request, raw):

    if request.method == "GET":
        return dict(request.query_params)

    if not raw:
        return {}

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pasangan = parse_qs(raw.decode(errors="replace"))
        return {kunci: nilai[-1] for kunci, nilai in pasangan.items()}


@app.get("/api/health")
async def health():

    return {"success": True, "msg": "Webhook Villa 360 aktif"}


@app.get("/api/cron/pengingat")
async def cron_pengingat(request: Request):

    rahasia = os.getenv("CRON_SECRET") or ""
    header = request.headers.get("authorization", "")
    token = header.removeprefix("Bearer ").strip()

    if (
        not rahasia
        or not header.startswith("Bearer ")
        or len(token) != len(rahasia)
        or not secrets.compare_digest(token, rahasia)
    ):

        return JSONResponse(
            {"success": False, "msg": "forbidden"},
            status_code=401,
        )

    settings = load_settings()
    db = Store(settings.supabase_url, settings.supabase_key)
    tg = Telegram(settings.bot_token)

    try:
        hasil = await kirim_pengingat(db, tg)
    finally:
        await db.close()
        await tg.close()

    print("PENGINGAT:", hasil)

    return {"success": True, "msg": hasil}


def asal_telegram_valid(request):

    # Telegram mengirim secret_token dari setWebhook di header ini.
    # Tanpa pengecekan, siapa pun bisa memalsukan from.id.
    # Env belum diisi = masa transisi: tetap diterima, dengan peringatan.

    rahasia = os.getenv("TELEGRAM_WEBHOOK_SECRET") or ""

    if not rahasia:

        print("PERINGATAN: TELEGRAM_WEBHOOK_SECRET belum diset")

        return True

    token = request.headers.get("x-telegram-bot-api-secret-token", "")

    return secrets.compare_digest(
        token.encode("utf-8"),
        rahasia.encode("utf-8"),
    )


@app.post("/api/telegram")
async def telegram(request: Request):

    if not asal_telegram_valid(request):

        print("TELEGRAM DITOLAK: secret token tidak cocok")

        return JSONResponse({"ok": False}, status_code=401)

    try:
        update = await request.json()
    except Exception:
        return JSONResponse({"ok": False}, status_code=400)

    try:

        settings = load_settings()

        db = Store(settings.supabase_url, settings.supabase_key)
        tg = Telegram(settings.bot_token)

        try:
            await handle_update(update, db, tg)
        finally:
            await db.close()
            await tg.close()

    except Exception as e:

        print("ERROR BOT:", repr(e))
        traceback.print_exception(e)

        chat_id = chat_dari(update)

        if chat_id:

            try:

                settings = load_settings()
                tg = Telegram(settings.bot_token)

                try:
                    await tg.send_message(
                        chat_id,
                        f"❌ Terjadi error:\n{e}\n\nSilakan coba lagi.",
                        reply_markup=menu(),
                    )
                finally:
                    await tg.close()

            except Exception:
                pass

    return {"ok": True}


@app.api_route("/api/qris/push/{secret}", methods=["GET", "POST"])
async def terima_push(secret: str, request: Request):

    try:
        settings = load_settings()
    except RuntimeError as e:
        return JSONResponse(
            {"success": False, "msg": str(e)},
            status_code=500,
        )

    if (
        len(secret) != len(settings.push_secret)
        or not secrets.compare_digest(secret, settings.push_secret)
    ):

        print("PUSH MASUK:", request.method, "/api/qris/push/<SECRET> -> 403")

        return JSONResponse(
            {"success": False, "msg": "forbidden"},
            status_code=403,
        )

    raw = await request.body()

    if request.method == "GET" and not request.query_params:

        print("PUSH MASUK: GET /api/qris/push/<SECRET> -> 200")

        return {
            "success": True,
            "msg": "Server push V360 aktif",
        }

    data = await baca_push(request, raw)

    print("PUSH QRIS:", data)

    trxid = data.get("trxid")

    db = Store(settings.supabase_url, settings.supabase_key)

    try:

        transaksi = await db.get_qris(trxid) if trxid else None

        if not transaksi:

            print("PUSH MASUK:", request.method, "-> 404")

            return JSONResponse(
                {"success": False, "msg": "trxid tidak ditemukan"},
                status_code=404,
            )

        if str(data.get("status", "")).lower() != "success":

            print("PUSH MASUK:", request.method, "-> 200")

            return {"success": True, "msg": "status diabaikan"}

        # Push bisa dikirim ulang; proses hanya sekali
        if transaksi["status"] == "PENDING":

            await db.tandai_lunas(
                trxid,
                data.get("refcode"),
                data.get("channel"),
            )

            try:

                tg = Telegram(settings.bot_token)

                try:
                    await pembayaran_selesai(db, tg, trxid)
                finally:
                    await tg.close()

            except Exception as e:

                # Pembayaran sudah tercatat; jangan sampai
                # provider mengulang push hanya karena Telegram error
                print("ERROR TAMPILAN PUSH:", repr(e))

        print("PUSH MASUK:", request.method, "-> 200")

        return {"success": True}

    finally:
        await db.close()
