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


# Disusun dari potongan acak supaya tiap klik terasa natural,
# bukan template baku yang sama terus.

_TAGIH_PEMBUKA = (
    "ceuk si {pengirim}",
    "dari {pengirim}:",
    "{pengirim} nanya,",
    "oy {pengirim} bilang,",
    "pesan ti {pengirim}:",
    "{pengirim} lagi ngamuk,",
)

_TAGIH_ISI = (
    "{tag} bayar goblog, tanggal {tanggal} can mayar keneh",
    "{tag} mayar atuh belegug, {tanggal} keneh can narik",
    "{tag} sia mah lila teuing, {tanggal} can mayar",
    "{tag} cepetan mayar weh, {tanggal} geus asup belegug",
    "{tag} bayar tai, {tanggal} can aya duitna keneh",
    "{tag} gerak goblog, nu can mayar tanggal {tanggal}",
    "{tag} ulah cicing wae, mayar tanggal {tanggal}",
    "{tag} iuran {tanggal} can kaluar keneh, bayar goblog",
    "{tag} heh can mayar? tanggal {tanggal} keneh goblog",
    "{tag} mending mayar ayeuna, {tanggal} geus lewat belegug",
    "{tag} duit iuran mana? {tanggal} can dibayar keneh",
    "{tag} woy bayar, {tanggal} masih nunggak goblog",
)

_TAGIH_UTUH = (
    "{tag} bayar goblog ges tanggal {tanggal} can mayar keneh — ceuk si {pengirim}",
    "heh {tag}, {pengirim} nyuruh mayar. tanggal {tanggal} can kaluar keneh belegug",
    "{pengirim}: {tag} cepetan bayar, {tanggal} keneh nunggak goblog",
    "oy {tag}! si {pengirim} lagi nyari duit iuran. tanggal {tanggal} can mayar",
    "{tag} maneh can mayar tanggal {tanggal}. ceuk si {pengirim} gerak atuh!",
    "dari {pengirim} ke {tag}: bayar tai, {tanggal} can aya duitna keneh",
)


def teks_tagih(belum, tanggal, pengirim):

    tag = " ".join(tag_anggota(nama) for nama in belum)
    isi = {
        "pengirim": pengirim,
        "tag": tag,
        "tanggal": tanggal,
    }

    # Kadang satu kalimat utuh, kadang potongan digabung.
    if random.random() < 0.45:
        return random.choice(_TAGIH_UTUH).format(**isi)

    return (
        f"{random.choice(_TAGIH_PEMBUKA).format(**isi)} "
        f"{random.choice(_TAGIH_ISI).format(**isi)}"
    )


_SPAM_TAGIH = (
    "heh {tag} goblog, spam terus. tunggu heula lah, kena suspend sakedap",
    "{tag} belegug banget, pencet Tagih terus. diam heula 1-2 menit!",
    "cicing atuh {tag}! spam deui, otakna teu aya? suspend heula",
    "ih {tag} teu waras, ulah spam wae. Tagih teu bisa dipencet sakedap",
    "{tag} maneh lila teuing pencet. tahan heula goblog, kena suspend!",
    "woy {tag}, spam Tagih deui? suspen sakedap heula belegug",
    "{tag} goblog pisan, pencet terus. eureun heula 1-2 menit!",
    "euy {tag}, ulah spam. bot keur kesel, diam heula sakedap goblog",
    "{tag} teh senang pencet? tahan dulu lah, kena suspend 1-2 menit",
    "stop {tag}! spam Tagih terus belegug. istirahat heula",
)


def teks_spam_tagih(nama):

    return random.choice(_SPAM_TAGIH).format(
        tag=tag_anggota(nama) if nama else "sia",
    )


_PUJI_LUNAS = (
    "mantap ges, {bulan} geus lunas kabeh. resep pisan!",
    "wah {bulan} beres kabeh, respect! teu aya nu kudu ditagih",
    "gas! {bulan} geus mayar kabeh, solid pisan",
    "alhamdulillah {bulan} lunas kabeh. jago teuing!",
    "sip, {bulan} geus beres. eweuh tunggakan, mantap!",
    "nice, {bulan} beres kabeh. teu aya nu kudu ditagih deui",
    "wah solid! {bulan} geus lunas semua, resep ningalna",
    "{bulan} beres kabeh ges. respect banget, teu aya nunggak",
)


def teks_puji_lunas(bulan):

    return random.choice(_PUJI_LUNAS).format(bulan=bulan)


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
