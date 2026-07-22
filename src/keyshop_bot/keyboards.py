from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from keyshop_bot.models import Product


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
                text=product.title,
                callback_data=ProductCallback(product_id=product.id).pack(),
            )
        ]
        for product in products
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_keyboard(product: Product) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Купить",
                    callback_data=BuyCallback(product_id=product.id).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data=BackCallback().pack(),
                )
            ],
        ]
    )


def payment_keyboard(payment_url: str, order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Оплатить", url=payment_url)],
            [
                InlineKeyboardButton(
                    text="Проверить оплату",
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
                    text="Я оплатил",
                    callback_data=ReportPaymentCallback(order_id=order_id).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад в каталог",
                    callback_data=BackCallback().pack(),
                )
            ],
        ]
    )


def phone_request_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Отправить номер", request_contact=True)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Нажмите кнопку ниже",
    )
