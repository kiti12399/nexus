from decimal import Decimal, InvalidOperation

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Contact, Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from keyshop_bot.config import Settings
from keyshop_bot.accounts import InvalidTelegramLinkCode, link_telegram_account, update_account_phone_by_telegram_id
from keyshop_bot.crypto import KeyCipher
from keyshop_bot.enums import OrderStatus, PaymentProvider
from keyshop_bot.formatting import format_money, html_code, html_text, short_order_id
from keyshop_bot.keyboards import (
    BackCallback,
    BuyCallback,
    CheckPaymentCallback,
    PackageCallback,
    PaymentMethodCallback,
    ProductCallback,
    ReportPaymentCallback,
    catalog_keyboard,
    manual_crypto_keyboard,
    payment_method_keyboard,
    packages_keyboard,
    payment_keyboard,
    product_keyboard,
    phone_request_keyboard,
)
from keyshop_bot.models import Order
from keyshop_bot.packages import package_by_code, package_for_product, products_in_package
from keyshop_bot.services import (
    DeliveryConflict,
    OrderNotFound,
    OutOfStock,
    ProductNotFound,
    add_stock_key,
    attach_manual_crypto_payment,
    attach_payment_to_order,
    cancel_order_and_release,
    create_or_update_product,
    create_order_with_reservation,
    deliver_paid_order,
    get_order_by_id_or_prefix,
    get_order_with_product,
    get_recent_orders,
    get_product_by_id,
    get_product_by_slug,
    list_active_products,
    list_pending_orders,
    product_stock_rows,
    set_product_active,
    upsert_customer,
)
from keyshop_bot.yookassa import YooKassaClient, YooKassaError


def build_router(
    settings: Settings,
    session_factory: async_sessionmaker,
    payment_client: YooKassaClient | None,
    cipher: KeyCipher,
) -> Router:
    router = Router()

    def is_admin(user_id: int | None) -> bool:
        return user_id is not None and user_id in settings.admin_ids

    async def notify_admins(bot: Bot, text: str) -> None:
        for admin_id in settings.admin_ids:
            await bot.send_message(admin_id, text)

    async def render_catalog(message_or_query: Message | CallbackQuery) -> None:
        async with session_factory() as session:
            products = await list_active_products(session)
        text = (
            "🧭 <b>Каталог Nexus AI</b>\n\n"
            "Выберите пакет ключей:\n"
            "🚀 <b>Start</b> — быстрый вход и тесты\n"
            "💎 <b>Comfort</b> — баланс цены и возможностей\n"
            "👑 <b>Premium</b> — максимум для серьезной работы"
        )
        if not products:
            text += "\n\nПока товары не добавлены, но разделы уже готовы."
        markup = packages_keyboard(products)

        if isinstance(message_or_query, CallbackQuery):
            await message_or_query.message.edit_text(text, reply_markup=markup)
            await message_or_query.answer()
        else:
            await message_or_query.answer(text, reply_markup=markup)

    async def render_package_catalog(
        message_or_query: Message | CallbackQuery,
        package_code: str,
    ) -> None:
        plan = package_by_code(package_code)
        async with session_factory() as session:
            products = products_in_package(await list_active_products(session), plan.code)
        if products:
            text = (
                f"{plan.emoji} <b>{html_text(plan.title)}</b>\n\n"
                f"{html_text(plan.description)}\n\n"
                "Выберите ключ:"
            )
        else:
            text = (
                f"{plan.emoji} <b>{html_text(plan.title)}</b>\n\n"
                f"{html_text(plan.description)}\n\n"
                "В этом пакете пока нет активных ключей."
            )
        markup = catalog_keyboard(products)

        if isinstance(message_or_query, CallbackQuery):
            await message_or_query.message.edit_text(text, reply_markup=markup)
            await message_or_query.answer()
        else:
            await message_or_query.answer(text, reply_markup=markup)

    async def render_product_card(
        message_or_query: Message | CallbackQuery,
        product_id: int | None = None,
        slug: str | None = None,
    ) -> bool:
        async with session_factory() as session:
            product = None
            if product_id is not None:
                product = await get_product_by_id(session, product_id)
            elif slug is not None:
                product = await get_product_by_slug(session, slug)
            if product is None or not product.is_active:
                if isinstance(message_or_query, CallbackQuery):
                    await message_or_query.answer("Товар недоступен", show_alert=True)
                else:
                    await message_or_query.answer("Товар недоступен. Покажу каталог.")
                    await render_catalog(message_or_query)
                return False

        plan = package_for_product(product)
        description = f"\n\n{html_text(product.description)}" if product.description else ""
        text = (
            f"{plan.emoji} <b>{html_text(product.title)}</b>\n\n"
            f"📦 Пакет: <b>{html_text(plan.title)}</b>\n"
            f"💰 Цена: {format_money(product.price_kopecks, product.currency)}\n"
            f"{description}\n\n"
            "Нажмите «Оплатить», чтобы выбрать способ оплаты."
        )
        back_target = f"package_{plan.code}"
        if isinstance(message_or_query, CallbackQuery):
            await message_or_query.message.edit_text(text, reply_markup=product_keyboard(product, back_target))
            await message_or_query.answer()
        else:
            await message_or_query.answer(text, reply_markup=product_keyboard(product, back_target))
        return True

    @router.message(Command("start"))
    async def start(message: Message, command: CommandObject) -> None:
        if message.from_user is not None:
            async with session_factory() as session:
                async with session.begin():
                    await upsert_customer(
                        session,
                        telegram_id=message.from_user.id,
                        username=message.from_user.username,
                        full_name=message.from_user.full_name,
                    )
        link_code = _link_code_from_start_arg(command.args)
        if link_code is not None:
            await _link_account_by_code(message, link_code)
            return
        slug = _product_slug_from_start_arg(command.args)
        if slug is not None and await render_product_card(message, slug=slug):
            return
        await render_catalog(message)

    @router.message(Command("catalog"))
    async def catalog(message: Message) -> None:
        await render_catalog(message)

    @router.message(Command("link"))
    async def link_account(message: Message, command: CommandObject) -> None:
        code = (command.args or "").strip()
        if not code:
            await message.answer("Формат: /link <код из личного кабинета>")
            return
        await _link_account_by_code(message, code)

    @router.message(Command("phone"))
    async def request_phone(message: Message) -> None:
        if message.from_user is None:
            return
        await message.answer(
            "Отправьте номер кнопкой ниже, и я сохраню его в аккаунт.",
            reply_markup=phone_request_keyboard(),
        )

    @router.message(F.contact)
    async def save_phone(message: Message) -> None:
        if message.from_user is None or message.contact is None:
            return
        if message.contact.user_id is not None and message.contact.user_id != message.from_user.id:
            await message.answer("Нужно отправить свой номер через кнопку контакта.")
            return
        async with session_factory() as session:
            async with session.begin():
                account = await update_account_phone_by_telegram_id(
                    session,
                    message.from_user.id,
                    message.contact.phone_number,
                )
        if account is None:
            await message.answer("Сначала привяжите Telegram к аккаунту через /link <код>.")
            return
        await message.answer("Номер сохранен в аккаунте.", reply_markup=None)

    async def _link_account_by_code(message: Message, code: str) -> None:
        if message.from_user is None:
            return
        try:
            async with session_factory() as session:
                async with session.begin():
                    account = await link_telegram_account(
                        session,
                        code,
                        message.from_user.id,
                        message.from_user.username,
                    )
        except InvalidTelegramLinkCode:
            await message.answer("Код привязки неверный или уже истек. Создайте новый код в личном кабинете.")
            return
        await message.answer(f"Telegram привязан к аккаунту {html_text(account.email)}.")

    @router.callback_query(PackageCallback.filter())
    async def package_details(query: CallbackQuery, callback_data: PackageCallback) -> None:
        await render_package_catalog(query, callback_data.code)

    @router.callback_query(BackCallback.filter())
    async def back_to_catalog(query: CallbackQuery, callback_data: BackCallback) -> None:
        if callback_data.target.startswith("package_"):
            await render_package_catalog(query, callback_data.target.removeprefix("package_"))
            return
        if callback_data.target.startswith("product_"):
            product_id_raw = callback_data.target.removeprefix("product_")
            if product_id_raw.isdigit():
                await render_product_card(query, product_id=int(product_id_raw))
                return
        await render_catalog(query)

    @router.callback_query(ProductCallback.filter())
    async def product_details(query: CallbackQuery, callback_data: ProductCallback) -> None:
        await render_product_card(query, product_id=callback_data.product_id)

    @router.callback_query(BuyCallback.filter())
    async def buy_product(
        query: CallbackQuery,
        callback_data: BuyCallback,
        bot: Bot,
    ) -> None:
        if query.from_user is None:
            await query.answer("Не удалось определить пользователя", show_alert=True)
            return
        await _show_payment_methods(query, callback_data.product_id)

    async def _show_payment_methods(query: CallbackQuery, product_id: int) -> None:
        async with session_factory() as session:
            product = await get_product_by_id(session, product_id)
        if product is None or not product.is_active:
            await query.answer("Товар недоступен", show_alert=True)
            return
        plan = package_for_product(product)
        text = (
            f"💳 <b>Оплата</b>\n\n"
            f"{plan.emoji} {html_text(product.title)}\n"
            f"💰 Сумма: {format_money(product.price_kopecks, product.currency)}\n\n"
            "Выберите способ оплаты:"
        )
        await query.message.edit_text(
            text,
            reply_markup=payment_method_keyboard(product, f"product_{product.id}"),
        )
        await query.answer()

    @router.callback_query(PaymentMethodCallback.filter())
    async def choose_payment_method(
        query: CallbackQuery,
        callback_data: PaymentMethodCallback,
        bot: Bot,
    ) -> None:
        if query.from_user is None:
            await query.answer("Не удалось определить пользователя", show_alert=True)
            return
        if callback_data.method == "crypto":
            await _buy_with_manual_crypto(query, callback_data, bot)
            return
        if callback_data.method == "money":
            if payment_client is not None and settings.payment_provider == PaymentProvider.YOOKASSA:
                await _buy_with_yookassa(query, callback_data, bot)
                return
            await query.answer(
                "Оплата картой временно недоступна. Подбираем новую платежную кассу.",
                show_alert=True,
            )
            return
        await query.answer("Платежный способ не настроен", show_alert=True)

    async def _buy_with_manual_crypto(
        query: CallbackQuery,
        callback_data: BuyCallback | PaymentMethodCallback,
        bot: Bot,
    ) -> None:
        if not settings.crypto_wallet_address:
            await query.answer("Криптокошелек еще не настроен", show_alert=True)
            return
        if not settings.admin_ids:
            await query.answer("Администратор еще не настроен", show_alert=True)
            return

        async with session_factory() as session:
            try:
                async with session.begin():
                    customer = await upsert_customer(
                        session,
                        telegram_id=query.from_user.id,
                        username=query.from_user.username,
                        full_name=query.from_user.full_name,
                    )
                    order = await create_order_with_reservation(
                        session,
                        customer,
                        callback_data.product_id,
                        settings.payment_timeout_minutes,
                        provider=PaymentProvider.MANUAL_CRYPTO,
                    )
                    await session.refresh(order, ["product"])
                async with session.begin():
                    order = await attach_manual_crypto_payment(session, order.id)
                    await session.refresh(order, ["product"])
            except ProductNotFound:
                await query.answer("Товар недоступен", show_alert=True)
                return
            except OutOfStock:
                await query.answer("Ключи закончились", show_alert=True)
                return

        await query.message.edit_text(
            _manual_crypto_payment_text(order, settings),
            reply_markup=manual_crypto_keyboard(order.id),
        )
        await notify_admins(bot, _new_manual_order_admin_text(order, query.from_user.id))
        await query.answer()

    async def _buy_with_yookassa(
        query: CallbackQuery,
        callback_data: BuyCallback | PaymentMethodCallback,
        bot: Bot,
    ) -> None:
        if payment_client is None:
            await query.answer("Оплата картой пока не настроена", show_alert=True)
            return

        order_id: str | None = None
        async with session_factory() as session:
            try:
                async with session.begin():
                    customer = await upsert_customer(
                        session,
                        telegram_id=query.from_user.id,
                        username=query.from_user.username,
                        full_name=query.from_user.full_name,
                    )
                    order = await create_order_with_reservation(
                        session,
                        customer,
                        callback_data.product_id,
                        settings.payment_timeout_minutes,
                        provider=PaymentProvider.YOOKASSA,
                    )
                    order_id = order.id
                    await session.refresh(order, ["product"])
                payment = await payment_client.create_payment(order, order.product)
                async with session.begin():
                    order = await attach_payment_to_order(
                        session,
                        order.id,
                        payment.payment_id,
                        payment.confirmation_url,
                    )
                    await session.refresh(order, ["product"])
            except ProductNotFound:
                await query.answer("Товар недоступен", show_alert=True)
                return
            except OutOfStock:
                await query.answer("Ключи закончились", show_alert=True)
                return
            except YooKassaError as exc:
                if order_id:
                    async with session.begin():
                        order = await get_order_with_product(session, order_id)
                        if order is not None:
                            await cancel_order_and_release(session, order)
                await bot.send_message(
                    query.from_user.id,
                    f"Не получилось создать платеж. Напишите в поддержку.\n{html_code(str(exc))}",
                )
                await query.answer("Ошибка платежной системы", show_alert=True)
                return

        await query.message.edit_text(
            _yookassa_payment_text(order),
            reply_markup=payment_keyboard(order.payment_url or "", order.id),
        )
        await query.answer()

    @router.callback_query(ReportPaymentCallback.filter())
    async def report_manual_payment(
        query: CallbackQuery,
        callback_data: ReportPaymentCallback,
        bot: Bot,
    ) -> None:
        async with session_factory() as session:
            order = await get_order_with_product(session, callback_data.order_id)
        if order is None or order.telegram_id != query.from_user.id:
            await query.answer("Заказ не найден", show_alert=True)
            return
        if order.status == OrderStatus.DELIVERED:
            await query.answer("Ключ уже был выдан", show_alert=True)
            return
        if not settings.admin_ids:
            await query.answer("Администратор пока не настроен", show_alert=True)
            return

        await notify_admins(bot, _reported_payment_admin_text(order, query.from_user.id, None))
        await query.message.answer(
            "Отметка об оплате отправлена администратору. "
            "После проверки поступления ключ придет сюда автоматически."
        )
        await query.answer("Отправлено администратору")

    @router.message(Command("paid"))
    async def paid(message: Message, command: CommandObject, bot: Bot) -> None:
        if message.from_user is None:
            return
        order_ref, comment = _parse_paid_args(command.args)
        if not order_ref:
            await message.answer("Формат: /paid <order_id> <tx_hash или комментарий>")
            return
        async with session_factory() as session:
            order = await get_order_by_id_or_prefix(session, order_ref)
        if order is None or order.telegram_id != message.from_user.id:
            await message.answer("Заказ не найден.")
            return
        if not settings.admin_ids:
            await message.answer("Администратор пока не настроен.")
            return
        await notify_admins(bot, _reported_payment_admin_text(order, message.from_user.id, comment))
        await message.answer("Информация об оплате отправлена администратору.")

    @router.callback_query(CheckPaymentCallback.filter())
    async def check_payment(
        query: CallbackQuery,
        callback_data: CheckPaymentCallback,
    ) -> None:
        if payment_client is None:
            await query.answer("Автопроверка платежей пока не настроена", show_alert=True)
            return
        async with session_factory() as session:
            async with session.begin():
                order = await get_order_with_product(session, callback_data.order_id)
                if order is None or order.telegram_id != query.from_user.id:
                    await query.answer("Заказ не найден", show_alert=True)
                    return
                if order.provider_payment_id is None:
                    await query.answer("Платеж еще не создан", show_alert=True)
                    return

        try:
            payment = await payment_client.get_payment(order.provider_payment_id)
        except YooKassaError:
            await query.answer("Не удалось проверить платеж", show_alert=True)
            return

        status = payment.get("status")
        if status == "succeeded":
            await _deliver_order_message(query.message, callback_data.order_id, cipher, session_factory)
            await query.answer("Оплата подтверждена")
            return
        if status == "canceled":
            async with session_factory() as session:
                async with session.begin():
                    order = await get_order_with_product(session, callback_data.order_id)
                    if order is not None:
                        await cancel_order_and_release(session, order)
            await query.message.answer("Платеж отменен. Можно оформить новый заказ.")
            await query.answer()
            return

        await query.answer("Платеж еще не завершен", show_alert=True)

    @router.message(Command("my_orders"))
    async def my_orders(message: Message) -> None:
        if message.from_user is None:
            return
        async with session_factory() as session:
            orders = await get_recent_orders(session, message.from_user.id)
        if not orders:
            await message.answer("У вас пока нет заказов.")
            return
        lines = ["<b>Последние заказы</b>"]
        for order in orders:
            lines.append(
                f"#{short_order_id(order.id)} - {html_text(order.product.title)} - "
                f"{format_money(order.amount_kopecks, order.currency)} - {order.status}"
            )
        await message.answer("\n".join(lines))

    @router.message(Command("admin"))
    async def admin(message: Message) -> None:
        if not is_admin(message.from_user.id if message.from_user else None):
            await message.answer("Команда доступна только администратору.")
            return
        await message.answer(
            "<b>Админ-команды</b>\n"
            "/add_product &lt;slug&gt; &lt;price_rub&gt; &lt;title&gt;\n"
            "/enable_product &lt;slug&gt;\n"
            "/disable_product &lt;slug&gt;\n"
            "/add_key &lt;slug&gt; &lt;api_key&gt;\n"
            "/stock\n"
            "/orders\n"
            "/approve_order &lt;order_id&gt;\n"
            "/reject_order &lt;order_id&gt;"
        )

    @router.message(Command("add_product"))
    async def add_product(message: Message, command: CommandObject) -> None:
        if not is_admin(message.from_user.id if message.from_user else None):
            await message.answer("Команда доступна только администратору.")
            return
        try:
            slug, price_kopecks, title = _parse_add_product_args(command.args)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        async with session_factory() as session:
            async with session.begin():
                product = await create_or_update_product(
                    session,
                    slug=slug,
                    price_kopecks=price_kopecks,
                    title=title,
                )
        await message.answer(
            f"Товар сохранен: {product.slug} - {format_money(product.price_kopecks)}"
        )

    @router.message(Command("enable_product"))
    async def enable_product(message: Message, command: CommandObject) -> None:
        await _set_product_activity(message, command, True)

    @router.message(Command("disable_product"))
    async def disable_product(message: Message, command: CommandObject) -> None:
        await _set_product_activity(message, command, False)

    async def _set_product_activity(
        message: Message,
        command: CommandObject,
        active: bool,
    ) -> None:
        if not is_admin(message.from_user.id if message.from_user else None):
            await message.answer("Команда доступна только администратору.")
            return
        slug = (command.args or "").strip()
        if not slug:
            await message.answer("Формат: /enable_product <slug>")
            return
        try:
            async with session_factory() as session:
                async with session.begin():
                    product = await set_product_active(session, slug, active)
        except ProductNotFound:
            await message.answer("Товар не найден.")
            return
        state = "включен" if product.is_active else "выключен"
        await message.answer(f"Товар {product.slug} {state}.")

    @router.message(Command("add_key"))
    async def add_key(message: Message, command: CommandObject) -> None:
        if not is_admin(message.from_user.id if message.from_user else None):
            await message.answer("Команда доступна только администратору.")
            return
        try:
            slug, plain_key = _parse_add_key_args(command.args)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        try:
            async with session_factory() as session:
                async with session.begin():
                    key = await add_stock_key(session, cipher, slug, plain_key)
        except ProductNotFound:
            await message.answer("Товар не найден.")
            return
        await message.answer(f"Ключ добавлен на склад: #{key.id}.")

    @router.message(Command("stock"))
    async def stock(message: Message) -> None:
        if not is_admin(message.from_user.id if message.from_user else None):
            await message.answer("Команда доступна только администратору.")
            return
        async with session_factory() as session:
            rows = await product_stock_rows(session)
        if not rows:
            await message.answer("Товаров пока нет.")
            return
        lines = ["<b>Склад</b>"]
        for product, available, reserved, sold in rows:
            active = "on" if product.is_active else "off"
            lines.append(
                f"{product.slug} ({active}): доступно {available}, резерв {reserved}, продано {sold}"
            )
        await message.answer("\n".join(lines))

    @router.message(Command("orders"))
    async def orders(message: Message) -> None:
        if not is_admin(message.from_user.id if message.from_user else None):
            await message.answer("Команда доступна только администратору.")
            return
        async with session_factory() as session:
            pending = await list_pending_orders(session)
        if not pending:
            await message.answer("Ожидающих заказов нет.")
            return
        lines = ["<b>Ожидают подтверждения</b>"]
        for order in pending:
            lines.append(
                f"#{short_order_id(order.id)} / {html_code(order.id)}\n"
                f"{html_text(order.product.title)} - {format_money(order.amount_kopecks, order.currency)}\n"
                f"Покупатель: <code>{order.telegram_id}</code>\n"
                f"Выдать: /approve_order {short_order_id(order.id)}\n"
                f"Отменить: /reject_order {short_order_id(order.id)}"
            )
        await message.answer("\n\n".join(lines))

    @router.message(Command("approve_order"))
    async def approve_order(message: Message, command: CommandObject) -> None:
        if not is_admin(message.from_user.id if message.from_user else None):
            await message.answer("Команда доступна только администратору.")
            return
        order_ref = (command.args or "").strip()
        if not order_ref:
            await message.answer("Формат: /approve_order <order_id>")
            return
        async with session_factory() as session:
            try:
                async with session.begin():
                    order = await get_order_by_id_or_prefix(session, order_ref)
                    if order is None:
                        raise OrderNotFound(order_ref)
                    plain_key, first_delivery = await deliver_paid_order(session, cipher, order)
            except OrderNotFound:
                await message.answer("Заказ не найден или короткий ID неоднозначный.")
                return
            except DeliveryConflict as exc:
                await message.answer(f"Не удалось выдать ключ: {html_code(str(exc))}")
                return
        prefix = "Оплата подтверждена. Ваш API-ключ:" if first_delivery else "Ключ уже был выдан ранее:"
        await message.bot.send_message(order.telegram_id, f"{prefix}\n{html_code(plain_key)}")
        await message.answer(f"Заказ #{short_order_id(order.id)} подтвержден, ключ отправлен.")

    @router.message(Command("reject_order"))
    async def reject_order(message: Message, command: CommandObject) -> None:
        if not is_admin(message.from_user.id if message.from_user else None):
            await message.answer("Команда доступна только администратору.")
            return
        order_ref = (command.args or "").strip()
        if not order_ref:
            await message.answer("Формат: /reject_order <order_id>")
            return
        async with session_factory() as session:
            async with session.begin():
                order = await get_order_by_id_or_prefix(session, order_ref)
                if order is None:
                    await message.answer("Заказ не найден или короткий ID неоднозначный.")
                    return
                await cancel_order_and_release(session, order)
                telegram_id = order.telegram_id
        await message.bot.send_message(
            telegram_id,
            "Заказ отменен администратором. Если вы уже отправили оплату, напишите в поддержку.",
        )
        await message.answer(f"Заказ #{short_order_id(order.id)} отменен, резерв освобожден.")

    return router


async def _deliver_order_message(
    message: Message,
    order_id: str,
    cipher: KeyCipher,
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        try:
            async with session.begin():
                order = await get_order_with_product(session, order_id)
                if order is None:
                    raise OrderNotFound(order_id)
                plain_key, first_delivery = await deliver_paid_order(session, cipher, order)
        except DeliveryConflict:
            await message.answer(
                "Оплата прошла, но ключ не удалось выдать автоматически. "
                "Администратор уже должен обработать заказ вручную."
            )
            return
    prefix = "Ваш API-ключ:" if first_delivery else "Ключ уже был выдан ранее:"
    await message.answer(f"{prefix}\n{html_code(plain_key)}")


def _yookassa_payment_text(order: Order) -> str:
    return (
        f"<b>Заказ #{short_order_id(order.id)}</b>\n"
        f"{html_text(order.product.title)}\n"
        f"Сумма: {format_money(order.amount_kopecks, order.currency)}\n\n"
        "Нажмите кнопку оплаты. После оплаты вернитесь сюда и нажмите "
        "\"Проверить оплату\". Обычно webhook выдаст ключ автоматически."
    )


def _manual_crypto_payment_text(order: Order, settings: Settings) -> str:
    note = f"\nКомментарий: {html_text(settings.crypto_payment_note)}" if settings.crypto_payment_note else ""
    return (
        f"<b>Заказ #{short_order_id(order.id)}</b>\n"
        f"{html_text(order.product.title)}\n"
        f"Стоимость: {format_money(order.amount_kopecks, order.currency)}\n\n"
        "<b>Оплата криптовалютой</b>\n"
        f"Актив: {html_text(settings.crypto_asset)}\n"
        f"Сеть: {html_text(settings.crypto_network)}\n"
        f"Кошелек: {html_code(settings.crypto_wallet_address)}\n"
        f"К оплате: {_crypto_amount_text(order, settings)}"
        f"{note}\n\n"
        "После перевода нажмите \"Я оплатил\". Администратор проверит поступление "
        "и отправит API-ключ в этот чат."
    )


def _crypto_amount_text(order: Order, settings: Settings) -> str:
    if settings.crypto_rub_per_unit is None:
        return f"эквивалент {format_money(order.amount_kopecks, order.currency)}"
    amount_rub = Decimal(order.amount_kopecks) / Decimal(100)
    crypto_amount = amount_rub / settings.crypto_rub_per_unit
    return f"{crypto_amount:.6f} {html_text(settings.crypto_asset)}"


def _new_manual_order_admin_text(order: Order, telegram_id: int) -> str:
    return (
        "<b>Новый крипто-заказ</b>\n"
        f"Заказ: {html_code(order.id)}\n"
        f"Покупатель: <code>{telegram_id}</code>\n"
        f"Товар: {html_text(order.product.title)}\n"
        f"Сумма: {format_money(order.amount_kopecks, order.currency)}\n"
        f"Выдать после проверки: /approve_order {short_order_id(order.id)}\n"
        f"Отменить: /reject_order {short_order_id(order.id)}"
    )


def _reported_payment_admin_text(
    order: Order,
    telegram_id: int,
    comment: str | None,
) -> str:
    comment_line = f"\nКомментарий/tx: {html_code(comment)}" if comment else ""
    return (
        "<b>Покупатель отметил оплату</b>\n"
        f"Заказ: {html_code(order.id)}\n"
        f"Покупатель: <code>{telegram_id}</code>\n"
        f"Товар: {html_text(order.product.title)}\n"
        f"Сумма: {format_money(order.amount_kopecks, order.currency)}"
        f"{comment_line}\n"
        f"Выдать: /approve_order {short_order_id(order.id)}\n"
        f"Отменить: /reject_order {short_order_id(order.id)}"
    )


def _parse_add_product_args(args: str | None) -> tuple[str, int, str]:
    parts = (args or "").split(maxsplit=2)
    if len(parts) < 3:
        raise ValueError("Формат: /add_product <slug> <price_rub> <title>")
    slug, price_raw, title = parts
    try:
        price = Decimal(price_raw.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("Цена должна быть числом, например 490 или 490.50") from exc
    if price <= 0:
        raise ValueError("Цена должна быть больше нуля.")
    return slug, int(price * 100), title.strip()


def _parse_add_key_args(args: str | None) -> tuple[str, str]:
    parts = (args or "").split(maxsplit=1)
    if len(parts) != 2:
        raise ValueError("Формат: /add_key <slug> <api_key>")
    slug, plain_key = parts
    plain_key = plain_key.strip()
    if not plain_key:
        raise ValueError("Ключ не должен быть пустым.")
    return slug, plain_key


def _parse_paid_args(args: str | None) -> tuple[str | None, str | None]:
    parts = (args or "").split(maxsplit=1)
    if not parts:
        return None, None
    order_ref = parts[0].strip()
    comment = parts[1].strip() if len(parts) > 1 else None
    return order_ref, comment


def _product_slug_from_start_arg(args: str | None) -> str | None:
    value = (args or "").strip()
    if not value:
        return None
    for prefix in ("product_", "p_"):
        if value.startswith(prefix):
            slug = value.removeprefix(prefix).strip()
            return slug or None
    return None


def _link_code_from_start_arg(args: str | None) -> str | None:
    value = (args or "").strip()
    if not value.startswith("link_"):
        return None
    code = value.removeprefix("link_").strip()
    return code or None
