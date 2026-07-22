from decimal import Decimal
from pathlib import Path

from aiogram import Bot
from aiohttp import web
from sqlalchemy.ext.asyncio import async_sessionmaker

from keyshop_bot.accounts import (
    AccountError,
    AccountExists,
    AuthRequired,
    InvalidVerificationCode,
    InvalidCredentials,
    account_from_token,
    account_keys,
    account_orders,
    account_payload,
    authenticate_account,
    create_email_verification,
    create_account_session,
    create_telegram_link_code,
    key_payload,
    order_payload,
    revoke_account_session,
    update_account_profile,
    verify_email_code,
)
from keyshop_bot.config import Settings
from keyshop_bot.crypto import KeyCipher
from keyshop_bot.emailer import EmailDeliveryError, send_verification_code
from keyshop_bot.formatting import format_money, html_code
from keyshop_bot.models import Product
from keyshop_bot.services import (
    DeliveryConflict,
    available_stock_count,
    cancel_order_and_release,
    deliver_paid_order,
    get_order_by_payment_id,
    get_order_with_product,
    get_product_by_slug,
    list_active_products,
)
from keyshop_bot.yookassa import YooKassaClient, YooKassaError


def create_web_app(
    bot: Bot,
    session_factory: async_sessionmaker,
    payment_client: YooKassaClient | None,
    cipher: KeyCipher,
    settings: Settings,
    bot_username: str,
) -> web.Application:
    @web.middleware
    async def cors_middleware(request: web.Request, handler):
        if request.method == "OPTIONS":
            response = web.Response()
        else:
            response = await handler(request)
        response.headers["Access-Control-Allow-Origin"] = settings.site_cors_origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

    app = web.Application(middlewares=[cors_middleware])

    async def index(_: web.Request) -> web.StreamResponse:
        index_path = Path("index.html")
        if not index_path.exists():
            raise web.HTTPNotFound(text="index.html not found")
        response = web.FileResponse(index_path)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def products(_: web.Request) -> web.Response:
        async with session_factory() as session:
            rows = []
            for product in await list_active_products(session):
                stock = await available_stock_count(session, product.id)
                rows.append(_product_payload(product, stock, bot_username))
        return web.json_response({"bot": _bot_payload(bot_username), "products": rows})

    async def product_details(request: web.Request) -> web.Response:
        slug = request.match_info["slug"]
        async with session_factory() as session:
            product = await get_product_by_slug(session, slug)
            if product is None or not product.is_active:
                raise web.HTTPNotFound(text="Product not found")
            stock = await available_stock_count(session, product.id)
        return web.json_response(
            {"bot": _bot_payload(bot_username), "product": _product_payload(product, stock, bot_username)}
        )

    async def auth_register(request: web.Request) -> web.Response:
        data = await _json_body(request)
        email = str(data.get("email") or "")
        password = str(data.get("password") or "")
        display_name = str(data.get("display_name") or "")
        if "@" not in email or len(password) < 8:
            return web.json_response(
                {"ok": False, "error": "Введите корректный email и пароль от 8 символов."},
                status=400,
            )
        if not settings.smtp_enabled and not settings.email_verification_dev_codes:
            return web.json_response(
                {"ok": False, "error": "Отправка email-кодов еще не настроена."},
                status=503,
            )
        try:
            async with session_factory() as session:
                async with session.begin():
                    _, code = await create_email_verification(
                        session,
                        email,
                        password,
                        display_name,
                    )
                    if settings.smtp_enabled:
                        await send_verification_code(settings, email.strip().lower(), code)
        except AccountExists:
            return web.json_response(
                {"ok": False, "error": "Аккаунт с таким email уже существует."},
                status=409,
            )
        except EmailDeliveryError:
            return web.json_response(
                {
                    "ok": False,
                    "error": "Не удалось отправить код на почту. Проверьте email или SMTP-настройки.",
                },
                status=502,
            )
        dev_code = code if settings.email_verification_dev_codes and not settings.smtp_enabled else None
        return web.json_response(
            {
                "ok": True,
                "verification_required": True,
                "email": email.strip().lower(),
                "dev_code": dev_code,
                "delivery": "email" if settings.smtp_enabled else "dev",
                "message": "Verification code sent" if settings.smtp_enabled else "Verification code generated",
            }
        )

    async def auth_verify(request: web.Request) -> web.Response:
        data = await _json_body(request)
        try:
            async with session_factory() as session:
                async with session.begin():
                    account = await verify_email_code(
                        session,
                        str(data.get("email") or ""),
                        str(data.get("code") or ""),
                    )
                    token, _ = await create_account_session(session, account)
                    payload = account_payload(account)
        except InvalidVerificationCode:
            return web.json_response(
                {"ok": False, "error": "Неверный или просроченный код подтверждения."},
                status=400,
            )
        except AccountExists:
            return web.json_response(
                {"ok": False, "error": "Аккаунт с таким email уже существует."},
                status=409,
            )
        return web.json_response({"ok": True, "token": token, "account": payload})

    async def auth_login(request: web.Request) -> web.Response:
        data = await _json_body(request)
        try:
            async with session_factory() as session:
                async with session.begin():
                    account = await authenticate_account(
                        session,
                        str(data.get("email") or ""),
                        str(data.get("password") or ""),
                    )
                    token, _ = await create_account_session(session, account)
                    payload = account_payload(account)
        except InvalidCredentials:
            return web.json_response(
                {"ok": False, "error": "Неверный email или пароль."},
                status=401,
            )
        return web.json_response({"ok": True, "token": token, "account": payload})

    async def auth_me(request: web.Request) -> web.Response:
        try:
            async with session_factory() as session:
                account = await account_from_token(session, _bearer_token(request))
                return web.json_response({"ok": True, "account": account_payload(account)})
        except AuthRequired:
            return _auth_error()

    async def auth_logout(request: web.Request) -> web.Response:
        async with session_factory() as session:
            async with session.begin():
                await revoke_account_session(session, _bearer_token(request))
        return web.json_response({"ok": True})

    async def update_profile(request: web.Request) -> web.Response:
        data = await _json_body(request)
        try:
            async with session_factory() as session:
                async with session.begin():
                    account = await account_from_token(session, _bearer_token(request))
                    account = await update_account_profile(
                        session,
                        account,
                        str(data.get("display_name") or ""),
                        str(data.get("phone") or ""),
                    )
                    payload = account_payload(account)
        except AuthRequired:
            return _auth_error()
        return web.json_response({"ok": True, "account": payload})

    async def telegram_link(request: web.Request) -> web.Response:
        try:
            async with session_factory() as session:
                async with session.begin():
                    account = await account_from_token(session, _bearer_token(request))
                    code = await create_telegram_link_code(session, account)
        except AuthRequired:
            return _auth_error()
        return web.json_response(
            {
                "ok": True,
                "code": code,
                "bot_username": bot_username,
                "telegram_url": f"https://t.me/{bot_username}?start=link_{code}",
                "expires_in_minutes": 15,
            }
        )

    async def my_orders(request: web.Request) -> web.Response:
        try:
            async with session_factory() as session:
                account = await account_from_token(session, _bearer_token(request))
                rows = await account_orders(session, account.id)
                return web.json_response(
                    {
                        "ok": True,
                        "account": account_payload(account),
                        "orders": [order_payload(order) for order in rows],
                    }
                )
        except AuthRequired:
            return _auth_error()

    async def my_keys(request: web.Request) -> web.Response:
        try:
            async with session_factory() as session:
                account = await account_from_token(session, _bearer_token(request))
                rows = await account_keys(session, account.id)
                return web.json_response(
                    {
                        "ok": True,
                        "account": account_payload(account),
                        "keys": [key_payload(row, cipher) for row in rows],
                    }
                )
        except AuthRequired:
            return _auth_error()
        except AccountError:
            return web.json_response(
                {"ok": False, "error": "Could not load account keys"},
                status=500,
            )

    async def yookassa_webhook(request: web.Request) -> web.Response:
        if payment_client is None:
            return web.json_response({"ok": False, "error": "YooKassa is not enabled"}, status=404)

        payload = await request.json()
        event = payload.get("event")
        payment_object = payload.get("object") or {}
        payment_id = payment_object.get("id")

        if not payment_id:
            return web.json_response({"ok": True})

        try:
            payment = await payment_client.get_payment(payment_id)
        except YooKassaError:
            return web.json_response({"ok": False}, status=502)

        metadata = payment.get("metadata") or {}
        order_id = metadata.get("order_id")
        if not order_id:
            return web.json_response({"ok": True})

        if event == "payment.succeeded" and payment.get("status") == "succeeded":
            await _deliver_from_webhook(
                bot,
                session_factory,
                cipher,
                order_id,
                payment_id,
                settings.admin_ids,
            )
        elif event == "payment.canceled" or payment.get("status") == "canceled":
            await _cancel_from_webhook(bot, session_factory, order_id)

        return web.json_response({"ok": True})

    app.router.add_get("/", index)
    app.router.add_get("/index.html", index)
    app.router.add_get("/health", health)
    app.router.add_get("/api/products", products)
    app.router.add_get("/api/products/{slug}", product_details)
    app.router.add_post("/api/auth/register", auth_register)
    app.router.add_post("/api/auth/verify", auth_verify)
    app.router.add_post("/api/auth/login", auth_login)
    app.router.add_get("/api/auth/me", auth_me)
    app.router.add_post("/api/auth/logout", auth_logout)
    app.router.add_patch("/api/account/profile", update_profile)
    app.router.add_post("/api/account/telegram-link", telegram_link)
    app.router.add_get("/api/account/orders", my_orders)
    app.router.add_get("/api/account/keys", my_keys)
    app.router.add_route("OPTIONS", "/api/products", products)
    app.router.add_route("OPTIONS", "/api/products/{slug}", product_details)
    app.router.add_route("OPTIONS", "/{tail:.*}", _options)
    app.router.add_post("/webhooks/yookassa", yookassa_webhook)
    return app


async def _json_body(request: web.Request) -> dict[str, object]:
    try:
        data = await request.json()
    except Exception as exc:
        raise web.HTTPBadRequest(text="Invalid JSON") from exc
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(text="JSON object expected")
    return data


async def _options(_: web.Request) -> web.Response:
    return web.Response()


def _bearer_token(request: web.Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    return header.split(" ", 1)[1].strip()


def _auth_error() -> web.Response:
    return web.json_response({"ok": False, "error": "Authentication required"}, status=401)


def _bot_payload(bot_username: str) -> dict[str, str]:
    return {
        "username": bot_username,
        "url": f"https://t.me/{bot_username}",
    }


def _product_payload(product: Product, stock: int, bot_username: str) -> dict[str, object]:
    amount = Decimal(product.price_kopecks) / Decimal(100)
    return {
        "id": product.id,
        "slug": product.slug,
        "title": product.title,
        "description": product.description,
        "price_kopecks": product.price_kopecks,
        "price": {
            "amount": f"{amount:.2f}",
            "currency": product.currency,
            "formatted": format_money(product.price_kopecks, product.currency),
        },
        "stock": stock,
        "available": stock > 0,
        "telegram_url": f"https://t.me/{bot_username}?start=product_{product.slug}",
    }


async def _deliver_from_webhook(
    bot: Bot,
    session_factory: async_sessionmaker,
    cipher: KeyCipher,
    order_id: str,
    payment_id: str,
    admin_ids: list[int],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            order = await get_order_with_product(session, order_id)
            if order is None:
                order = await get_order_by_payment_id(session, payment_id)
            if order is None:
                return
            try:
                plain_key, first_delivery = await deliver_paid_order(
                    session,
                    cipher,
                    order,
                    provider_payment_id=payment_id,
                )
            except DeliveryConflict as exc:
                for admin_id in admin_ids:
                    await bot.send_message(
                        admin_id,
                        f"Оплата получена, но заказ {order_id} требует ручной обработки: "
                        f"{html_code(str(exc))}",
                    )
                await bot.send_message(
                    order.telegram_id,
                    "Оплата прошла, но ключ не удалось выдать автоматически. "
                    "Администратор обработает заказ вручную.",
                )
                return

    if first_delivery:
        await bot.send_message(order.telegram_id, f"Оплата получена. Ваш API-ключ:\n{html_code(plain_key)}")


async def _cancel_from_webhook(
    bot: Bot,
    session_factory: async_sessionmaker,
    order_id: str,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            order = await get_order_with_product(session, order_id)
            if order is None:
                return
            await cancel_order_and_release(session, order)
            telegram_id = order.telegram_id
    await bot.send_message(telegram_id, "Платеж отменен. Вы можете оформить новый заказ.")
