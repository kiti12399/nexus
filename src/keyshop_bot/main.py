import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web

from keyshop_bot.config import get_settings
from keyshop_bot.crypto import KeyCipher
from keyshop_bot.db import init_db, make_engine, make_session_factory
from keyshop_bot.enums import PaymentProvider
from keyshop_bot.handlers import build_router
from keyshop_bot.tasks import cleanup_expired_orders_loop
from keyshop_bot.webapp import create_web_app
from keyshop_bot.yookassa import YooKassaClient


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = get_settings()
    engine = make_engine(settings.database_url)
    await init_db(engine)
    session_factory = make_session_factory(engine)

    cipher = KeyCipher(settings.key_encryption_key.get_secret_value())
    bot = Bot(
        settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    payment_client: YooKassaClient | None = None
    runner: web.AppRunner | None = None
    cleanup_task: asyncio.Task | None = None

    if settings.payment_provider == PaymentProvider.YOOKASSA:
        payment_client = YooKassaClient(settings)

    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(settings, session_factory, payment_client, cipher))

    bot_info = await bot.get_me()
    bot_username = settings.bot_username or bot_info.username
    if bot_username is None:
        raise RuntimeError("Bot username is not available")

    web_app = create_web_app(
        bot,
        session_factory,
        payment_client,
        cipher,
        settings,
        bot_username,
    )
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, settings.webapp_host, settings.webapp_port)
    await site.start()
    logging.info("Web app started on %s:%s", settings.webapp_host, settings.webapp_port)

    if payment_client is not None:
        cleanup_task = asyncio.create_task(
            cleanup_expired_orders_loop(
                bot,
                session_factory,
                payment_client,
                cipher,
                settings.admin_ids,
            )
        )

    try:
        await dispatcher.start_polling(bot)
    finally:
        if cleanup_task is not None:
            cleanup_task.cancel()
            await asyncio.gather(cleanup_task, return_exceptions=True)
        if runner is not None:
            await runner.cleanup()
        if payment_client is not None:
            await payment_client.close()
        await bot.session.close()
        await engine.dispose()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
