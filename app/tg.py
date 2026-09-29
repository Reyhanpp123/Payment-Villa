import json

import httpx


class Telegram:

    def __init__(self, token):

        self.base = f"https://api.telegram.org/bot{token}"

        self.client = httpx.AsyncClient(timeout=30)

    async def close(self):

        await self.client.aclose()

    async def call(self, method, payload, ignore=()):

        response = await self.client.post(
            f"{self.base}/{method}",
            json=payload,
        )

        data = response.json()

        if data.get("ok"):
            return data.get("result")

        keterangan = data.get("description", "Telegram gagal")

        if any(bagian in keterangan for bagian in ignore):
            return None

        raise RuntimeError(keterangan)

    async def send_message(self, chat_id, teks, reply_markup=None, reply_to=None):

        payload = {
            "chat_id": chat_id,
            "text": teks,
        }

        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        if reply_to:
            payload["reply_to_message_id"] = reply_to

        return await self.call("sendMessage", payload)

    async def edit_text(self, chat_id, message_id, teks, reply_markup=None):

        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": teks,
        }

        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        return await self.call(
            "editMessageText",
            payload,
            ignore=("message is not modified",),
        )

    async def edit_caption(self, chat_id, message_id, caption, reply_markup):

        try:

            await self.call(
                "editMessageCaption",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "caption": caption,
                    "reply_markup": reply_markup,
                },
            )

        except RuntimeError:

            pass

    async def delete_message(self, chat_id, message_id):

        try:

            await self.call(
                "deleteMessage",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                },
            )

            return True

        except RuntimeError:

            return False

    async def send_photo(self, chat_id, photo, caption, reply_markup=None, reply_to=None):

        data = {
            "chat_id": str(chat_id),
            "caption": caption,
        }

        if reply_to:
            data["reply_to_message_id"] = str(reply_to)

        if reply_markup is not None:
            data["reply_markup"] = json.dumps(reply_markup)

        response = await self.client.post(
            f"{self.base}/sendPhoto",
            data=data,
            files={"photo": ("qris.png", photo, "image/png")},
        )

        hasil = response.json()

        if not hasil.get("ok"):
            raise RuntimeError(
                hasil.get("description", "Telegram gagal mengirim QR")
            )

        return hasil["result"]

    async def copy_message(
        self,
        chat_id,
        from_chat_id,
        message_id,
        caption,
        reply_markup=None,
        reply_to=None,
    ):

        payload = {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id,
            "caption": caption,
        }

        if reply_to:
            payload["reply_to_message_id"] = reply_to

        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        return await self.call("copyMessage", payload)

    async def answer(self, callback_id, teks=None, show_alert=False):

        payload = {"callback_query_id": callback_id}

        if teks:
            payload["text"] = teks
            payload["show_alert"] = show_alert

        await self.call(
            "answerCallbackQuery",
            payload,
            ignore=(
                "query is too old",
                "query ID is invalid",
            ),
        )
