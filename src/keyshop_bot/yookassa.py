from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from aiohttp import BasicAuth, ClientResponseError, ClientSession

from keyshop_bot.config import Settings
from keyshop_bot.models import Order, Product


def _amount_value(kopecks: int) -> str:
    return f"{Decimal(kopecks) / Decimal(100):.2f}"


@dataclass(frozen=True)
class CreatedPayment:
    payment_id: str
    status: str
    confirmation_url: str


class YooKassaError(RuntimeError):
    pass


class YooKassaClient:
    base_url = "https://api.yookassa.ru/v3"

    def __init__(self, settings: Settings) -> None:
        if (
            not settings.yookassa_shop_id
            or settings.yookassa_secret_key is None
            or not settings.yookassa_return_url
        ):
            raise YooKassaError("YooKassa settings are not configured")
        self._auth = BasicAuth(
            settings.yookassa_shop_id,
            settings.yookassa_secret_key.get_secret_value(),
        )
        self._return_url = settings.yookassa_return_url
        self._session = ClientSession(auth=self._auth)

    async def close(self) -> None:
        await self._session.close()

    async def create_payment(self, order: Order, product: Product) -> CreatedPayment:
        payload = {
            "amount": {
                "value": _amount_value(order.amount_kopecks),
                "currency": order.currency,
            },
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": self._return_url,
            },
            "description": f"{product.title} / order {order.id}",
            "metadata": {
                "order_id": order.id,
                "telegram_id": str(order.telegram_id),
                "product_id": str(order.product_id),
            },
        }
        data = await self._request(
            "POST",
            "/payments",
            json=payload,
            headers={"Idempotence-Key": order.id},
        )
        confirmation = data.get("confirmation") or {}
        confirmation_url = confirmation.get("confirmation_url")
        if not confirmation_url:
            raise YooKassaError("YooKassa did not return confirmation_url")
        return CreatedPayment(
            payment_id=data["id"],
            status=data["status"],
            confirmation_url=confirmation_url,
        )

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/payments/{payment_id}")

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            async with self._session.request(method, url, **kwargs) as response:
                response.raise_for_status()
                return await response.json()
        except ClientResponseError as exc:
            raise YooKassaError(
                f"YooKassa API returned HTTP {exc.status}: {exc.message}"
            ) from exc
