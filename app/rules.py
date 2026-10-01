import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

# ID Telegram Peri
ADMIN_ID = 1724220561

# Tombol reset progress hanya di menu sesi user ini
RESET_OWNER_ID = 210230164

# Tandai lunas manual (Ali Achay / Pa Ali di grup)
MANUAL_LUNAS_ID = 33014779

IURAN = 300000

# Iuran khusus @feri30watt: QR = $300 × kurs saat generate.
# Progress/kas tetap 1 slot Rp300.000. Set False untuk matikan.
IURAN_USD_AKTIF = False
IURAN_USD_USERNAME = "feri30watt"
IURAN_USD_ANGGOTA = "Peri"
IURAN_USD_NOMINAL = 300
KURS_USD_URL = "https://open.er-api.com/v6/latest/USD"

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

# Callback yang hanya boleh dipakai Peri (reset data, dll.)
KHUSUS_ADMIN = (
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
# Username bebas tidak dipakai, karena bisa diganti siapa saja.
# Hanya username di daftar tetap ini yang dikenali.
ALIAS_GRUP = {
    ("rey",): "Reyhan",
    ("beny", "benoy"): "Benoy",
    ("feri",): "Peri",
    ("bayu",): "Bayu",
    ("bayu", "lingga"): "Bayu",
    ("lingga", "bayu"): "Bayu",
    ("ali", "achay"): "Pa Ali",
    ("ali",): "Pa Ali",
    ("indra", "purnama"): "Indro",
    ("indra",): "Indro",
}

USERNAME_TAG = {
    "reyhanPp": "Reyhan",
    "Benybenoy": "Benoy",
    "NuAliAchay": "Pa Ali",
    "bylinggha": "Bayu",
    "Indrapurnama9080": "Indro",
    "feri30watt": "Peri",
}

USERNAME_ANGGOTA = {
    username.lower(): anggota
    for username, anggota in USERNAME_TAG.items()
}


def kata_nama_user(user):

    if not user:
        return ()

    potong = [
        user.get("first_name") or "",
        user.get("last_name") or "",
    ]

    return tuple(kata(" ".join(potong)))


def cocok_kata(kunci, nama):

    # Urutan kata di profil Telegram tidak selalu sama dengan di grup.
    if not kunci or not nama:
        return False

    set_kunci = set(kunci)
    set_nama = set(nama)

    if not set_kunci <= set_nama:
        return False

    return len(nama) <= len(kunci) + 1


def username_anggota(user):

    if not user:
        return None

    nama = (user.get("username") or "").lstrip("@").lower()

    return USERNAME_ANGGOTA.get(nama)


def tag_anggota(nama):

    for tampilan, anggota in USERNAME_TAG.items():

        if anggota == nama:
            return f"@{tampilan}"

    return nama


def nama_anggota_user(user):

    if not user:
        return None

    lengkap = kata_nama_user(user)

    if lengkap in ALIAS_GRUP:
        return ALIAS_GRUP[lengkap]

    for kunci in sorted(ALIAS_GRUP, key=len, reverse=True):

        if cocok_kata(kunci, lengkap):
            return ALIAS_GRUP[kunci]

    for anggota in ANGGOTA:

        kunci = tuple(kata(anggota))

        if lengkap == kunci or cocok_kata(kunci, lengkap):
            return anggota

    return username_anggota(user)


def rupiah(angka):

    # 1800000 -> Rp1.800.000
    return "Rp" + f"{angka:,}".replace(",", ".")


def sekarang():

    return datetime.now(TIMEZONE)


def teks_tanggal(saat=None):

    nama_bulan = (
        "",
        "Januari",
        "Februari",
        "Maret",
        "April",
        "Mei",
        "Juni",
        "Juli",
        "Agustus",
        "September",
        "Oktober",
        "November",
        "Desember",
    )

    saat = saat or sekarang()

    return f"{saat.day} {nama_bulan[saat.month]} {saat.year}"


def bulan_berjalan(saat=None):

    # Nama bulan iuran yang sama dengan tanggal hari ini, atau None
    # kalau hari ini di luar Oktober 2026–Februari 2027.

    saat = saat or sekarang()

    for nama, (tahun, nomor) in PERIODE.items():

        if tahun == saat.year and nomor == saat.month:
            return nama

    return None


def bulan_terbuka(saat=None):

    # Bulan yang sudah masuk waktunya, plus satu bulan di depannya.
    # Layar bayar tetap satu tombol: yang paling awal belum lunas.
    # Jadi November baru muncul setelah Oktober orang itu lunas.

    saat = saat or sekarang()
    nama_bulan = list(PERIODE)
    terbuka = []
    indeks_terakhir = None

    for indeks, (nama, (tahun, nomor)) in enumerate(PERIODE.items()):

        if (tahun, nomor) <= (saat.year, saat.month):
            terbuka.append(nama)
            indeks_terakhir = indeks

    if (
        indeks_terakhir is not None
        and indeks_terakhir + 1 < len(nama_bulan)
    ):
        terbuka.append(nama_bulan[indeks_terakhir + 1])

    return terbuka


def trxid_acak(bulan, dipakai=()):

    # ID lama (202610INDRO) ditolak provider kalau pernah dipakai,
    # termasuk setelah data lokal direset. Setiap QR pakai ID baru.

    tahun, nomor_bulan = PERIODE[bulan]
    awalan = f"{tahun}{nomor_bulan:02d}"

    while True:

        kandidat = awalan + secrets.token_hex(4).upper()

        if kandidat not in dipakai:
            return kandidat


def tombol(teks, data):

    return {"text": teks, "callback_data": data}


def papan(baris):

    return {"inline_keyboard": baris}


def menu(user_id=None):

    baris = [
        [tombol("💸 Bayar Iuran", "bayar")],
        [
            tombol("📊 Progress", "progress"),
            tombol("📋 Rekap", "rekap"),
        ],
        [tombol("⚠️ Tunggakan", "tunggakan")],
        [tombol("🔔 Pengingat", "ingatkan")],
        [tombol("📣 Tagih", "tagih")],
    ]

    if user_id == RESET_OWNER_ID:
        baris.append([tombol("🗑 Reset Progress", "resetprogress")])

    return papan(baris)


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
