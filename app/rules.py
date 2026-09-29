from datetime import datetime
from zoneinfo import ZoneInfo

# ID Telegram Peri
ADMIN_ID = 1724220561

IURAN = 300000

ANGGOTA = [
    "Benoy",
    "Reyhan",
    "Pa Ali",
    "Bayu",
    "Indro",
    "Peri",
]

# Bulan iuran -> (tahun, bulan), dipakai untuk trxid & keterangan QRIS
PERIODE = {
    "Oktober": (2026, 10),
    "November": (2026, 11),
    "Desember": (2026, 12),
    "Januari": (2027, 1),
    "Februari": (2027, 2),
}

BULAN = list(PERIODE)

# Iuran x anggota x bulan (300.000 x 6 x 5 = 9.000.000)
TARGET = IURAN * len(ANGGOTA) * len(BULAN)

QRIS_URL = (
    "https://be-emet.equinoxteknologi.com/"
    "api/v360/gen_qr.php"
)

TIMEZONE = ZoneInfo("Asia/Jakarta")

# Callback yang hanya boleh dipakai Peri
KHUSUS_ADMIN = (
    "lunas|",
    "skipingatkan|",
)


def kata(teks):

    return [
        bagian
        for bagian in "".join(
            huruf.lower() if huruf.isalnum() else " "
            for huruf in (teks or "")
        ).split()
        if bagian
    ]


# Nama tampilan di grup -> nama iuran.
# Username tidak dipakai, karena bisa diganti siapa saja.
ALIAS_GRUP = {
    ("rey",): "Reyhan",
    ("beny", "benoy"): "Benoy",
    ("feri",): "Peri",
    ("bayu", "lingga"): "Bayu",
    ("ali", "achay"): "Pa Ali",
    ("indra", "purnama"): "Indro",
}


def nama_anggota_user(user):

    if not user:
        return None

    lengkap = tuple(kata(
        f"{user.get('first_name') or ''} {user.get('last_name') or ''}"
    ))

    if lengkap in ALIAS_GRUP:
        return ALIAS_GRUP[lengkap]

    for anggota in ANGGOTA:

        if lengkap == tuple(kata(anggota)):
            return anggota

    return None


def rupiah(angka):

    # 1800000 -> Rp1.800.000
    return "Rp" + f"{angka:,}".replace(",", ".")


def sekarang():

    return datetime.now(TIMEZONE)


def bulan_berjalan(saat=None):

    # Nama bulan iuran yang sama dengan tanggal hari ini, atau None
    # kalau hari ini di luar Oktober 2026–Februari 2027.

    saat = saat or sekarang()

    for nama, (tahun, nomor) in PERIODE.items():

        if tahun == saat.year and nomor == saat.month:
            return nama

    return None


def buat_trxid(nama, bulan):

    # Format provider: 202610BENOY
    # (tahun + bulan iuran + nama)

    tahun, nomor_bulan = PERIODE[bulan]

    nama_bersih = (
        nama
        .upper()
        .replace(" ", "")
        .replace("-", "")
    )

    return f"{tahun}{nomor_bulan:02d}" + nama_bersih


def trxid_selanjutnya(dasar, dipakai):

    # QR baru tidak boleh memakai trxid yang sudah ada.
    # 202610REYHAN, lalu 202610REYHAN2, 202610REYHAN3, ...

    if dasar not in dipakai:
        return dasar

    nomor = 2

    while f"{dasar}{nomor}" in dipakai:
        nomor += 1

    return f"{dasar}{nomor}"


def tombol(teks, data):

    return {"text": teks, "callback_data": data}


def papan(baris):

    return {"inline_keyboard": baris}


def menu():

    return papan([
        [tombol("💸 Bayar Iuran", "bayar")],
        [
            tombol("📊 Progress", "progress"),
            tombol("📋 Rekap", "rekap"),
        ],
        [tombol("⚠️ Tunggakan", "tunggakan")],
        [tombol("🔔 Pengingat", "ingatkan")],
    ])


PERINTAH_BOT = [
    {"command": "start", "description": "Menu utama"},
    {"command": "progress", "description": "Progress iuran"},
    {"command": "rekap", "description": "Rekap iuran"},
    {"command": "tunggakan", "description": "Daftar tunggakan"},
    {"command": "ingatkan", "description": "Aktifkan pengingat di grup ini"},
]


def tombol_kembali(target):

    return [[tombol("⬅️ Kembali", target)]]


def tombol_transaksi(trxid):

    return [
        [tombol("🔄 Cek Pembayaran", f"cekqr|{trxid}")],
        [tombol("✅ Tandai Lunas (Manual)", f"lunas|{trxid}")],
    ]


def teks_mulai():

    return (
        "🏡 VILLA 360\n"
        "Tabungan Villa 2027\n"
        f"Iuran {rupiah(IURAN)} / bulan\n"
        f"Target {rupiah(TARGET)}\n\n"
        "Pilih menu:"
    )


def teks_transaksi(judul, nama, bulan, nominal, trxid, transaksi_id, waktu, status):

    return (
        f"{judul}\n"
        f"{nama} · {bulan}\n"
        f"{rupiah(nominal)} · {status}\n"
        f"TRX {trxid}\n"
        f"ID {transaksi_id}\n"
        f"{waktu}"
    )


def teks_berhasil(row):

    tambahan = " · ".join(
        bagian
        for bagian in (row.get("channel"), row.get("refcode"))
        if bagian
    )

    teks = teks_transaksi(
        "✅ LUNAS",
        row["nama"],
        row["bulan"],
        row["nominal"],
        row["trxid"],
        row["transaction_id"],
        row.get("paid_at") or "-",
        "selesai",
    )

    if tambahan:
        teks += f"\n{tambahan}"

    return teks


def teks_progress(jumlah_per_nama):

    total_iuran = sum(
        jumlah_per_nama.get(nama, 0) for nama in ANGGOTA
    )

    slot = len(ANGGOTA) * len(BULAN)
    uang = total_iuran * IURAN
    persen = uang / TARGET * 100 if TARGET else 0

    if total_iuran == 0:
        terisi = 0
    else:
        terisi = min(10, max(1, round(persen / 10)))

    bar = "█" * terisi + "░" * (10 - terisi)

    return (
        "📊 PROGRESS\n"
        f"{bar} {persen:.1f}%\n"
        f"{rupiah(uang)} / {rupiah(TARGET)}\n"
        f"{total_iuran} dari {slot} iuran lunas"
    )


def hitung_per_nama(baris_pembayaran):

    jumlah = {nama: 0 for nama in ANGGOTA}

    for baris in baris_pembayaran:

        nama = baris["nama"]

        if nama in jumlah:
            jumlah[nama] += 1

    return jumlah
