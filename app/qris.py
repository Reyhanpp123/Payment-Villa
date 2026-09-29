import base64

import httpx

from app.rules import IURAN, PERIODE, QRIS_URL, buat_trxid, rupiah, sekarang


async def generate_qris(db, nama, bulan):

    trxid = buat_trxid(nama, bulan)

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

    return f"""
{judul}

━━━━━━━━━━━━━━

👤 Nama:
{nama}

📅 Bulan:
{bulan}

💰 Nominal:
{rupiah(qris["amount"])}

🆔 ID Transaksi:
{qris["transaction_id"]}

🔖 TRXID:
{qris["trxid"]}

🕐 Waktu:
{qris["created_at"]}

━━━━━━━━━━━━━━

⏳ Status:
MENUNGGU PEMBAYARAN

Silakan scan QRIS di atas.
"""
