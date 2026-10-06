import pytest
from fastapi.testclient import TestClient

import app.main as main

HEADER = "X-Telegram-Bot-Api-Secret-Token"

# Update palsu: seolah-olah dikirim pemilik reset.
UPDATE_RESET = {
    "update_id": 1,
    "message": {
        "message_id": 1,
        "chat": {"id": 10, "type": "private"},
        "from": {"id": 1724220561, "first_name": "Peri"},
        "text": "/resetsemuadataanjing",
    },
}


class Palsu:

    def __init__(self, *args):

        pass

    async def close(self):

        pass


@pytest.fixture
def klien(monkeypatch):

    diproses = []

    async def handle_update_palsu(update, db, tg):
        diproses.append(update)

    monkeypatch.setattr(main, "Store", Palsu)
    monkeypatch.setattr(main, "Telegram", Palsu)
    monkeypatch.setattr(main, "handle_update", handle_update_palsu)

    return TestClient(main.app), diproses


def test_dengan_secret_terpasang_tanpa_header_ditolak(klien, monkeypatch):

    client, diproses = klien
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "rahasia-webhook")

    hasil = client.post("/api/telegram", json=UPDATE_RESET)

    assert hasil.status_code == 401
    assert diproses == []


def test_dengan_secret_terpasang_header_salah_ditolak(klien, monkeypatch):

    client, diproses = klien
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "rahasia-webhook")

    hasil = client.post(
        "/api/telegram",
        json=UPDATE_RESET,
        headers={HEADER: "salah"},
    )

    assert hasil.status_code == 401
    assert diproses == []


def test_header_beda_panjang_ditolak_tanpa_error(klien, monkeypatch):

    client, diproses = klien
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "rahasia-webhook")

    hasil = client.post(
        "/api/telegram",
        json=UPDATE_RESET,
        headers={HEADER: "rahasia-webhook-lebih-panjang"},
    )

    assert hasil.status_code == 401
    assert diproses == []


def test_header_benar_diproses(klien, monkeypatch):

    client, diproses = klien
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "rahasia-webhook")

    hasil = client.post(
        "/api/telegram",
        json=UPDATE_RESET,
        headers={HEADER: "rahasia-webhook"},
    )

    assert hasil.status_code == 200
    assert diproses == [UPDATE_RESET]


def test_tanpa_secret_terpasang_tetap_diterima_masa_transisi(klien):

    client, diproses = klien

    hasil = client.post("/api/telegram", json=UPDATE_RESET)

    assert hasil.status_code == 200
    assert diproses == [UPDATE_RESET]


def test_secret_salah_ditolak_sebelum_body_dibaca(klien, monkeypatch):

    client, diproses = klien
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "rahasia-webhook")

    hasil = client.post(
        "/api/telegram",
        content="bukan json",
        headers={HEADER: "salah"},
    )

    assert hasil.status_code == 401
    assert diproses == []
