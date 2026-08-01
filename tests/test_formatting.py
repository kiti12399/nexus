from keyshop_bot.formatting import display_access_title, format_money, short_order_id
from keyshop_bot.handlers import _product_slug_from_start_arg
from keyshop_bot.models import Product
from keyshop_bot.packages import package_for_product, products_in_package
from keyshop_bot.yookassa import _amount_value


def test_format_money_rub() -> None:
    assert format_money(49050) == "490.50 руб."


def test_amount_value_for_yookassa() -> None:
    assert _amount_value(100) == "1.00"
    assert _amount_value(9999) == "99.99"


def test_short_order_id() -> None:
    assert short_order_id("12345678-aaaa-bbbb") == "12345678"


def test_display_access_title_softens_api_key_wording() -> None:
    assert display_access_title("API Key $5") == "Пакет доступа Claude API"
    assert display_access_title("Claude API ключ") == "Claude API доступ"


def test_product_slug_from_start_arg() -> None:
    assert _product_slug_from_start_arg("product_gpt") == "gpt"
    assert _product_slug_from_start_arg("p_gpt-4o") == "gpt-4o"
    assert _product_slug_from_start_arg(None) is None
    assert _product_slug_from_start_arg("catalog") is None


def test_package_for_product_uses_slug_and_title() -> None:
    start = Product(slug="Start🚀", title="API Key $5", price_kopecks=99900)
    comfort = Product(slug="gemini", title="Comfort Gemini", price_kopecks=149900)
    premium = Product(slug="premium-gpt", title="GPT Premium", price_kopecks=299900)

    assert package_for_product(start).code == "start"
    assert package_for_product(comfort).code == "comfort"
    assert package_for_product(premium).code == "premium"
    assert products_in_package([start, comfort, premium], "comfort") == [comfort]
