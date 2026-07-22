import asyncio
import logging

from aiogram import Bot
from sqlalchemy.ext.asyncio import async_sessionmaker

from keyshop_bot.crypto import KeyCipher
from keyshop_bot.formatting import html_code
from keyshop_bot.services import (
    DeliveryConflict,
    cancel_order_and_release,
    deliver_paid_order,
    expire_order_and_release,
    get_order_with_product,
    waiting_orders_expired,
)
from keyshop_bot.yookassa import YooKassaClient, YooKassaError

logger = logging.getLogger(__name__)


async def cleanup_expired_orders_loop(
    bot: Bot,
    session_factory: async_sessionmaker,
    payment_client: YooKassaClient,
    cipher: KeyCipher,
    admin_ids: list[int],
    interval_seconds: int = 60,
) -> None:
    while True:
        try:
            await cleanup_expired_orders(bot, session_factory, payment_client, cipher, admin_ids)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Expired order cleanup failed")
        await asyncio.sleep(interval_seconds)


async def cleanup_expired_orders(
    bot: Bot,
    session_factory: async_sessionmaker,
    payment_client: YooKassaClient,
    cipher: KeyCipher,
    admin_ids: list[int],
) -> None:
    async with session_factory() as session:
        orders = await waiting_orders_expired(session)

    for order in orders:
        payment_status = None
        if order.provider_payment_id:
            try:
                payment = await payment_client.get_payment(order.provider_payment_id)
                payment_status = payment.get("status")
            except YooKassaError:
                logger.warning("Could not fetch payment %s", order.provider_payment_id)
                continue

        async with session_factory() as session:
            async with session.begin():
                fresh_order = await get_order_with_product(session, order.id)
                if fresh_order is None:
                    continue
                if payment_status == "succeeded":
                    try:
                        plain_key, first_delivery = await deliver_paid_order(
                            session,
                            cipher,
                            fresh_order,
                            provider_payment_id=fresh_order.provider_payment_id,
                        )
                    except DeliveryConflict as exc:
                        for admin_id in admin_ids:
                            await bot.send_message(
                                admin_id,
                                f"Оплаченный истекший заказ {fresh_order.id} требует ручной обработки: "
                                f"{html_code(str(exc))}",
                            )
                    else:
                        if first_delivery:
                            await bot.send_message(
                                fresh_order.telegram_id,
                                f"Оплата получена. Ваш API-ключ:\n{html_code(plain_key)}",
                            )
                elif payment_status == "canceled":
                    await cancel_order_and_release(session, fresh_order)
                else:
                    await expire_order_and_release(session, fresh_order)
