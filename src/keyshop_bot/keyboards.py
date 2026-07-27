from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from keyshop_bot.models import Product
from keyshop_bot.packages import PACKAGE_PLANS, package_for_product


class PackageCallback(CallbackData, prefix="pkg"):
    code: str


class ProductCallback(CallbackData, prefix="product"):
    product_id: int


class BuyCallback(CallbackData, prefix="buy"):
    product_id: int


class CheckPaymentCallback(CallbackData, prefix="check"):
    order_id: str


class ReportPaymentCallback(CallbackData, prefix="paid"):
    order_id: str


class BackCallback(CallbackData, prefix="back"):
    target: str = "catalog"


def catalog_keyboard(products: list[Product]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{package_for_product(product).emoji} {product.title}",
                callback_data=ProductCallback(product_id=product.id).pack(),
            )
        ]
        for product in products
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад к пакетам",
                callback_data=BackCallback().pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def packages_keyboard(products: list[Product]) -> InlineKeyboardMarkup:
    counts = {plan.code: 0 for plan in PACKAGE_PLANS}
    for product in products:
        plan = package_for_product(product)
        counts[plan.code] = counts.get(plan.code, 0) + 1

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{plan.emoji} {plan.title} ({counts.get(plan.code, 0)})",
                    callback_data=PackageCallback(code=plan.code).pack(),
                )
            ]
            for plan in PACKAGE_PLANS
        ]
    )


def product_keyboard(product: Product, back_target: str = "catalog") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛒 Купить",
                    callback_data=BuyCallback(product_id=product.id).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=BackCallback(target=back_target).pack(),
                )
            ],
        ]
    )


def payment_keyboard(payment_url: str, order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=payment_url)],
            [
                InlineKeyboardButton(
                    text="🔎 Проверить оплату",
                    callback_data=CheckPaymentCallback(order_id=order_id).pack(),
                )
            ],
        ]
    )


def manual_crypto_keyboard(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Я оплатил",
                    callback_data=ReportPaymentCallback(order_id=order_id).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад в каталог",
                    callback_data=BackCallback().pack(),
                )
            ],
        ]
    )


def phone_request_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Отправить номер", request_contact=True)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Нажмите кнопку ниже",
    )
