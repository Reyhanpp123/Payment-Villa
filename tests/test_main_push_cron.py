import pytest
from fastapi.testclient import TestClient

import app.main as main


class DbPalsu:

    def __init__(self, transaksi=None):

        self.transaksi = transaksi
        self.lunas_dipanggil = []

    async def get_qris(self, trxid):

        return self.transaksi

    async def tandai_lunas(self, trxid, refcode=None, channel=None):

        self.lunas_dipanggil.append((trxid, refcode, channel))

        return True, "PEMBAYARAN BERHASIL"

    async def close(self):

        pass


class TelegramPalsu:

    def __init__(self, *args):

        pass

    async def close(self):

        pass


@pytest.fixture
def pasang(monkeypatch):

    selesai = []

    async def pembayaran_selesai_palsu(db, tg, trxid, *args, **kwargs):
        selesai.append(trxid)

    def _pasang(transaksi=None):

        db = DbPalsu(transaksi)
        monkeypatch.setattr(main, "Store", lambda *a: db)
        monkeypatch.setattr(main, "Telegram", TelegramPalsu)
        monkeypatch.setattr(
            main, "pembayaran_selesai", pembayaran_selesai_palsu
        )

        return TestClient(main.app), db, selesai

    return _pasang


PUSH = "/api/qris/push/rahasia-push-tes"


def test_push_secret_salah_ditolak(pasang):

    client, db, _ = pasang()

    assert client.post(
        "/api/qris/push/salah", json={"trxid": "X"}
    ).status_code == 403


def test_push_get_tanpa_query_hanya_cek_hidup(pasang):

    client, _, _ = pasang()

    hasil = client.get(PUSH)

    assert hasil.status_code == 200
    assert hasil.json()["success"] is True


def test_push_trxid_tidak_dikenal_404(pasang):

    client, _, _ = pasang(transaksi=None)

    assert client.post(
        PUSH, json={"trxid": "X", "status": "success"}
    ).status_code == 404


def test_push_status_bukan_success_diabaikan(pasang):

    client, db, selesai = pasang({"status": "PENDING"})

    hasil = client.post(PUSH, json={"trxid": "X", "status": "failed"})

    assert hasil.status_code == 200
    assert db.lunas_dipanggil == []
    assert selesai == []


def test_push_success_memproses_pending_sekali(pasang):

    client, db, selesai = pasang({"status": "PENDING"})

    hasil = client.post(
        PUSH,
        json={
            "trxid": "202610BENOY",
            "status": "success",
            "refcode": "R1",
            "channel": "QRIS",
        },
    )

    assert hasil.status_code == 200
    assert db.lunas_dipanggil == [("202610BENOY", "R1", "QRIS")]
    assert selesai == ["202610BENOY"]


@pytest.mark.parametrize("status", ["SUCCESS", "DIGANTI"])
def test_push_untuk_status_lain_tidak_memproses_ulang(pasang, status):

    client, db, selesai = pasang({"status": status})

    hasil = client.post(
        PUSH, json={"trxid": "202610BENOY", "status": "success"}
    )

    assert hasil.status_code == 200
    assert db.lunas_dipanggil == []
    assert selesai == []


def test_push_form_encoded_dibaca(pasang):

    client, db, _ = pasang({"status": "PENDING"})

    client.post(
        PUSH,
        content="trxid=202610BENOY&status=success",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert db.lunas_dipanggil[0][0] == "202610BENOY"


def test_cron_tanpa_atau_dengan_token_salah_401(pasang):

    client, _, _ = pasang()

    assert client.get("/api/cron/pengingat").status_code == 401
    assert client.get(
        "/api/cron/pengingat",
        headers={"authorization": "Bearer salah"},
    ).status_code == 401


def test_cron_tanpa_cron_secret_selalu_401(pasang, monkeypatch):

    client, _, _ = pasang()
    monkeypatch.delenv("CRON_SECRET")

    assert client.get(
        "/api/cron/pengingat",
        headers={"authorization": "Bearer "},
    ).status_code == 401


def test_cron_token_benar_menjalankan_pengingat(pasang, monkeypatch):

    client, _, _ = pasang()

    async def pengingat_palsu(db, tg):
        return "terkirim"

    monkeypatch.setattr(main, "kirim_pengingat", pengingat_palsu)

    hasil = client.get(
        "/api/cron/pengingat",
        headers={"authorization": "Bearer rahasia-cron-tes"},
    )

    assert hasil.status_code == 200
    assert hasil.json() == {"success": True, "msg": "terkirim"}
