from app.rules import (
    ANGGOTA,
    IURAN,
    PERIODE,
    bulan_berjalan,
    rupiah,
    tag_anggota,
    tombol,
    papan,
)


def yang_belum_bayar(bulan, baris_pembayaran):

    lunas = {
        baris["nama"]
        for baris in baris_pembayaran
        if baris.get("bulan") == bulan
    }

    return [nama for nama in ANGGOTA if nama not in lunas]


def teks_pengingat(bulan, belum):

    tahun = PERIODE[bulan][0]

    return (
        f"⚠️ PENGINGAT {bulan} {tahun}\n"
        f"Belum bayar: {', '.join(belum)}\n"
        f"{rupiah(IURAN)} / orang"
    )


def teks_tagih(belum, tanggal):

    tag = " ".join(tag_anggota(nama) for nama in belum)

    return (
        f"{tag} bayar goblog ges tanggal {tanggal} can mayar keneh"
    )


def tombol_skip(bulan):

    return papan([[
        tombol(
            "⏭️ Jangan ingatkan lagi bulan ini",
            f"skipingatkan|{bulan}",
        )
    ]])


async def kirim_pengingat(db, tg):

    # Dipanggil cron sekali sehari.
    # Tanggal 1 belum terkirim -> kirim.
    # Kalau gagal, panggilan hari berikutnya mengulang
    # sampai status terkirim atau skip.

    bulan = bulan_berjalan()

    if not bulan:
        return "di luar periode iuran"

    catatan = await db.get_pengingat(bulan)

    if catatan and catatan.get("status") in ("terkirim", "skip"):
        return catatan["status"]

    belum = yang_belum_bayar(bulan, await db.semua_pembayaran())

    if not belum:
        await db.simpan_pengingat(bulan, "terkirim")
        return "semua lunas"

    chat_id = await db.get_tujuan_pengingat()

    if not chat_id:
        return "tujuan belum diatur"

    pesan = await tg.send_message(
        chat_id,
        teks_pengingat(bulan, belum),
        tombol_skip(bulan),
    )

    await db.simpan_pengingat(
        bulan,
        "terkirim",
        pesan["message_id"],
    )

    return "terkirim"


async def skip_pengingat(db, tg, bulan, message):

    if bulan not in PERIODE:
        return False

    await db.simpan_pengingat(
        bulan,
        "skip",
        message.get("message_id"),
    )

    await tg.edit_text(
        message["chat"]["id"],
        message["message_id"],
        teks_pengingat(
            bulan,
            yang_belum_bayar(bulan, await db.semua_pembayaran()),
        )
        + "\n⏭️ Pengingat bulan ini dimatikan.",
        {"inline_keyboard": []},
    )

    return True
