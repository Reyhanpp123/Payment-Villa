import json

import httpx
import pytest

from app.store import Store


class SupabasePalsu:

    # Meniru PostgREST seperlunya dan merekam semua tulisan.

    def __init__(self, transaksi, sudah_lunas=False, kode_insert=201):

        self.transaksi = transaksi
        self.sudah_lunas = sudah_lunas
        self.kode_insert = kode_insert
        self.tulis = []

    def __call__(self, request):

        tabel = request.url.path.rsplit("/", 1)[-1]

        if request.method == "GET" and tabel == "qris_transactions":
            return httpx.Response(
                200, json=[self.transaksi] if self.transaksi else []
            )

        if request.method == "GET" and tabel == "pembayaran":
            return httpx.Response(
                200, json=[{"id": 1}] if self.sudah_lunas else []
            )

        body = json.loads(request.content) if request.content else None
        self.tulis.append((request.method, tabel, body))

        if request.method == "POST" and tabel == "pembayaran":
            return httpx.Response(self.kode_insert, text="")

        return httpx.Response(200, json=[])


def buat_store(palsu):

    db = Store("https://supabase.tes", "kunci")
    db.client = httpx.AsyncClient(transport=httpx.MockTransport(palsu))

    return db


def baris(status):

    return {
        "trxid": "202610BENOY",
        "nama": "Benoy",
        "bulan": "Oktober",
        "nominal": 300000,
        "status": status,
    }


async def test_pending_dicatat_lalu_ditandai_sukses():

    palsu = SupabasePalsu(baris("PENDING"))
    db = buat_store(palsu)

    hasil = await db.tandai_lunas("202610BENOY", "ref", "QRIS")

    assert hasil == (True, "PEMBAYARAN BERHASIL")
    assert [t[:2] for t in palsu.tulis] == [
        ("POST", "pembayaran"),
        ("PATCH", "qris_transactions"),
    ]
    assert palsu.tulis[0][2] == {
        "nama": "Benoy",
        "bulan": "Oktober",
        "nominal": 300000,
    }
    assert palsu.tulis[1][2]["status"] == "SUCCESS"


async def test_sudah_success_tidak_menulis_apa_pun():

    palsu = SupabasePalsu(baris("SUCCESS"))
    db = buat_store(palsu)

    assert await db.tandai_lunas("202610BENOY") == (True, "SUDAH LUNAS")
    assert palsu.tulis == []


@pytest.mark.parametrize("status", ["DIGANTI", "LAINNYA"])
async def test_status_selain_pending_ditolak(status):

    palsu = SupabasePalsu(baris(status))
    db = buat_store(palsu)

    assert await db.tandai_lunas("202610BENOY") == (
        False,
        "TRANSAKSI TIDAK MENUNGGU",
    )
    assert palsu.tulis == []


async def test_trxid_tidak_ada():

    db = buat_store(SupabasePalsu(None))

    assert await db.tandai_lunas("TIDAKADA") == (
        False,
        "TRANSAKSI TIDAK DITEMUKAN",
    )


async def test_kas_sudah_ada_tidak_ditulis_ulang_tapi_status_tetap_sukses():

    palsu = SupabasePalsu(baris("PENDING"), sudah_lunas=True)
    db = buat_store(palsu)

    assert await db.tandai_lunas("202610BENOY") == (True, "SUDAH LUNAS")
    assert [t[:2] for t in palsu.tulis] == [("PATCH", "qris_transactions")]


async def test_konflik_409_dianggap_sudah_lunas():

    palsu = SupabasePalsu(baris("PENDING"), kode_insert=409)
    db = buat_store(palsu)

    assert await db.tandai_lunas("202610BENOY") == (True, "SUDAH LUNAS")
    assert palsu.tulis[-1][2]["status"] == "SUCCESS"


async def test_error_supabase_naik_sebagai_runtime_error():

    palsu = SupabasePalsu(baris("PENDING"), kode_insert=500)
    db = buat_store(palsu)

    with pytest.raises(RuntimeError):
        await db.tandai_lunas("202610BENOY")
