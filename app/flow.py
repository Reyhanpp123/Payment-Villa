from contextvars import ContextVar

from app.pengingat import skip_pengingat
from app.qris import caption_qris, generate_qris
from app.rules import (
    ADMIN_ID,
    ANGGOTA,
    BULAN,
    IURAN,
    KHUSUS_ADMIN,
    TARGET,
    hitung_per_nama,
    menu,
    papan,
    rupiah,
    teks_berhasil,
    teks_mulai,
    teks_progress,
    tombol,
    tombol_kembali,
    tombol_transaksi,
)


USER_SESI = ContextVar("user_sesi", default=None)
DB_SESI = ContextVar("db_sesi", default=None)


def nama_perintah(teks):

    if not teks or not teks.startswith("/"):
        return None

    perintah = teks.split()[0]

    return perintah.split("@", 1)[0].lower()


def chat_grup(message):

    return message.get("chat", {}).get("type") in ("group", "supergroup")


async def tampilkan(tg, message, teks, reply_markup=None, db=None, user_id=None):

    # Pesan foto (QRIS) tidak punya teks untuk diedit,
    # jadi kirim pesan baru.

    if message.get("photo"):

        pesan = await tg.send_message(
            message["chat"]["id"],
            teks,
            reply_markup,
            reply_to=message["message_id"],
        )

        db = db or DB_SESI.get()
        user_id = user_id or USER_SESI.get()

        if db and user_id:
            await db.simpan_sesi(
                message["chat"]["id"],
                user_id,
                pesan["message_id"],
            )

        return pesan

    await tg.edit_text(
        message["chat"]["id"],
        message["message_id"],
        teks,
        reply_markup,
    )

    return message


async def hapus_qr_lama(tg, qr_lama):

    chat_id, message_id = qr_lama

    if not message_id:
        return

    await tg.delete_message(chat_id, message_id)


async def pembayaran_selesai(db, tg, trxid, message=None, user_id=None):

    # QRIS dihapus, diganti pesan
    # PEMBAYARAN SELESAI + progress dana terbaru.
    # message=None -> dipanggil dari push provider.

    user_id = user_id or USER_SESI.get()

    row = await db.get_qris(trxid)

    teks = teks_berhasil(row) + teks_progress(
        hitung_per_nama(await db.semua_pembayaran())
    )

    chat_id = row.get("chat_id") if row else None
    message_id = row.get("message_id") if row else None

    foto = bool(message and message.get("photo"))

    # Transaksi lama (sebelum ID pesan disimpan)
    if not message_id and message and foto:

        chat_id = message["chat"]["id"]
        message_id = message["message_id"]

    if message_id:

        terhapus = await tg.delete_message(chat_id, message_id)

        if not terhapus:

            # Tidak bisa dihapus (mis. pesan > 48 jam):
            # minimal buang tombolnya supaya QR tidak dipakai lagi.

            await tg.edit_caption(
                chat_id,
                message_id,
                "✅ QRIS ini sudah dibayar.",
                {"inline_keyboard": []},
            )

    # Ditekan dari layar teks -> ganti layar itu
    if message and not foto:

        await tampilkan(tg, message, teks, menu(), db, user_id)

        return

    tujuan = chat_id

    if not tujuan and message:
        tujuan = message["chat"]["id"]

    if not tujuan:
        raise RuntimeError("chat tujuan tidak ada")

    pesan = await tg.send_message(tujuan, teks, menu())

    if user_id:
        await db.simpan_sesi(tujuan, user_id, pesan["message_id"])
    elif message_id:
        await db.pindah_sesi(tujuan, message_id, pesan["message_id"])


async def kirim_qr(db, tg, message, qris, caption, user_id=None):

    pesan = await tg.send_photo(
        message["chat"]["id"],
        qris["qr_bytes"],
        caption,
        papan(
            tombol_transaksi(qris["trxid"])
            + tombol_kembali("bayar")
        ),
        reply_to=message["message_id"],
    )

    await db.simpan_pesan_qr(
        qris["trxid"],
        pesan["chat"]["id"],
        pesan["message_id"],
    )

    user_id = user_id or USER_SESI.get()

    if user_id:
        await db.simpan_sesi(
            pesan["chat"]["id"],
            user_id,
            pesan["message_id"],
        )

    await hapus_qr_lama(tg, qris["qr_lama"])


async def handle_update(update, db, tg):

    if "callback_query" in update:
        user_id = (update["callback_query"].get("from") or {}).get("id")
    else:
        user_id = ((update.get("message") or {}).get("from") or {}).get("id")

    token_user = USER_SESI.set(user_id)
    token_db = DB_SESI.set(db)

    try:
        await _handle_update(update, db, tg)
    finally:
        USER_SESI.reset(token_user)
        DB_SESI.reset(token_db)


async def _handle_update(update, db, tg):

    if "callback_query" in update:
        await handle_callback(update["callback_query"], db, tg)
        return

    message = update.get("message")

    if not message:
        return

    perintah = nama_perintah(message.get("text"))

    if perintah == "/start":

        user = message.get("from") or {}

        pesan = await tg.send_message(
            message["chat"]["id"],
            teks_mulai(),
            menu(),
            reply_to=message["message_id"],
        )

        if user.get("id"):
            await db.simpan_sesi(
                message["chat"]["id"],
                user["id"],
                pesan["message_id"],
            )

        return

    if perintah == "/ingatkan":

        user = message.get("from") or {}

        if user.get("id") != ADMIN_ID:

            await tg.send_message(
                message["chat"]["id"],
                "❌ Pengingat hanya bisa diatur Peri",
                reply_to=message["message_id"],
            )

            return

        if not chat_grup(message):

            await tg.send_message(
                message["chat"]["id"],
                "Kirim /ingatkan di grup yang akan menerima pengingat.",
                reply_to=message["message_id"],
            )

            return

        await db.simpan_tujuan_pengingat(message["chat"]["id"])

        await tg.send_message(
            message["chat"]["id"],
            """
✅ Pengingat iuran akan dikirim ke grup ini.

Tiap tanggal 1, pagi WIB, untuk anggota yang belum bayar.
Kalau pengiriman gagal, dicoba lagi hari berikutnya.

Tombol pada pesan itu mematikan sisa pengingat bulan berjalan.
""",
            reply_to=message["message_id"],
        )

        return

    if perintah == "/resetsemuadataanjing":

        user = message.get("from") or {}

        if user.get("id") != ADMIN_ID:
            return

        await db.hapus_semua()

        await tg.send_message(
            message["chat"]["id"],
            """
✅ RESET BERHASIL

Semua pembayaran dan transaksi QRIS
sudah dikosongkan.
""",
            reply_to=message["message_id"],
        )


async def handle_callback(query, db, tg):

    data = query.get("data") or ""
    message = query.get("message")
    user = query.get("from") or {}

    if not message:
        await tg.answer(query["id"])
        return

    user_id = user.get("id")

    # Pesan pengingat bukan sesi /start siapa pun.
    # Tombol skip tetap boleh ditekan Peri.
    if data.startswith("skipingatkan|"):

        if user_id != ADMIN_ID:

            await tg.answer(
                query["id"],
                "❌ Pengingat hanya bisa diatur Peri",
                show_alert=True,
            )

            return

        await tg.answer(query["id"])

        await skip_pengingat(
            db,
            tg,
            data.split("|", 1)[1],
            message,
        )

        return

    # Di grup, tiap orang punya pesan menu sendiri.
    # Tombol di pesan orang lain tidak boleh mengubah layar itu.
    if chat_grup(message) and user_id:

        sesi = await db.get_sesi(message["chat"]["id"], user_id)

        if not sesi or sesi.get("message_id") != message["message_id"]:

            await tg.answer(
                query["id"],
                "Tombol ini milik sesi orang lain. Kirim /start untuk membuka sesi kamu.",
                show_alert=True,
            )

            return

    if (
        data.startswith(KHUSUS_ADMIN)
        and user_id != ADMIN_ID
    ):

        await tg.answer(
            query["id"],
            "❌ Pembayaran hanya bisa dilakukan Peri",
            show_alert=True,
        )

        return

    if not data.startswith("cekqr|"):
        await tg.answer(query["id"])

    if data == "kembali":

        await tampilkan(
            tg,
            message,
            """
🏡 VILLA 360

Pilih menu:
""",
            menu(),
        )

        return

    if data == "bayar":

        baris = [
            [tombol(nama, f"nama|{nama}")]
            for nama in ANGGOTA
        ]

        baris += tombol_kembali("kembali")

        await tampilkan(
            tg,
            message,
            """
💸 BAYAR IURAN

Pilih nama:
""",
            papan(baris),
        )

        return

    if data.startswith("nama|"):

        nama = data.split("|", 1)[1]

        baris = [
            [tombol(bulan, f"bulan|{nama}|{bulan}")]
            for bulan in BULAN
        ]

        baris += tombol_kembali("bayar")

        await tampilkan(
            tg,
            message,
            f"""
💸 BAYAR IURAN

👤 Nama:
{nama}

Pilih bulan:
""",
            papan(baris),
        )

        return

    if data.startswith("bulan|"):

        bagian = data.split("|")

        # Bentuk lama tidak membawa nama.
        # Webhook tidak menyimpan pilihan di memori proses.
        if len(bagian) < 3:

            await tampilkan(
                tg,
                message,
                "❌ Nama belum dipilih.",
                menu(),
            )

            return

        nama = bagian[1]
        bulan = bagian[2]

        await lanjut_bayar(db, tg, message, nama, bulan)

        return

    if data.startswith("buatqr|"):

        bagian = data.split("|", 2)
        nama = bagian[1]
        bulan = bagian[2]

        await tampilkan(tg, message, "⏳ Membuat QRIS baru...")

        try:
            qris = await generate_qris(db, nama, bulan)
        except Exception as e:
            await tampilkan(
                tg,
                message,
                f"""
❌ GAGAL

{e}
""",
                menu(),
            )
            return

        await kirim_qr(
            db,
            tg,
            message,
            qris,
            f"""
💳 QRIS BARU

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

🕐 Dibuat:
{qris["created_at"]}

⏳ MENUNGGU PEMBAYARAN
""",
        )

        return

    if data.startswith("cekqr|"):

        await cek_pembayaran(db, tg, query, message)

        return

    if data.startswith("lunas|"):

        trxid = data.split("|", 1)[1]

        berhasil, pesan = await db.tandai_lunas(
            trxid,
            channel="MANUAL",
        )

        if not berhasil:

            await tampilkan(
                tg,
                message,
                f"❌ {pesan}",
                menu(),
            )

            return

        await pembayaran_selesai(db, tg, trxid, message)

        return

    if data == "progress":

        await tampilkan(
            tg,
            message,
            teks_progress(
                hitung_per_nama(await db.semua_pembayaran())
            ),
            menu(),
        )

        return

    if data == "dana":

        baris = await db.semua_pembayaran()

        total = sum((item.get("nominal") or 0) for item in baris)

        await tampilkan(
            tg,
            message,
            f"""
💰 TOTAL DANA

{rupiah(total)} / {rupiah(TARGET)}

📈 Progress:

{total / TARGET * 100:.1f}%
""",
            menu(),
        )

        return

    if data == "rekap":

        await tampilkan(
            tg,
            message,
            teks_rekap(await db.semua_pembayaran()),
            menu(),
        )

        return

    if data == "tunggakan":

        await tampilkan(
            tg,
            message,
            teks_tunggakan(await db.semua_pembayaran()),
            menu(),
        )


async def lanjut_bayar(db, tg, message, nama, bulan):

    if await db.sudah_lunas(nama, bulan):

        await tampilkan(
            tg,
            message,
            f"""
⚠️ SUDAH MELUNASI

👤 Nama:
{nama}

📅 Bulan:
{bulan}

💰 Nominal:
{rupiah(IURAN)}

Status:
LUNAS ✅
""",
            menu(),
        )

        return

    pending = await db.get_pending(nama, bulan)

    if pending:

        trxid = pending["trxid"]

        await tampilkan(
            tg,
            message,
            f"""
💳 TRANSAKSI MASIH MENUNGGU

👤 Nama:
{nama}

📅 Bulan:
{bulan}

💰 Nominal:
{rupiah(pending["nominal"])}

🆔 ID Transaksi:
{pending["transaction_id"]}

🔖 TRXID:
{trxid}

🕐 Dibuat:
{pending["created_at"]}

⏳ Status:
MENUNGGU PEMBAYARAN
""",
            papan(
                tombol_transaksi(trxid)
                + [[tombol(
                    "🔄 Buat QR Baru",
                    f"buatqr|{nama}|{bulan}",
                )]]
                + [[tombol("⬅️ Kembali", "bayar")]]
            ),
        )

        return

    await tampilkan(tg, message, "⏳ Sedang membuat QRIS...")

    try:
        qris = await generate_qris(db, nama, bulan)
    except Exception as e:

        print("ERROR GENERATE QRIS:", repr(e))

        await tampilkan(
            tg,
            message,
            f"""
❌ GAGAL MEMBUAT QRIS

{e}
""",
            menu(),
        )

        return

    await kirim_qr(
        db,
        tg,
        message,
        qris,
        caption_qris(
            nama,
            bulan,
            qris,
            "💳 PEMBAYARAN QRIS",
        ),
    )


async def cek_pembayaran(db, tg, query, message):

    trxid = query["data"].split("|", 1)[1]

    transaksi = await db.get_qris(trxid)

    if not transaksi:

        await tg.answer(
            query["id"],
            "❌ Transaksi tidak ditemukan",
            show_alert=True,
        )

        return

    if transaksi["status"] == "SUCCESS":

        await tg.answer(
            query["id"],
            "✅ Pembayaran sudah berhasil",
            show_alert=True,
        )

        await pembayaran_selesai(db, tg, trxid, message)

        return

    await tg.answer(
        query["id"],
        "⏳ Pembayaran belum diterima",
        show_alert=True,
    )


def teks_rekap(baris_pembayaran):

    jumlah = hitung_per_nama(baris_pembayaran)

    teks = """
📋 REKAP VILLA 360

━━━━━━━━━━━━━━

"""

    total = 0

    for nama in ANGGOTA:

        banyak = jumlah[nama]
        uang = banyak * IURAN
        total += uang

        lunas = "🟩" * banyak
        belum = "⬜" * (len(BULAN) - banyak)

        teks += f"""
👤 {nama}

{lunas}{belum}
{banyak}/{len(BULAN)}

💰 {rupiah(uang)}

"""

    teks += f"""
━━━━━━━━━━━━━━

💵 Total Kas:

{rupiah(total)}

🎯 Target:

{rupiah(TARGET)}
"""

    return teks


def teks_tunggakan(baris_pembayaran):

    lunas = {
        (baris["nama"], baris["bulan"])
        for baris in baris_pembayaran
    }

    teks = "⚠️ TUNGGAKAN\n\n"

    ada = False

    for nama in ANGGOTA:

        belum = [
            bulan
            for bulan in BULAN
            if (nama, bulan) not in lunas
        ]

        if belum:

            ada = True

            teks += (
                f"👤 {nama}\n"
                + ", ".join(belum)
                + "\n\n"
            )

    if not ada:
        teks += "🎉 Semua anggota sudah lunas"

    return teks
