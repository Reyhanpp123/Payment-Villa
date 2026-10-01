import httpx

from app.rules import (
    IURAN,
    IURAN_USD_AKTIF,
    IURAN_USD_ANGGOTA,
    IURAN_USD_NOMINAL,
    KURS_USD_URL,
)


def iuran_usd_anggota(nama):

    return (
        IURAN_USD_AKTIF
        and nama == IURAN_USD_ANGGOTA
    )


async def kurs_usd_idr():

    async with httpx.AsyncClient(timeout=15) as client:

        response = await client.get(KURS_USD_URL)

        response.raise_for_status()

        hasil = response.json()

    if hasil.get("result") != "success":
        raise RuntimeError("Kurs USD gagal diambil")

    kurs = (hasil.get("rates") or {}).get("IDR")

    if not kurs:
        raise RuntimeError("Kurs IDR tidak ditemukan")

    return float(kurs)


async def nominal_bayar(nama):

    # Anggota lain: iuran biasa.
    # Peri (kalau flag aktif): $300 × kurs USD→IDR saat ini.

    if not iuran_usd_anggota(nama):
        return IURAN

    kurs = await kurs_usd_idr()

    return max(1, round(IURAN_USD_NOMINAL * kurs))
