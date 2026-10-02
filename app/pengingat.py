import random

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


KATA_TAGIH = (
    "ceuk si {pengirim} {tag} bayar goblog ges tanggal {tanggal} can mayar keneh",
    "ceuk si {pengirim} {tag} mayar atuh belegug, tanggal {tanggal} keneh can narik",
    "ceuk si {pengirim} {tag} sia mah lila teuing goblog, {tanggal} can mayar",
    "ceuk si {pengirim} {tag} cepetan mayar weh, tanggal {tanggal} geus asup belegug",
    "ceuk si {pengirim} {tag} bayar tai, tanggal {tanggal} can aya duitna keneh",
    "ceuk si {pengirim} {tag} maneh keneh nu can mayar tanggal {tanggal}, gerak goblog",
    "ceuk si {pengirim} {tag} ulah cicing wae belegug, mayar tanggal {tanggal}",
    "ceuk si {pengirim} {tag} iuran tanggal {tanggal} can kaluar keneh, bayar goblog",
)


def teks_tagih(belum, tanggal, pengirim):

    tag = " ".join(tag_anggota(nama) for nama in belum)

    return random.choice(KATA_TAGIH).format(
        pengirim=pengirim,
        tag=tag,
        tanggal=tanggal,
    )


KATA_SPAM_TAGIH = (
    "Heh {tag} goblog, spam terus. Tunggu heula lah, kena suspend sakedap.",
    "{tag} belegug banget, pencet Tagih terus. Diam heula 1-2 menit!",
    "Cicing atuh {tag}! Spam deui, otakna teu aya? Suspend heula.",
    "Ih {tag} teu waras, ulah spam wae. Tagih teu bisa dipencet sakedap.",
    "{tag} maneh lila teuing pencet. Tahan heula goblog, kena suspend!",
    "Woy {tag}, spam Tagih deui? Suspen sakedap heula belegug.",
    "{tag} goblog pisan, pencet terus. Eureun heula 1-2 menit!",
)


def teks_spam_tagih(nama):

    return random.choice(KATA_SPAM_TAGIH).format(
        tag=tag_anggota(nama) if nama else "sia",
    )


KATA_PUJI_LUNAS = (
    "Mantap ges, {bulan} geus lunas kabeh. resep pisan!",
    "Wah {bulan} beres kabeh, respect! Teu aya nu kudu ditagih.",
    "Gas! {bulan} geus mayar kabeh, solid pisan.",
    "Alhamdulillah {bulan} lunas kabeh. jago teuing!",
    "Sip, {bulan} geus beres. eweuh tunggakan, mantap!",
)


def teks_puji_lunas(bulan):

    return random.choice(KATA_PUJI_LUNAS).format(bulan=bulan)


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
