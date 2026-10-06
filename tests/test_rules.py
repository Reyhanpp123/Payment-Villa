import re
from datetime import datetime

import pytest

import app.rules as rules
from app.flow import label_bulan, nama_target_bayar, teks_tunggakan
from app.rules import (
    ANGGOTA,
    BULAN,
    TIMEZONE,
    TARGET,
    bulan_berjalan,
    hitung_per_nama,
    nama_anggota_user,
    rupiah,
    teks_progress,
    trxid_acak,
)


def user(depan, belakang=""):

    return {"first_name": depan, "last_name": belakang}


@pytest.mark.parametrize(
    "depan,belakang,diharapkan",
    [
        ("Rey", "", "Reyhan"),
        ("Reyhan", "Prastha", "Reyhan"),
        ("Feri", "", "Peri"),
        ("Ali", "Achay", "Pa Ali"),
        ("Pa", "Ali", "Pa Ali"),
        ("Indra", "Purnama", "Indro"),
        ("Benoy", "", "Benoy"),
        ("Orang", "Asing", None),
    ],
)
def test_nama_anggota_dari_profil(depan, belakang, diharapkan):

    assert nama_anggota_user(user(depan, belakang)) == diharapkan


def test_nama_anggota_tanpa_user():

    assert nama_anggota_user(None) is None
    assert nama_anggota_user({}) is None


def test_trxid_acak_anggota_biasa_dan_peri():

    assert re.fullmatch(r"202611[0-9A-F]{8}", trxid_acak("November"))
    assert re.fullmatch(
        r"202701[0-9A-F]{8}", trxid_acak("Januari", nama="Benoy")
    )
    assert re.fullmatch(
        r"202610PERI[0-9A-F]{6}", trxid_acak("Oktober", nama="Peri")
    )


def test_trxid_acak_melewati_yang_sudah_terpakai(monkeypatch):

    urutan = iter(["aaaaaaaa", "bbbbbbbb"])
    monkeypatch.setattr(
        rules.secrets, "token_hex", lambda n: next(urutan)
    )

    assert trxid_acak("Oktober", dipakai={"202610AAAAAAAA"}) == (
        "202610BBBBBBBB"
    )


def test_rupiah():

    assert rupiah(1800000) == "Rp1.800.000"


def test_bulan_berjalan_dalam_dan_luar_periode():

    dalam = datetime(2026, 10, 6, tzinfo=TIMEZONE)
    luar = datetime(2026, 9, 30, tzinfo=TIMEZONE)

    assert bulan_berjalan(dalam) == "Oktober"
    assert bulan_berjalan(luar) is None


def test_hitung_per_nama_mengabaikan_nama_asing():

    baris = [
        {"nama": "Benoy", "bulan": "Oktober"},
        {"nama": "Benoy", "bulan": "November"},
        {"nama": "Bukan Anggota", "bulan": "Oktober"},
    ]

    hasil = hitung_per_nama(baris)

    assert hasil["Benoy"] == 2
    assert "Bukan Anggota" not in hasil


def test_progress_kosong_dan_penuh():

    kosong = teks_progress(hitung_per_nama([]))
    penuh = teks_progress({nama: len(BULAN) for nama in ANGGOTA})

    assert "0.0%" in kosong
    assert "░" * 10 in kosong
    assert "100.0%" in penuh
    assert "█" * 10 in penuh
    assert rupiah(TARGET) in penuh


def test_label_bulan_meringkas_rentang():

    assert label_bulan([]) == "—"
    assert label_bulan(["Oktober", "November", "Desember"]) == "Okt–Des"
    assert label_bulan(["Oktober", "Desember"]) == "Okt, Des"


def test_tunggakan_semua_lunas_dan_semua_menunggak():

    lunas = [
        {"nama": nama, "bulan": bulan}
        for nama in ANGGOTA
        for bulan in BULAN
    ]

    assert "Semua anggota sudah lunas" in teks_tunggakan(lunas)
    assert teks_tunggakan([]).endswith("Okt–Feb · semua")


def test_nama_target_bayar():

    assert nama_target_bayar("nama|Benoy") == "Benoy"
    assert nama_target_bayar("bulan|Benoy|Oktober") == "Benoy"
    assert nama_target_bayar("buatqr|Benoy|Oktober") == "Benoy"
    assert nama_target_bayar("bulan|Benoy") is None
    assert nama_target_bayar("progress") is None
