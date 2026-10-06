from pathlib import Path

import httpx
import pytest

import app.flow as flow
from app.tg import Telegram


class DbPalsu:

    def __init__(self, nama):

        self.row = {
            "trxid": "202610TES",
            "nama": nama,
            "bulan": "Oktober",
            "nominal": 300000,
            "transaction_id": "TX1",
            "paid_at": "2026-10-06 10:00:00",
            "channel": "QRIS",
            "refcode": "R1",
            "chat_id": -100,
            "message_id": 5,
        }

    async def get_qris(self, trxid):

        return self.row

    async def semua_pembayaran(self):

        return []

    async def simpan_sesi(self, *args):

        pass

    async def pindah_sesi(self, *args):

        pass


class TgPalsu:

    def __init__(self, gagal_animasi=False):

        self.panggilan = []
        self.gagal_animasi = gagal_animasi

    async def delete_message(self, chat_id, message_id):

        self.panggilan.append("hapus")

        return True

    async def edit_caption(self, *args):

        self.panggilan.append("edit_caption")

    async def edit_text(self, *args):

        self.panggilan.append("edit_text")

    async def send_animation(self, chat_id, animasi, *args, **kwargs):

        self.panggilan.append("animasi")
        self.animasi = (chat_id, animasi)

        if self.gagal_animasi:
            raise RuntimeError("Telegram menolak")

    async def send_message(self, chat_id, teks, *args, **kwargs):

        self.panggilan.append("pesan")
        self.teks = teks

        return {"message_id": 99}


async def test_peri_dapat_gif_sebelum_pesan_lunas():

    tg = TgPalsu()

    await flow.pembayaran_selesai(DbPalsu("Peri"), tg, "202610TES")

    assert tg.panggilan == ["hapus", "animasi", "pesan"]
    assert tg.animasi[0] == -100
    assert tg.animasi[1].startswith(b"GIF8")
    assert "LUNAS" in tg.teks


async def test_anggota_lain_tidak_dapat_gif():

    tg = TgPalsu()

    await flow.pembayaran_selesai(DbPalsu("Benoy"), tg, "202610TES")

    assert "animasi" not in tg.panggilan
    assert tg.panggilan[-1] == "pesan"


async def test_peri_dari_layar_teks_gif_ke_chat_itu_dan_layar_tetap_diganti():

    tg = TgPalsu()
    db = DbPalsu("Peri")
    db.row["message_id"] = None
    db.row["chat_id"] = None
    message = {"chat": {"id": 777}, "message_id": 8}

    await flow.pembayaran_selesai(db, tg, "202610TES", message)

    assert tg.animasi[0] == 777
    assert tg.panggilan == ["animasi", "edit_text"]


async def test_gagal_kirim_gif_tidak_menggagalkan_pembayaran():

    tg = TgPalsu(gagal_animasi=True)

    await flow.pembayaran_selesai(DbPalsu("Peri"), tg, "202610TES")

    assert tg.panggilan[-1] == "pesan"


async def test_file_gif_hilang_tidak_menggagalkan_pembayaran(monkeypatch):

    tg = TgPalsu()
    monkeypatch.setattr(flow, "GIF_LUNAS_PATH", Path("tidak-ada.gif"))

    await flow.pembayaran_selesai(DbPalsu("Peri"), tg, "202610TES")

    assert "animasi" not in tg.panggilan
    assert tg.panggilan[-1] == "pesan"


async def test_telegram_send_animation_kirim_multipart_ke_send_animation():

    terekam = {}

    def handler(request):

        terekam["path"] = request.url.path
        terekam["isi"] = request.content

        return httpx.Response(
            200, json={"ok": True, "result": {"message_id": 1}}
        )

    tg = Telegram("token")
    tg.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    await tg.send_animation(-100, b"GIF89a-isi", "judul")

    assert terekam["path"].endswith("/sendAnimation")
    assert b"GIF89a-isi" in terekam["isi"]
    assert b'name="chat_id"' in terekam["isi"]
    assert b"-100" in terekam["isi"]


async def test_telegram_send_animation_error_naik_runtime_error():

    tg = Telegram("token")
    tg.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                400, json={"ok": False, "description": "bad"}
            )
        )
    )

    with pytest.raises(RuntimeError):
        await tg.send_animation(-100, b"GIF89a", "judul")
