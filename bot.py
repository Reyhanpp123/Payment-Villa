import os
import secrets
import io
import base64
import sqlite3
import traceback

from dotenv import load_dotenv

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from aiohttp import web

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.error import BadRequest

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)


load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

# ID Telegram Peri
ADMIN_ID = 1724220561

IURAN = 300000

ANGGOTA = [
    "Benoy",
    "Reyhan",
    "Pa Ali",
    "Bayu",
    "Indro",
    "Peri"
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

# Server penerima PUSH dari provider QRIS.
# URL yang didaftarkan ke provider:
#   http://<alamat-publik>:<PUSH_PORT>/qris/push/<PUSH_SECRET>
PUSH_PORT = int(os.getenv("PUSH_PORT", "8080"))
PUSH_SECRET = os.getenv("PUSH_SECRET")

# Callback yang hanya boleh dipakai Peri
KHUSUS_ADMIN = (
    "bayar",
    "nama|",
    "bulan|",
    "buatqr|",
    "cekqr|",
    "lunas|"
)


# ============================================================
# CEK TOKEN
# ============================================================

if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN belum diset.\n"
        "Mac/Linux:\n"
        "export BOT_TOKEN='TOKEN_BOT_KAMU'"
    )

if not PUSH_SECRET:
    raise RuntimeError(
        "PUSH_SECRET belum diset di .env.\n"
        "Isi dengan teks acak panjang, contoh:\n"
        "PUSH_SECRET=" + secrets.token_urlsafe(24)
    )


# ============================================================
# DATABASE
# ============================================================

db = sqlite3.connect(
    "villa.db",
    check_same_thread=False
)

cursor = db.cursor()


# Tabel pembayaran yang sudah LUNAS
cursor.execute("""
CREATE TABLE IF NOT EXISTS pembayaran (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    nama TEXT,

    bulan TEXT,

    nominal INTEGER

)
""")


# Tabel transaksi QRIS
cursor.execute("""
CREATE TABLE IF NOT EXISTS qris_transactions (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    trxid TEXT UNIQUE,

    transaction_id TEXT,

    nama TEXT,

    bulan TEXT,

    nominal INTEGER,

    status TEXT DEFAULT 'PENDING',

    refcode TEXT,

    channel TEXT,

    created_at TEXT,

    paid_at TEXT

)
""")


# Kolom untuk menyimpan pesan foto QR,
# supaya bisa dihapus otomatis setelah lunas
kolom_qris = [
    baris[1]
    for baris in cursor.execute(
        "PRAGMA table_info(qris_transactions)"
    )
]

for kolom in ("chat_id", "message_id"):

    if kolom not in kolom_qris:

        cursor.execute(
            f"ALTER TABLE qris_transactions ADD COLUMN {kolom} INTEGER"
        )


db.commit()


# ============================================================
# DATABASE HELPER
# ============================================================

def pembayaran_sudah_lunas(nama, bulan):

    cursor.execute("""
        SELECT id
        FROM pembayaran
        WHERE nama = ?
        AND bulan = ?
        LIMIT 1
    """, (
        nama,
        bulan
    ))

    return cursor.fetchone() is not None


def simpan_pesan_qr(trxid, pesan):

    cursor.execute("""
        UPDATE qris_transactions
        SET chat_id = ?, message_id = ?
        WHERE trxid = ?
    """, (
        pesan.chat_id,
        pesan.message_id,
        trxid
    ))

    db.commit()


def get_pesan_qr(trxid):

    cursor.execute("""
        SELECT chat_id, message_id
        FROM qris_transactions
        WHERE trxid = ?
    """, (
        trxid,
    ))

    return cursor.fetchone() or (None, None)


def get_qris_transaction(trxid):

    cursor.execute("""
        SELECT
            id,
            trxid,
            transaction_id,
            nama,
            bulan,
            nominal,
            status,
            refcode,
            channel,
            created_at,
            paid_at
        FROM qris_transactions
        WHERE trxid = ?
        LIMIT 1
    """, (
        trxid,
    ))

    return cursor.fetchone()


# ============================================================
# MENU
# ============================================================

def menu():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "💸 Bayar Iuran",
                callback_data="bayar"
            )
        ],

        [
            InlineKeyboardButton(
                "📊 Progress",
                callback_data="progress"
            ),

            InlineKeyboardButton(
                "📋 Rekap",
                callback_data="rekap"
            )
        ],

        [
            InlineKeyboardButton(
                "⚠️ Tunggakan",
                callback_data="tunggakan"
            )
        ],

    ])


def tombol_kembali(target):

    return [
        [
            InlineKeyboardButton(
                "⬅️ Kembali",
                callback_data=target
            )
        ]
    ]


def tombol_transaksi(trxid):

    return [

        [
            InlineKeyboardButton(
                "🔄 Cek Pembayaran",
                callback_data=f"cekqr|{trxid}"
            )
        ],

        [
            InlineKeyboardButton(
                "✅ Tandai Lunas (Manual)",
                callback_data=f"lunas|{trxid}"
            )
        ],

    ]


# ============================================================
# FORMAT & TAMPILAN
# ============================================================

def rupiah(angka):

    # 1800000 -> Rp1.800.000
    return "Rp" + f"{angka:,}".replace(",", ".")


async def tampilkan(
    query,
    teks,
    reply_markup=None
):

    # Pesan foto (QRIS) tidak punya teks untuk diedit,
    # jadi kirim pesan baru.

    try:

        if query.message.photo:

            await query.message.reply_text(
                teks,
                reply_markup=reply_markup
            )

        else:

            await query.edit_message_text(
                teks,
                reply_markup=reply_markup
            )

    except BadRequest as e:

        # Tombol yang sama ditekan dua kali
        if "not modified" not in str(e):
            raise


async def pembayaran_selesai(
    bot,
    trxid,
    query=None
):

    # QRIS dihapus, diganti pesan
    # PEMBAYARAN SELESAI + progress dana terbaru.
    # query=None -> dipanggil dari cek otomatis.

    teks = (
        teks_berhasil(trxid)
        + teks_progress()
    )


    chat_id, message_id = get_pesan_qr(
        trxid
    )

    # Transaksi lama (sebelum ID pesan disimpan)
    if (
        not message_id
        and query
        and query.message.photo
    ):

        chat_id = query.message.chat_id

        message_id = query.message.message_id


    if message_id:

        try:

            await bot.delete_message(
                chat_id,
                message_id
            )

        except BadRequest:

            # Tidak bisa dihapus (mis. pesan > 48 jam):
            # minimal buang tombolnya supaya QR tidak dipakai lagi.

            try:

                await bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption="✅ QRIS ini sudah dibayar.",
                    reply_markup=None
                )

            except BadRequest:

                pass


    # Ditekan dari layar teks -> ganti layar itu
    if query and not query.message.photo:

        await tampilkan(
            query,
            teks,
            reply_markup=menu()
        )

        return


    await bot.send_message(
        chat_id or query.message.chat_id,
        teks,
        reply_markup=menu()
    )


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        f"""
🏡 VILLA 360

Tabungan Villa 2027

💰 Iuran:
{rupiah(IURAN)} / bulan

🎯 Target:
{rupiah(TARGET)}

Silahkan pilih menu:
""",

        reply_markup=menu()

    )


# ============================================================
# GENERATE TRXID
# ============================================================

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

    return (
        f"{tahun}{nomor_bulan:02d}"
        + nama_bersih
    )


# ============================================================
# GENERATE QRIS
# ============================================================

async def generate_qris(
    nama,
    bulan
):

    trxid = buat_trxid(nama, bulan)

    payload = {

        "judul":
            f"Payment {nama} V360",

        # Format provider: "Oktober 2026"
        "keterangan":
            f"{bulan} {PERIODE[bulan][0]}",

        "trxid":
            trxid

    }

    async with httpx.AsyncClient(
        timeout=30
    ) as client:

        response = await client.post(

            QRIS_URL,

            json=payload

        )

        response.raise_for_status()

        result = response.json()


    # Cek response provider

    if not result.get("success"):

        # Detail lengkap untuk dikirim ke provider saat debugging
        print("QRIS REQUEST :", payload)
        print("QRIS HTTP    :", response.status_code)
        print("QRIS RESPONSE:", result)

        raise RuntimeError(
            result.get(
                "msg",
                "QRIS gagal dibuat"
            )
        )


    data = result.get("data")

    if not data:

        raise RuntimeError(
            "Response QRIS tidak mempunyai data"
        )


    transaction_id = data.get(
        "transactionId"
    )

    amount = data.get(
        "amount"
    )

    qr_content = data.get(
        "qrContent"
    )


    if not transaction_id:

        raise RuntimeError(
            "transactionId tidak ditemukan"
        )


    if not qr_content:

        raise RuntimeError(
            "qrContent tidak ditemukan"
        )


    # --------------------------------------------------------
    # Ambil base64 QR
    # --------------------------------------------------------

    if "," in qr_content:

        base64_data = (
            qr_content
            .split(",", 1)[1]
        )

    else:

        base64_data = qr_content


    try:

        qr_bytes = base64.b64decode(
            base64_data
        )

    except Exception as e:

        raise RuntimeError(
            f"QRIS base64 rusak: {e}"
        )


    # --------------------------------------------------------
    # Simpan transaksi sebagai PENDING
    # (setelah QR valid, supaya tidak ada PENDING tanpa QR)
    # --------------------------------------------------------

    sekarang = datetime.now(TIMEZONE)

    # trxid sama untuk anggota+bulan yang sama, jadi QR baru
    # menimpa transaksi PENDING lama. Foto QR lamanya dikembalikan
    # supaya bisa dihapus dari chat.
    qr_lama = get_pesan_qr(trxid)

    cursor.execute("""
        INSERT INTO qris_transactions (

            trxid,
            transaction_id,
            nama,
            bulan,
            nominal,
            status,
            created_at

        )

        VALUES (?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT (trxid) DO UPDATE SET
            transaction_id = excluded.transaction_id,
            nominal = excluded.nominal,
            status = excluded.status,
            created_at = excluded.created_at,
            refcode = NULL,
            channel = NULL,
            paid_at = NULL,
            chat_id = NULL,
            message_id = NULL

    """, (

        trxid,

        transaction_id,

        nama,

        bulan,

        amount or IURAN,

        "PENDING",

        sekarang.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    ))

    db.commit()


    return {

        "trxid": trxid,

        "transaction_id":
            transaction_id,

        "amount":
            amount or IURAN,

        "created_at":
            sekarang.strftime(
                "%d-%m-%Y %H:%M:%S"
            ),

        "qr_bytes":
            qr_bytes,

        "qr_lama":
            qr_lama

    }


async def hapus_qr_lama(bot, qr_lama):

    chat_id, message_id = qr_lama

    if not message_id:
        return

    try:

        await bot.delete_message(
            chat_id,
            message_id
        )

    except BadRequest:

        pass


# ============================================================
# MENANDAI TRANSAKSI SEBAGAI LUNAS
# ============================================================

def tandai_lunas(
    trxid,
    refcode=None,
    channel=None
):

    transaksi = get_qris_transaction(
        trxid
    )

    if not transaksi:

        return False, "TRANSAKSI TIDAK DITEMUKAN"


    (
        transaction_db_id,
        trxid_db,
        transaction_id,
        nama,
        bulan,
        nominal,
        status,
        old_refcode,
        old_channel,
        created_at,
        paid_at

    ) = transaksi


    # Sudah sukses
    if status == "SUCCESS":

        return True, "SUDAH LUNAS"


    # --------------------------------------------------------
    # Masukkan ke pembayaran
    # HANYA setelah SUCCESS
    # --------------------------------------------------------

    if pembayaran_sudah_lunas(
        nama,
        bulan
    ):

        cursor.execute("""
            UPDATE qris_transactions

            SET
                status = 'SUCCESS',
                refcode = ?,
                channel = ?,
                paid_at = ?

            WHERE trxid = ?

        """, (

            refcode,

            channel,

            datetime.now(
                TIMEZONE
            ).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

            trxid

        ))

        db.commit()

        return True, "SUDAH LUNAS"


    sekarang = datetime.now(
        TIMEZONE
    )

    # Update QRIS
    cursor.execute("""
        UPDATE qris_transactions

        SET
            status = 'SUCCESS',
            refcode = ?,
            channel = ?,
            paid_at = ?

        WHERE trxid = ?

    """, (

        refcode,

        channel,

        sekarang.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),

        trxid

    ))


    # Baru masuk pembayaran
    cursor.execute("""
        INSERT INTO pembayaran
        (
            nama,
            bulan,
            nominal
        )

        VALUES (?, ?, ?)

    """, (

        nama,

        bulan,

        nominal

    ))


    db.commit()

    return True, "PEMBAYARAN BERHASIL"


def teks_berhasil(trxid):

    (
        transaction_db_id,
        trxid_db,
        transaction_id,
        nama,
        bulan,
        nominal,
        status,
        refcode,
        channel,
        created_at,
        paid_at

    ) = get_qris_transaction(trxid)


    return f"""
✅ PEMBAYARAN SELESAI

━━━━━━━━━━━━━━

👤 Nama:
{nama}

📅 Bulan:
{bulan}

💰 Nominal:
{rupiah(nominal)}

🆔 ID Transaksi:
{transaction_id}

🔖 TRXID:
{trxid}

💳 Channel:
{channel or "-"}

🔖 Refcode:
{refcode or "-"}

🕐 Dibayar:
{paid_at}

━━━━━━━━━━━━━━

Status:
LUNAS ✅
"""


def teks_progress():

    teks = """
📊 PROGRESS VILLA 360

━━━━━━━━━━━━━━

"""

    total = 0


    for nama in ANGGOTA:

        cursor.execute("""
            SELECT COUNT(*)
            FROM pembayaran
            WHERE nama = ?
        """, (
            nama,
        ))


        jumlah = cursor.fetchone()[0]

        total += jumlah * IURAN


        jumlah_bar = min(
            jumlah,
            len(BULAN)
        )


        bar = (
            "█" * jumlah_bar
            +
            "░" *
            (len(BULAN) - jumlah_bar)
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


# ============================================================
# BUTTON HANDLER
# ============================================================

async def button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    data = query.data


    # Callback hanya boleh dijawab SEKALI.
    # Cabang cekqr menjawab sendiri (pakai alert).

    if (
        data.startswith(KHUSUS_ADMIN)
        and update.effective_user.id != ADMIN_ID
    ):

        await query.answer(
            "❌ Pembayaran hanya bisa dilakukan Peri",
            show_alert=True
        )

        return


    if not data.startswith("cekqr|"):

        await query.answer()


    # ========================================================
    # KEMBALI
    # ========================================================

    if data == "kembali":

        await tampilkan(
            query,

            """
🏡 VILLA 360

Pilih menu:
""",

            reply_markup=menu()

        )

        return


    # ========================================================
    # BAYAR
    # ========================================================

    if data == "bayar":

        tombol = []


        for nama in ANGGOTA:

            tombol.append([

                InlineKeyboardButton(

                    nama,

                    callback_data=f"nama|{nama}"

                )

            ])


        tombol += tombol_kembali(
            "kembali"
        )


        await tampilkan(
            query,

            """
💸 BAYAR IURAN

Pilih nama:
""",

            reply_markup=
            InlineKeyboardMarkup(
                tombol
            )

        )

        return


    # ========================================================
    # PILIH NAMA
    # ========================================================

    if data.startswith("nama|"):

        nama = data.split(
            "|",
            1
        )[1]


        context.user_data["nama"] = nama


        tombol = []


        for bulan in BULAN:

            tombol.append([

                InlineKeyboardButton(

                    bulan,

                    callback_data=
                    f"bulan|{bulan}"

                )

            ])


        tombol += tombol_kembali(
            "bayar"
        )


        await tampilkan(
            query,

            f"""
💸 BAYAR IURAN

👤 Nama:
{nama}

Pilih bulan:
""",

            reply_markup=
            InlineKeyboardMarkup(
                tombol
            )

        )

        return


    # ========================================================
    # PILIH BULAN
    # ========================================================

    if data.startswith("bulan|"):

        bulan = data.split(
            "|",
            1
        )[1]


        nama = context.user_data.get(
            "nama"
        )


        if not nama:

            await tampilkan(
                query,

                "❌ Nama belum dipilih.",

                reply_markup=menu()

            )

            return


        # ----------------------------------------------------
        # Cek pembayaran yang sudah LUNAS
        # ----------------------------------------------------

        if pembayaran_sudah_lunas(
            nama,
            bulan
        ):

            await tampilkan(
                query,

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

                reply_markup=menu()

            )

            return


        # ----------------------------------------------------
        # Cek transaksi PENDING
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                trxid,
                transaction_id,
                nominal,
                created_at
            FROM qris_transactions
            WHERE nama = ?
            AND bulan = ?
            AND status = 'PENDING'
            ORDER BY id DESC
            LIMIT 1
        """, (

            nama,

            bulan

        ))


        pending = cursor.fetchone()


        if pending:

            trxid = pending[0]

            transaction_id = pending[1]

            nominal = pending[2]

            created_at = pending[3]


            await tampilkan(
                query,

                f"""
💳 TRANSAKSI MASIH MENUNGGU

👤 Nama:
{nama}

📅 Bulan:
{bulan}

💰 Nominal:
{rupiah(nominal)}

🆔 ID Transaksi:
{transaction_id}

🔖 TRXID:
{trxid}

🕐 Dibuat:
{created_at}

⏳ Status:
MENUNGGU PEMBAYARAN
""",

                reply_markup=
                InlineKeyboardMarkup([

                    *tombol_transaksi(trxid),

                    [
                        InlineKeyboardButton(
                            "🔄 Buat QR Baru",
                            callback_data=
                            f"buatqr|{nama}|{bulan}"
                        )
                    ],

                    [
                        InlineKeyboardButton(
                            "⬅️ Kembali",
                            callback_data="bayar"
                        )
                    ]

                ])

            )

            return


        # ----------------------------------------------------
        # Generate QR
        # ----------------------------------------------------

        await tampilkan(
            query,
            "⏳ Sedang membuat QRIS..."
        )


        try:

            qris = await generate_qris(

                nama,

                bulan

            )

        except Exception as e:

            print(
                "ERROR GENERATE QRIS:",
                repr(e)
            )

            await tampilkan(
                query,

                f"""
❌ GAGAL MEMBUAT QRIS

{str(e)}
""",

                reply_markup=menu()

            )

            return


        caption = f"""
💳 PEMBAYARAN QRIS

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


        pesan_qr = await query.message.reply_photo(

            photo=io.BytesIO(
                qris["qr_bytes"]
            ),

            caption=caption,

            reply_markup=
            InlineKeyboardMarkup(
                tombol_transaksi(qris["trxid"])
                + tombol_kembali("bayar")
            )

        )

        simpan_pesan_qr(
            qris["trxid"],
            pesan_qr
        )

        await hapus_qr_lama(
            context.bot,
            qris["qr_lama"]
        )

        return


    # ========================================================
    # BUAT QR BARU
    # ========================================================

    if data.startswith("buatqr|"):

        bagian = data.split(
            "|",
            2
        )


        nama = bagian[1]

        bulan = bagian[2]


        await tampilkan(
            query,
            "⏳ Membuat QRIS baru..."
        )


        try:

            qris = await generate_qris(
                nama,
                bulan
            )

        except Exception as e:

            await tampilkan(
                query,

                f"""
❌ GAGAL

{str(e)}
""",

                reply_markup=menu()

            )

            return


        caption = f"""
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
"""


        pesan_qr = await query.message.reply_photo(

            photo=io.BytesIO(
                qris["qr_bytes"]
            ),

            caption=caption,

            reply_markup=
            InlineKeyboardMarkup(
                tombol_transaksi(qris["trxid"])
                + tombol_kembali("bayar")
            )

        )

        simpan_pesan_qr(
            qris["trxid"],
            pesan_qr
        )

        await hapus_qr_lama(
            context.bot,
            qris["qr_lama"]
        )

        return


    # ========================================================
    # CEK PEMBAYARAN
    # ========================================================

    if data.startswith("cekqr|"):

        trxid = data.split(
            "|",
            1
        )[1]


        transaksi = get_qris_transaction(
            trxid
        )


        if not transaksi:

            await query.answer(

                "❌ Transaksi tidak ditemukan",

                show_alert=True

            )

            return


        (
            transaction_db_id,
            trxid_db,
            transaction_id,
            nama,
            bulan,
            nominal,
            status,
            refcode,
            channel,
            created_at,
            paid_at

        ) = transaksi


        # Sudah sukses
        if status == "SUCCESS":

            await query.answer(
                "✅ Pembayaran sudah berhasil",
                show_alert=True
            )

            await pembayaran_selesai(
                context.bot,
                trxid,
                query
            )

            return


        # ----------------------------------------------------
        # Belum bayar (push dari provider belum masuk)
        # ----------------------------------------------------

        await query.answer(

            "⏳ Pembayaran belum diterima",

            show_alert=True

        )

        return


    # ========================================================
    # TANDAI LUNAS MANUAL
    # ========================================================
    #
    # Dipakai selama provider belum punya endpoint
    # cek status. Peri cek mutasi/notifikasi dulu,
    # baru tekan tombol ini.

    if data.startswith("lunas|"):

        trxid = data.split(
            "|",
            1
        )[1]


        berhasil, pesan = tandai_lunas(
            trxid,
            channel="MANUAL"
        )


        if not berhasil:

            await tampilkan(
                query,
                f"❌ {pesan}",
                reply_markup=menu()
            )

            return


        await pembayaran_selesai(
            context.bot,
            trxid,
            query
        )

        return


    # ========================================================
    # PROGRESS
    # ========================================================

    if data == "progress":

        await tampilkan(
            query,
            teks_progress(),
            reply_markup=menu()
        )

        return


    # ========================================================
    # TOTAL DANA
    # ========================================================

    if data == "dana":

        cursor.execute("""
            SELECT SUM(nominal)
            FROM pembayaran
        """)


        total = (
            cursor.fetchone()[0]
            or 0
        )


        await tampilkan(
            query,

            f"""
💰 TOTAL DANA

{rupiah(total)} / {rupiah(TARGET)}

📈 Progress:

{total / TARGET * 100:.1f}%
""",

            reply_markup=menu()

        )

        return


    # ========================================================
    # REKAP
    # ========================================================

    if data == "rekap":

        teks = """
📋 REKAP VILLA 360

━━━━━━━━━━━━━━

"""

        total = 0


        for nama in ANGGOTA:

            cursor.execute("""
                SELECT COUNT(*)
                FROM pembayaran
                WHERE nama = ?
            """, (
                nama,
            ))


            jumlah = cursor.fetchone()[0]

            uang = jumlah * IURAN

            total += uang


            lunas = (
                "🟩" * jumlah
            )

            belum = (
                "⬜" *
                (len(BULAN) - jumlah)
            )


            teks += f"""
👤 {nama}

{lunas}{belum}
{jumlah}/{len(BULAN)}

💰 {rupiah(uang)}

"""


        teks += f"""
━━━━━━━━━━━━━━

💵 Total Kas:

{rupiah(total)}

🎯 Target:

{rupiah(TARGET)}
"""


        await tampilkan(
            query,

            teks,

            reply_markup=menu()

        )

        return


    # ========================================================
    # TUNGGAKAN
    # ========================================================

    if data == "tunggakan":

        teks = "⚠️ TUNGGAKAN\n\n"

        ada = False


        for nama in ANGGOTA:

            belum = []


            for bulan in BULAN:

                if not pembayaran_sudah_lunas(
                    nama,
                    bulan
                ):

                    belum.append(
                        bulan
                    )


            if belum:

                ada = True

                teks += (
                    f"👤 {nama}\n"
                    +
                    ", ".join(belum)
                    +
                    "\n\n"
                )


        if not ada:

            teks += (
                "🎉 Semua anggota "
                "sudah lunas"
            )


        await tampilkan(
            query,

            teks,

            reply_markup=menu()

        )

        return


# ============================================================
# RESET ADMIN
# ============================================================

async def reset(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE

):

    if update.effective_user.id != ADMIN_ID:

        return


    cursor.execute(
        "DELETE FROM pembayaran"
    )

    cursor.execute(
        "DELETE FROM qris_transactions"
    )

    db.commit()


    await update.message.reply_text(

        """
✅ RESET BERHASIL

Semua pembayaran dan transaksi QRIS
sudah dikosongkan.
"""

    )


# ============================================================
# SERVER PUSH QRIS
# ============================================================
#
# Provider mengirim POST setelah QRIS dibayar:
#
# {
#     "status": "success",
#     "trxid": "202610BENOY",
#     "channel": "GOPAY",
#     "refcode": "1730263190"
# }

async def terima_push(request):

    if not secrets.compare_digest(
        request.match_info["secret"],
        PUSH_SECRET
    ):

        return web.json_response(
            {"success": False, "msg": "forbidden"},
            status=403
        )


    if request.method == "GET" and not request.query:

        # Dibuka dari browser untuk cek: server aktif
        return web.json_response(
            {"success": True, "msg": "Server push V360 aktif"}
        )

    if request.method == "GET":

        # Jaga-jaga kalau provider kirim lewat URL:
        # ...?status=success&trxid=...&channel=...&refcode=...
        data = dict(request.query)

    else:

        try:

            data = await request.json()

        except Exception:

            # Jaga-jaga kalau provider kirim form, bukan JSON
            data = dict(await request.post())


    print("PUSH QRIS:", data)


    trxid = data.get("trxid")

    transaksi = (
        get_qris_transaction(trxid)
        if trxid
        else None
    )

    if not transaksi:

        return web.json_response(
            {"success": False, "msg": "trxid tidak ditemukan"},
            status=404
        )


    if str(data.get("status", "")).lower() != "success":

        return web.json_response(
            {"success": True, "msg": "status diabaikan"}
        )


    # Push bisa dikirim ulang; proses hanya sekali
    if transaksi[6] == "PENDING":

        tandai_lunas(
            trxid,
            data.get("refcode"),
            data.get("channel")
        )

        try:

            await pembayaran_selesai(
                request.app["bot"],
                trxid
            )

        except Exception as e:

            # Pembayaran sudah tercatat; jangan sampai
            # provider mengulang push hanya karena Telegram error
            print(
                "ERROR TAMPILAN PUSH:",
                repr(e)
            )


    return web.json_response(
        {"success": True}
    )


@web.middleware
async def log_request_push(request, handler):

    # Catat SEMUA request yang masuk (termasuk path salah),
    # supaya kelihatan apakah provider benar-benar mengirim push.
    # Kode rahasia disamarkan.

    path = request.path.replace(
        PUSH_SECRET,
        "<SECRET>"
    )

    try:

        response = await handler(request)

    except web.HTTPException as e:

        print(f"PUSH MASUK: {request.method} {path} -> {e.status}")

        raise

    print(f"PUSH MASUK: {request.method} {path} -> {response.status}")

    return response


async def mulai_server_push(app):

    server = web.Application(
        middlewares=[log_request_push]
    )

    server["bot"] = app.bot

    server.router.add_post(
        "/qris/push/{secret}",
        terima_push
    )

    server.router.add_get(
        "/qris/push/{secret}",
        terima_push
    )

    runner = web.AppRunner(server)

    await runner.setup()

    app.bot_data["server_push"] = runner

    try:

        await web.TCPSite(
            runner,
            "0.0.0.0",
            PUSH_PORT
        ).start()

    except OSError as e:

        raise RuntimeError(
            f"Port {PUSH_PORT} sudah dipakai.\n"
            "Kemungkinan bot.py masih jalan di terminal lain "
            "(tekan Ctrl+C di sana), atau ganti PUSH_PORT di .env.\n"
            f"Cek: lsof -nP -iTCP:{PUSH_PORT} -sTCP:LISTEN"
        ) from e

    print(
        f"📡 Server push QRIS aktif di port {PUSH_PORT}"
    )


async def stop_server_push(app):

    runner = app.bot_data.get("server_push")

    if runner:

        await runner.cleanup()


# ============================================================
# ERROR HANDLER
# ============================================================

async def tangani_error(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    # Tanpa ini error (mis. Telegram timeout) hilang diam-diam
    # dan tampilan Telegram macet di "Sedang membuat QRIS..."

    print("ERROR BOT:", repr(context.error))

    traceback.print_exception(context.error)

    if (
        isinstance(update, Update)
        and update.effective_chat
    ):

        try:

            await context.bot.send_message(
                update.effective_chat.id,
                f"❌ Terjadi error:\n{context.error}\n\nSilakan coba lagi.",
                reply_markup=menu()
            )

        except Exception:

            pass


# ============================================================
# MAIN
# ============================================================

def main():

    app = (
        Application
        .builder()
        .token(TOKEN)
        # Upload foto QR bisa lebih lama dari default 5 detik
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(15)
        .post_init(mulai_server_push)
        .post_shutdown(stop_server_push)
        .build()
    )


    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )


    app.add_handler(
        CallbackQueryHandler(
            button
        )
    )


    app.add_handler(
        CommandHandler(
            "resetsemuadataanjing",
            reset
        )
    )


    app.add_error_handler(
        tangani_error
    )


    print(
        "🏡 Villa 360 Bot aktif..."
    )


    app.run_polling()


if __name__ == "__main__":

    main()
