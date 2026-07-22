from decimal import Decimal
from html import escape


def format_money(kopecks: int, currency: str = "RUB") -> str:
    amount = Decimal(kopecks) / Decimal(100)
    suffix = "руб." if currency == "RUB" else currency
    return f"{amount:.2f} {suffix}"


def html_code(value: str) -> str:
    return f"<code>{escape(value)}</code>"


def html_text(value: str) -> str:
    return escape(value)


def short_order_id(order_id: str) -> str:
    return order_id.split("-", 1)[0]
