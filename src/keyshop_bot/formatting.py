from decimal import Decimal
from html import escape
import re


def format_money(kopecks: int, currency: str = "RUB") -> str:
    amount = Decimal(kopecks) / Decimal(100)
    suffix = "руб." if currency == "RUB" else currency
    return f"{amount:.2f} {suffix}"


def html_code(value: str) -> str:
    return f"<code>{escape(value)}</code>"


def html_text(value: str) -> str:
    return escape(value)


def display_access_title(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return "Пакет доступа Claude API"
    if re.search(r"api\s*key", raw, flags=re.IGNORECASE):
        return "Пакет доступа Claude API"
    cleaned = re.sub(r"API-ключ(?:и|ей|а|ом|ами)?", "API доступ", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"API ключ(?:и|ей|а|ом|ами)?", "API доступ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"ключ(?:и|ей|а|ом|ами)?", "доступ", cleaned, flags=re.IGNORECASE)
    return cleaned.strip() or "Пакет доступа Claude API"


def short_order_id(order_id: str) -> str:
    return order_id.split("-", 1)[0]
