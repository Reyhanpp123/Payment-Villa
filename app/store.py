import httpx

from app.rules import sekarang


class Store:

    def __init__(self, url, key):

        self.url = url.rstrip("/")

        self.client = httpx.AsyncClient(
            timeout=20,
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )

    async def close(self):

        await self.client.aclose()

    async def _get(self, tabel, params):

        response = await self.client.get(
            f"{self.url}/rest/v1/{tabel}",
            params=params,
        )

        self._raise(response, tabel)

        return response.json()

    async def _patch(self, tabel, params, isi):

        response = await self.client.patch(
            f"{self.url}/rest/v1/{tabel}",
            params=params,
            headers={"Prefer": "return=representation"},
            json=isi,
        )

        self._raise(response, tabel)

        return response.json()

    def _raise(self, response, tabel):

        if response.status_code >= 400:
            raise RuntimeError(
                f"Supabase {tabel} gagal ({response.status_code}): "
                f"{response.text}"
            )

    async def semua_pembayaran(self):

        return await self._get(
            "pembayaran",
            {"select": "nama,bulan,nominal"},
        )

    async def sudah_lunas(self, nama, bulan):

        baris = await self._get(
            "pembayaran",
            {
                "select": "id",
                "nama": f"eq.{nama}",
                "bulan": f"eq.{bulan}",
                "limit": "1",
            },
        )

        return bool(baris)

    async def get_qris(self, trxid):

        baris = await self._get(
            "qris_transactions",
            {
                "select": "*",
                "trxid": f"eq.{trxid}",
                "limit": "1",
            },
        )

        return baris[0] if baris else None

    async def get_pending(self, nama, bulan):

        baris = await self._get(
            "qris_transactions",
            {
                "select": "trxid,transaction_id,nominal,created_at",
                "nama": f"eq.{nama}",
                "bulan": f"eq.{bulan}",
                "status": "eq.PENDING",
                "order": "id.desc",
                "limit": "1",
            },
        )

        return baris[0] if baris else None

    async def simpan_pending(self, trxid, transaction_id, nama, bulan, nominal):

        # trxid sama untuk anggota+bulan yang sama, jadi QR baru
        # menimpa transaksi PENDING lama.

        response = await self.client.post(
            f"{self.url}/rest/v1/qris_transactions",
            params={"on_conflict": "trxid"},
            headers={
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            json={
                "trxid": trxid,
                "transaction_id": transaction_id,
                "nama": nama,
                "bulan": bulan,
                "nominal": nominal,
                "status": "PENDING",
                "created_at": sekarang().strftime("%Y-%m-%d %H:%M:%S"),
                "refcode": None,
                "channel": None,
                "paid_at": None,
                "chat_id": None,
                "message_id": None,
            },
        )

        self._raise(response, "qris_transactions")

    async def simpan_pesan_qr(self, trxid, chat_id, message_id):

        await self._patch(
            "qris_transactions",
            {"trxid": f"eq.{trxid}"},
            {
                "chat_id": chat_id,
                "message_id": message_id,
            },
        )

    async def tandai_lunas(self, trxid, refcode=None, channel=None):

        transaksi = await self.get_qris(trxid)

        if not transaksi:
            return False, "TRANSAKSI TIDAK DITEMUKAN"

        if transaksi["status"] == "SUCCESS":
            return True, "SUDAH LUNAS"

        sudah = await self.sudah_lunas(
            transaksi["nama"],
            transaksi["bulan"],
        )

        # Kas dicatat dulu. Kalau update status gagal,
        # push ulang masih melihat PENDING dan tidak menulis kas dua kali.
        if not sudah:

            response = await self.client.post(
                f"{self.url}/rest/v1/pembayaran",
                headers={"Prefer": "return=minimal"},
                json={
                    "nama": transaksi["nama"],
                    "bulan": transaksi["bulan"],
                    "nominal": transaksi["nominal"],
                },
            )

            if response.status_code == 409:
                sudah = True
            else:
                self._raise(response, "pembayaran")

        await self._patch(
            "qris_transactions",
            {"trxid": f"eq.{trxid}"},
            {
                "status": "SUCCESS",
                "refcode": refcode,
                "channel": channel,
                "paid_at": sekarang().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )

        if sudah:
            return True, "SUDAH LUNAS"

        return True, "PEMBAYARAN BERHASIL"

    async def get_sesi(self, chat_id, user_id):

        baris = await self._get(
            "sesi",
            {
                "select": "message_id",
                "chat_id": f"eq.{chat_id}",
                "user_id": f"eq.{user_id}",
                "limit": "1",
            },
        )

        return baris[0] if baris else None

    async def simpan_sesi(self, chat_id, user_id, message_id):

        # Satu baris per orang per chat, supaya layar di grup
        # tidak saling menimpa.

        response = await self.client.post(
            f"{self.url}/rest/v1/sesi",
            params={"on_conflict": "chat_id,user_id"},
            headers={
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            json={
                "chat_id": chat_id,
                "user_id": user_id,
                "message_id": message_id,
                "updated_at": sekarang().isoformat(),
            },
        )

        self._raise(response, "sesi")

    async def pindah_sesi(self, chat_id, message_id_lama, message_id_baru):

        if not message_id_lama or not message_id_baru:
            return

        await self._patch(
            "sesi",
            {
                "chat_id": f"eq.{chat_id}",
                "message_id": f"eq.{message_id_lama}",
            },
            {
                "message_id": message_id_baru,
                "updated_at": sekarang().isoformat(),
            },
        )

    async def get_tujuan_pengingat(self):

        baris = await self._get(
            "pengingat_tujuan",
            {
                "select": "chat_id",
                "id": "eq.1",
                "limit": "1",
            },
        )

        return baris[0]["chat_id"] if baris else None

    async def simpan_tujuan_pengingat(self, chat_id):

        response = await self.client.post(
            f"{self.url}/rest/v1/pengingat_tujuan",
            params={"on_conflict": "id"},
            headers={
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            json={
                "id": 1,
                "chat_id": chat_id,
                "updated_at": sekarang().isoformat(),
            },
        )

        self._raise(response, "pengingat_tujuan")

    async def get_pengingat(self, bulan):

        baris = await self._get(
            "pengingat",
            {
                "select": "bulan,status,message_id",
                "bulan": f"eq.{bulan}",
                "limit": "1",
            },
        )

        return baris[0] if baris else None

    async def simpan_pengingat(self, bulan, status, message_id=None):

        response = await self.client.post(
            f"{self.url}/rest/v1/pengingat",
            params={"on_conflict": "bulan"},
            headers={
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            json={
                "bulan": bulan,
                "status": status,
                "message_id": message_id,
                "updated_at": sekarang().isoformat(),
            },
        )

        self._raise(response, "pengingat")

    async def hapus_semua(self):

        for tabel in ("pembayaran", "qris_transactions"):

            response = await self.client.delete(
                f"{self.url}/rest/v1/{tabel}",
                params={"id": "gt.0"},
                headers={"Prefer": "return=minimal"},
            )

            self._raise(response, tabel)
