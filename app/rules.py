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
    "bayar",
    "nama|",
    "bulan|",
    "buatqr|",
    "cekqr|",
    "lunas|",
)


def rupiah(angka):

    # 1800000 -> Rp1.800.000
    return "Rp" + f"{angka:,}".replace(",", ".")


def sekarang():

    return datetime.now(TIMEZONE)


def buat_trxid(nama, bulan):

    # Format provider: 202610BENOY
    # (tahun + bulan iuran + nama), satu trxid per anggota per bulan

    tahun, nomor_bulan = PERIODE[bulan]

    nama_bersih = (
        nama
        .upper()
        .replace(" ", "")
        .replace("-", "")
    )

    return f"{tahun}{nomor_bulan:02d}" + nama_bersih


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
    ])


def tombol_kembali(target):

    return [[tombol("⬅️ Kembali", target)]]


def tombol_transaksi(trxid):

    return [
        [tombol("🔄 Cek Pembayaran", f"cekqr|{trxid}")],
        [tombol("✅ Tandai Lunas (Manual)", f"lunas|{trxid}")],
    ]


def teks_mulai():

    return f"""
🏡 VILLA 360

Tabungan Villa 2027

💰 Iuran:
{rupiah(IURAN)} / bulan

🎯 Target:
{rupiah(TARGET)}

Silahkan pilih menu:
"""


def teks_berhasil(row):

    return f"""
✅ PEMBAYARAN SELESAI

━━━━━━━━━━━━━━

👤 Nama:
{row["nama"]}

📅 Bulan:
{row["bulan"]}

💰 Nominal:
{rupiah(row["nominal"])}

🆔 ID Transaksi:
{row["transaction_id"]}

🔖 TRXID:
{row["trxid"]}

💳 Channel:
{row.get("channel") or "-"}

🔖 Refcode:
{row.get("refcode") or "-"}

🕐 Dibayar:
{row.get("paid_at")}

━━━━━━━━━━━━━━

Status:
LUNAS ✅
"""


def teks_progress(jumlah_per_nama):

    teks = """
📊 PROGRESS VILLA 360

━━━━━━━━━━━━━━

"""

    total = 0

    for nama in ANGGOTA:

        jumlah = jumlah_per_nama.get(nama, 0)

        total += jumlah * IURAN

        jumlah_bar = min(jumlah, len(BULAN))

        bar = (
            "█" * jumlah_bar
            + "░" * (len(BULAN) - jumlah_bar)
        )

        teks += (
            f"{nama:<7} "
            f"{bar} "
            f"{jumlah}/{len(BULAN)}\n"
        )

    teks += f"""
━━━━━━━━━━━━━━

💰 Dana:
{rupiah(total)} / {rupiah(TARGET)}

📈 Progress:
{total / TARGET * 100:.1f}%
"""

    return teks


def hitung_per_nama(baris_pembayaran):

    jumlah = {nama: 0 for nama in ANGGOTA}

    for baris in baris_pembayaran:

        nama = baris["nama"]

        if nama in jumlah:
            jumlah[nama] += 1

    return jumlah
