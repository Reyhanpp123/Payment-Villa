from contextvars import ContextVar
from datetime import datetime, timedelta
import random

from app.pengingat import (
    skip_pengingat,
    teks_puji_lunas,
    teks_spam_tagih,
    teks_tagih,
    yang_belum_bayar,
)
from app.qris import caption_qris, generate_qris
from app.rules import (
    ADMIN_ID,
    MANUAL_LUNAS_ID,
    RESET_OWNER_ID,
    ANGGOTA,
    BULAN,
    IURAN,
    TARGET,
    TAGIH_COOLDOWN_DETIK,
    TAGIH_SUSPEND_MAX_DETIK,
    TAGIH_SUSPEND_MIN_DETIK,
    TIMEZONE,
    bulan_berjalan,
    bulan_terbuka,
    hitung_per_nama,
    menu,
    nama_anggota_user,
    papan,
    rupiah,
    sekarang,
    teks_berhasil,
    PERINTAH_BOT,
    teks_mulai,
    teks_progress,
    teks_tanggal,
    teks_transaksi,
    tombol,
    tombol_kembali,
    tombol_transaksi,
    username_anggota,
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


def id_sama(kiri, kanan):

    try:
        return int(kiri) == int(kanan)
    except (TypeError, ValueError):
        return False


def menu_pengguna(user_id=None):

    if user_id is None:
        user_id = USER_SESI.get()

    return menu(user_id)


async def tampilkan(tg, message, teks, reply_markup=None, db=None, user_id=None):

    # Pesan foto tidak bisa diedit jadi teks,
    # jadi balasannya dikirim sebagai pesan baru.

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

        await tampilkan(tg, message, teks, menu_pengguna(user_id), db, user_id)

        return

    tujuan = chat_id

    if not tujuan and message:
        tujuan = message["chat"]["id"]

    if not tujuan:
        raise RuntimeError("chat tujuan tidak ada")

    pesan = await tg.send_message(tujuan, teks, menu_pengguna(user_id))

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


_perintah_siap = False
_perintah_chat = set()


def chat_id_update(update):

    if "callback_query" in update:
        message = update["callback_query"].get("message") or {}
    else:
        message = update.get("message") or {}

    chat = message.get("chat") or {}

    return chat.get("id")


async def pastikan_perintah(tg, chat_id=None):

    global _perintah_siap

    if not _perintah_siap:

        try:
            await tg.daftarkan_perintah(PERINTAH_BOT)
            _perintah_siap = True
        except Exception as e:
            print("GAGAL DAFTAR PERINTAH:", repr(e))

    if chat_id is None or chat_id in _perintah_chat:
        return

    try:
        await tg.daftarkan_perintah(PERINTAH_BOT, chat_id=chat_id)
        _perintah_chat.add(chat_id)
    except Exception as e:
        print("GAGAL DAFTAR PERINTAH GRUP:", repr(e))


async def balas_layar(db, tg, message, teks, markup=None):

    user = message.get("from") or {}

    pesan = await tg.send_message(
        message["chat"]["id"],
        teks,
        menu_pengguna(user.get("id")) if markup is None else markup,
        reply_to=message["message_id"],
    )

    if user.get("id"):
        await db.simpan_sesi(
            message["chat"]["id"],
            user["id"],
            pesan["message_id"],
        )

    return pesan


async def atur_pengingat(db, tg, message, lewat_tombol=False):

    if not chat_grup(message):

        teks = (
            "Pengingat dipakai di grup, supaya pesannya masuk ke grup itu."
        )

    else:

        await db.simpan_tujuan_pengingat(message["chat"]["id"])

        teks = (
            "✅ Pengingat iuran dikirim ke grup ini tiap tanggal 1 pagi, "
            "untuk yang belum bayar. Tombol pada pesan itu mematikan "
            "pengingat bulan berjalan."
        )

    if lewat_tombol:
        pengguna = (message.get("from") or {}).get("id")
        await tampilkan(tg, message, teks, menu_pengguna(pengguna))
        return

    await balas_layar(db, tg, message, teks)


def _parse_waktu(nilai):

    if not nilai:
        return None

    if isinstance(nilai, datetime):
        saat = nilai
    else:
        teks = str(nilai).replace("Z", "+00:00")
        saat = datetime.fromisoformat(teks)

    if saat.tzinfo is None:
        return saat.replace(tzinfo=TIMEZONE)

    return saat.astimezone(TIMEZONE)


async def kirim_marah_spam(tg, message, nama):

    chat_id = (message or {}).get("chat", {}).get("id")

    if not chat_id:
        return

    await tg.send_message(chat_id, teks_spam_tagih(nama))


async def cek_batas_tagih(db, tg, query, user):

    # Cooldown 3 menit setelah pesan Tagih ke grup (tagih atau pujian).
    # Spam di dalam jendela itu: pesan marah ke grup 1x + suspend 1-2 menit.
    # Klik lagi saat suspend: diam saja, tanpa pesan berulang.

    user_id = user.get("id")

    if not user_id:
        return False

    batas = await db.get_tagih_batas(user_id)
    sekarang_ini = sekarang()
    nama = nama_anggota_user(user) or "sia"
    message = query.get("message") or {}

    suspended_until = _parse_waktu(
        (batas or {}).get("suspended_until")
    )

    if suspended_until and suspended_until > sekarang_ini:

        if not (batas or {}).get("alert_ditampilkan"):

            await db.simpan_tagih_batas(
                user_id,
                last_tagih_at=(batas or {}).get("last_tagih_at"),
                suspended_until=suspended_until.isoformat(),
                alert_ditampilkan=True,
            )

            await tg.answer(query["id"])
            await kirim_marah_spam(tg, message, nama)

        else:
            await tg.answer(query["id"])

        return False

    last_tagih = _parse_waktu((batas or {}).get("last_tagih_at"))

    if last_tagih:

        jeda = (sekarang_ini - last_tagih).total_seconds()

        if jeda < TAGIH_COOLDOWN_DETIK:

            suspend_detik = random.randint(
                TAGIH_SUSPEND_MIN_DETIK,
                TAGIH_SUSPEND_MAX_DETIK,
            )
            suspended_until = sekarang_ini + timedelta(
                seconds=suspend_detik
            )

            await db.simpan_tagih_batas(
                user_id,
                last_tagih_at=last_tagih.isoformat(),
                suspended_until=suspended_until.isoformat(),
                alert_ditampilkan=True,
            )

            await tg.answer(query["id"])
            await kirim_marah_spam(tg, message, nama)

            return False

    return True


async def catat_klik_tagih(db, user):

    # Setiap pesan Tagih ke grup (tagih atau pujian) ikut cooldown.
    user_id = (user or {}).get("id")

    if not user_id:
        return

    await db.simpan_tagih_batas(
        user_id,
        last_tagih_at=sekarang().isoformat(),
        suspended_until=None,
        alert_ditampilkan=False,
    )


async def kirim_tagih(db, tg, message, user=None):

    if not chat_grup(message):

        await tampilkan(
            tg,
            message,
            "Tagih dipakai di grup, supaya mention-nya masuk ke grup.",
            menu_pengguna(),
        )

        return

    bulan = bulan_berjalan()

    if not bulan:

        await tg.send_message(
            message["chat"]["id"],
            "Sekarang di luar periode iuran.",
        )

        return

    belum = yang_belum_bayar(bulan, await db.semua_pembayaran())

    if not belum:

        await tg.send_message(
            message["chat"]["id"],
            teks_puji_lunas(bulan),
        )
        await catat_klik_tagih(db, user)

        return

    pengirim = nama_anggota_user(user) or "teman"

    await tg.send_message(
        message["chat"]["id"],
        teks_tagih(belum, teks_tanggal(), pengirim),
    )
    await catat_klik_tagih(db, user)


async def handle_update(update, db, tg):

    if "callback_query" in update:
        user_id = (update["callback_query"].get("from") or {}).get("id")
    else:
        user_id = ((update.get("message") or {}).get("from") or {}).get("id")

    token_user = USER_SESI.set(user_id)
    token_db = DB_SESI.set(db)

    await pastikan_perintah(tg, chat_id_update(update))

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

        await balas_layar(db, tg, message, teks_mulai())

        return

    if perintah == "/ingatkan":

        await atur_pengingat(db, tg, message)

        return

    if perintah == "/progress":

        await balas_layar(
            db,
            tg,
            message,
            teks_progress(
                hitung_per_nama(await db.semua_pembayaran())
            ),
        )

        return

    if perintah == "/rekap":

        await balas_layar(
            db,
            tg,
            message,
            teks_rekap(await db.semua_pembayaran()),
        )

        return

    if perintah == "/tunggakan":

        await balas_layar(
            db,
            tg,
            message,
            teks_tunggakan(await db.semua_pembayaran()),
        )

        return

    if perintah == "/resetsemuadataanjing":

        user = message.get("from") or {}

        if user.get("id") != ADMIN_ID:
            return

        await db.hapus_semua()

        await tg.send_message(
            message["chat"]["id"],
            "✅ Reset berhasil. Pembayaran dan transaksi QRIS dikosongkan.",
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

    # Pesan pengingat dikirim ke grup, bukan sesi satu orang.
    # Siapa saja di grup itu boleh mematikan pengingat bulan ini.
    if data.startswith("skipingatkan|"):

        await tg.answer(query["id"])

        await skip_pengingat(
            db,
            tg,
            data.split("|", 1)[1],
            message,
        )

        return

    # Pa Ali boleh tandai lunas di QR orang lain di grup.
    # Tagih boleh ditekan semua username anggota, meski menu orang lain.
    lewati_kunci_sesi = (
        data.startswith("lunas|")
        and user_id == MANUAL_LUNAS_ID
    ) or (
        data == "tagih"
        and username_anggota(user)
    )

    # Di grup, tombol hanya melanjutkan sesi orang yang punya pesan itu.
    if chat_grup(message) and user_id and not lewati_kunci_sesi:

        sesi = await db.get_sesi(message["chat"]["id"], user_id)

        if not sesi or not id_sama(sesi.get("message_id"), message["message_id"]):

            await tg.answer(
                query["id"],
                "Tombol ini bukan sesi kamu. Kirim /start untuk membuka sesi sendiri.",
                show_alert=True,
            )

            return

    if (
        data.startswith("lunas|")
        and user_id != MANUAL_LUNAS_ID
    ):

        await tg.answer(
            query["id"],
            "❌ Tandai lunas manual hanya bisa dilakukan Pa Ali.",
            show_alert=True,
        )

        return

    if data == "bayar" or data.startswith((
        "nama|",
        "bulan|",
        "buatqr|",
        "cekqr|",
    )):

        punya = nama_anggota_user(user)

        if not punya:

            await tg.answer(
                query["id"],
                "❌ Nama Telegram kamu tidak ada di daftar anggota.",
                show_alert=True,
            )

            return

        target = nama_target_bayar(data)

        if target and target != punya:

            await tg.answer(
                query["id"],
                "❌ Kamu hanya bisa membayar atas nama sendiri.",
                show_alert=True,
            )

            return

    if data == "tagih":

        if not username_anggota(user):

            await tg.answer(
                query["id"],
                "❌ Tagih hanya bisa dipakai anggota.",
                show_alert=True,
            )

            return

        if not await cek_batas_tagih(db, tg, query, user):
            return

        await tg.answer(query["id"])
        await kirim_tagih(db, tg, message, user)

        return

    if not data.startswith("cekqr|"):
        await tg.answer(query["id"])

    if data == "ingatkan":

        await atur_pengingat(db, tg, message, lewat_tombol=True)

        return

    if data == "kembali":

        await tampilkan(
            tg,
            message,
            teks_mulai(),
            menu_pengguna(user_id),
        )

        return

    if data == "resetprogress" or data == "resetprogress|ya":

        if user_id != RESET_OWNER_ID:

            await tg.answer(
                query["id"],
                "❌ Tombol ini khusus admin reset.",
                show_alert=True,
            )

            return

        if data == "resetprogress":

            await tampilkan(
                tg,
                message,
                (
                    "🗑 RESET PROGRESS\n\n"
                    "Kosongkan semua pembayaran dan transaksi QRIS?\n"
                    "Tidak bisa dibatalkan."
                ),
                papan([
                    [tombol("✅ Ya, kosongkan", "resetprogress|ya")],
                    [tombol("⬅️ Batal", "kembali")],
                ]),
            )

            return

        await db.hapus_semua()

        await tampilkan(
            tg,
            message,
            "✅ Progress direset.\n\n" + teks_mulai(),
            menu_pengguna(user_id),
        )

        return

    if data == "bayar":

        await layar_bulan(db, tg, message, nama_anggota_user(user))

        return

    if data.startswith("nama|"):

        await layar_bulan(db, tg, message, data.split("|", 1)[1])

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
                menu_pengguna(user_id),
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
            trxid = await db.trxid_berikutnya(nama, bulan)
            qris = await generate_qris(db, nama, bulan, trxid)
            await db.ganti_pending_lain(nama, bulan, qris["trxid"])
        except Exception as e:
            await tampilkan(
                tg,
                message,
                f"""
❌ GAGAL

{e}
""",
                menu_pengguna(user_id),
            )
            return

        await kirim_qr(
            db,
            tg,
            message,
            qris,
            teks_transaksi(
                "💳 QRIS BARU",
                nama,
                bulan,
                qris["amount"],
                qris["trxid"],
                qris["transaction_id"],
                qris["created_at"],
                "menunggu",
            ),
        )

        return

    if data.startswith("cekqr|"):

        await cek_pembayaran(
            db,
            tg,
            query,
            message,
            nama_anggota_user(user),
        )

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
                menu_pengguna(user_id),
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
            menu_pengguna(user_id),
        )

        return

    if data == "dana":

        baris = await db.semua_pembayaran()

        total = sum((item.get("nominal") or 0) for item in baris)

        await tampilkan(
            tg,
            message,
            (
                f"💰 DANA\n"
                f"{rupiah(total)} / {rupiah(TARGET)} "
                f"({total / TARGET * 100:.1f}%)"
            ),
            menu_pengguna(user_id),
        )

        return

    if data == "rekap":

        await tampilkan(
            tg,
            message,
            teks_rekap(await db.semua_pembayaran()),
            menu_pengguna(user_id),
        )

        return

    if data == "tunggakan":

        await tampilkan(
            tg,
            message,
            teks_tunggakan(await db.semua_pembayaran()),
            menu_pengguna(user_id),
        )


def nama_target_bayar(data):

    if data.startswith("nama|"):
        return data.split("|", 1)[1]

    if data.startswith(("bulan|", "buatqr|")):

        bagian = data.split("|")

        if len(bagian) >= 3:
            return bagian[1]

    return None


async def layar_bulan(db, tg, message, nama):

    # Satu tombol: bulan paling awal yang belum lunas.
    # Bulan berikutnya baru masuk setelah bulan ini lunas,
    # supaya bisa transfer dua kali berturut-turut.

    terbuka = bulan_terbuka()
    bulan = None

    for kandidat in terbuka:

        if not await db.sudah_lunas(nama, kandidat):
            bulan = kandidat
            break

    if not bulan:

        if terbuka:
            teks = f"✅ {nama}\nSampai {terbuka[-1]} sudah lunas."
        else:
            teks = f"{nama}\nBelum ada bulan yang bisa dibayar."

        await tampilkan(
            tg,
            message,
            teks,
            papan(tombol_kembali("kembali")),
        )

        return

    await tampilkan(
        tg,
        message,
        f"💸 BAYAR\n{nama}\nPilih bulan:",
        papan(
            [[tombol(bulan, f"bulan|{nama}|{bulan}")]]
            + tombol_kembali("kembali")
        ),
    )


async def tampilkan_qr_tersimpan(db, tg, message, row):

    # Gambar QR tidak disimpan di database.
    # Yang ada hanya pesan foto lama, jadi disalin ulang ke chat.

    if not row or not row.get("message_id") or not row.get("chat_id"):
        return False

    caption = teks_transaksi(
        "💳 MENUNGGU",
        row["nama"],
        row["bulan"],
        row["nominal"],
        row["trxid"],
        row["transaction_id"],
        row["created_at"],
        "menunggu",
    )

    try:

        hasil = await tg.copy_message(
            message["chat"]["id"],
            row["chat_id"],
            row["message_id"],
            caption,
            papan(
                tombol_transaksi(row["trxid"])
                + [[tombol(
                    "🔄 Buat QR Baru",
                    f"buatqr|{row['nama']}|{row['bulan']}",
                )]]
                + [[tombol("⬅️ Kembali", "bayar")]]
            ),
            reply_to=message["message_id"],
        )

    except RuntimeError:
        return False

    user_id = USER_SESI.get()
    message_id = hasil.get("message_id") if isinstance(hasil, dict) else None

    if user_id and message_id:
        await db.simpan_sesi(
            message["chat"]["id"],
            user_id,
            message_id,
        )

    return True


async def lanjut_bayar(db, tg, message, nama, bulan):

    if await db.sudah_lunas(nama, bulan):

        await tampilkan(
            tg,
            message,
            f"✅ {nama} · {bulan} sudah lunas\n{rupiah(IURAN)}",
            menu_pengguna(),
        )

        return

    pending = await db.get_pending(nama, bulan)

    if pending:

        trxid = pending["trxid"]
        row = await db.get_qris(trxid)

        if await tampilkan_qr_tersimpan(db, tg, message, row):
            return

        await tampilkan(
            tg,
            message,
            teks_transaksi(
                "💳 MENUNGGU",
                nama,
                bulan,
                pending["nominal"],
                trxid,
                pending["transaction_id"],
                pending["created_at"],
                "menunggu",
            ),
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
            menu_pengguna(),
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


async def cek_pembayaran(db, tg, query, message, nama_sendiri):

    trxid = query["data"].split("|", 1)[1]

    transaksi = await db.get_qris(trxid)

    if not transaksi:

        await tg.answer(
            query["id"],
            "❌ Transaksi tidak ditemukan",
            show_alert=True,
        )

        return

    if transaksi["nama"] != nama_sendiri:

        await tg.answer(
            query["id"],
            "❌ Ini bukan pembayaran kamu.",
            show_alert=True,
        )

        return

    if transaksi["status"] not in ("PENDING", "SUCCESS"):

        await tg.answer(
            query["id"],
            "QR ini sudah diganti. Buat QR baru.",
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

    if not message.get("photo"):
        await tampilkan_qr_tersimpan(db, tg, message, transaksi)


_BULAN_SINGKAT = {
    "Oktober": "Okt",
    "November": "Nov",
    "Desember": "Des",
    "Januari": "Jan",
    "Februari": "Feb",
}


def singkat_bulan(bulan):

    return _BULAN_SINGKAT.get(bulan, bulan[:3])


def label_bulan(daftar):

    if not daftar:
        return "—"

    singkat = [singkat_bulan(bulan) for bulan in daftar]
    indeks = [BULAN.index(bulan) for bulan in daftar]
    bagian = []
    mulai = 0

    for i in range(1, len(indeks) + 1):

        putus = i == len(indeks) or indeks[i] != indeks[i - 1] + 1

        if not putus:
            continue

        potong = singkat[mulai:i]

        if len(potong) >= 3:
            bagian.append(f"{potong[0]}–{potong[-1]}")
        else:
            bagian.extend(potong)

        mulai = i

    return ", ".join(bagian)


def bulan_lunas(baris_pembayaran):

    ada = {
        (baris["nama"], baris["bulan"])
        for baris in baris_pembayaran
    }

    return {
        nama: [bulan for bulan in BULAN if (nama, bulan) in ada]
        for nama in ANGGOTA
    }


def teks_rekap(baris_pembayaran):

    lunas = bulan_lunas(baris_pembayaran)

    teks = "📋 REKAP\n"
    total = 0

    for nama in ANGGOTA:

        bulan = lunas[nama]

        if not bulan:
            teks += f"{nama} · —\n"
            continue

        uang = len(bulan) * IURAN
        total += uang
        teks += f"{nama} · {label_bulan(bulan)} · {rupiah(uang)}\n"

    teks += f"\nKas {rupiah(total)} / {rupiah(TARGET)}"

    return teks


def teks_tunggakan(baris_pembayaran):

    lunas = bulan_lunas(baris_pembayaran)

    belum_per_bulan = [
        [nama for nama in ANGGOTA if bulan not in lunas[nama]]
        for bulan in BULAN
    ]

    if not any(belum_per_bulan):
        return "⚠️ TUNGGAKAN\nSemua anggota sudah lunas"

    teks = "⚠️ TUNGGAKAN\n"
    i = 0

    while i < len(BULAN):

        orang = belum_per_bulan[i]

        if not orang:
            i += 1
            continue

        j = i + 1

        while j < len(BULAN) and belum_per_bulan[j] == orang:
            j += 1

        if len(orang) == len(ANGGOTA):
            nama = "semua"
        else:
            nama = ", ".join(orang)

        teks += f"{label_bulan(BULAN[i:j])} · {nama}\n"
        i = j

    return teks.rstrip("\n")
