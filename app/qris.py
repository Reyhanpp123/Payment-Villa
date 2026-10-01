import base64

import httpx

from app.rules import (
    IURAN,
    PERIODE,
    QRIS_URL,
    sekarang,
    teks_transaksi,
    trxid_acak,
)


async def generate_qris(db, nama, bulan, trxid=None):

    # Provider menolak trxid yang pernah dipakai, meski sudah
    # dihapus dari database lokal (misalnya setelah reset).
    # Kalau gagal, buat ID acak lain sampai diterima.

    dipakai = set()
    kandidat = trxid or trxid_acak(bulan, dipakai)
    terakhir = None

    for _ in range(20):

        try:
            return await _buat_qris(db, nama, bulan, kandidat)
        except RuntimeError as e:

            if "generating qr content" not in str(e).lower():
                raise

            terakhir = e
            dipakai.add(kandidat)
            kandidat = trxid_acak(bulan, dipakai)

            print("QRIS TRXID DITOLAK, COBA:", kandidat)

    raise terakhir or RuntimeError("QRIS gagal dibuat")


async def _buat_qris(db, nama, bulan, trxid):

    payload = {
        "judul": f"Payment {nama} V360",
        "keterangan": f"{bulan} {PERIODE[bulan][0]}",
        "trxid": trxid,
    }

    async with httpx.AsyncClient(timeout=30) as client:

        response = await client.post(QRIS_URL, json=payload)

        response.raise_for_status()

        result = response.json()

    if not result.get("success"):

        print("QRIS REQUEST :", payload)
        print("QRIS HTTP    :", response.status_code)
        print("QRIS RESPONSE:", result)

        raise RuntimeError(
            result.get("msg", "QRIS gagal dibuat")
        )

    data = result.get("data")

    if not data:
        raise RuntimeError("Response QRIS tidak mempunyai data")

    transaction_id = data.get("transactionId")
    amount = data.get("amount")
    qr_content = data.get("qrContent")

    if not transaction_id:
        raise RuntimeError("transactionId tidak ditemukan")

    if not qr_content:
        raise RuntimeError("qrContent tidak ditemukan")

    if "," in qr_content:
        base64_data = qr_content.split(",", 1)[1]
    else:
        base64_data = qr_content

    try:
        qr_bytes = base64.b64decode(base64_data)
    except Exception as e:
        raise RuntimeError(f"QRIS base64 rusak: {e}") from e

    # Ambil foto QR lama sebelum barisnya ditimpa.
    lama = await db.get_qris(trxid)
    qr_lama = (
        (lama.get("chat_id"), lama.get("message_id"))
        if lama
        else (None, None)
    )

    nominal = amount or IURAN

    await db.simpan_pending(
        trxid,
        transaction_id,
        nama,
        bulan,
        nominal,
    )

    return {
        "trxid": trxid,
        "transaction_id": transaction_id,
        "amount": nominal,
        "created_at": sekarang().strftime("%d-%m-%Y %H:%M:%S"),
        "qr_bytes": qr_bytes,
        "qr_lama": qr_lama,
    }


def caption_qris(nama, bulan, qris, judul):

    return teks_transaksi(
        judul,
        nama,
        bulan,
        qris["amount"],
        qris["trxid"],
        qris["transaction_id"],
        qris["created_at"],
        "menunggu",
    )
