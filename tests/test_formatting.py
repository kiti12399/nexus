from keyshop_bot.formatting import format_money, short_order_id
from keyshop_bot.handlers import _product_slug_from_start_arg
from keyshop_bot.yookassa import _amount_value


def test_format_money_rub() -> None:
    assert format_money(49050) == "490.50 руб."


def test_amount_value_for_yookassa() -> None:
    assert _amount_value(100) == "1.00"
    assert _amount_value(9999) == "99.99"


def test_short_order_id() -> None:
    assert short_order_id("12345678-aaaa-bbbb") == "12345678"


def test_product_slug_from_start_arg() -> None:
    assert _product_slug_from_start_arg("product_gpt") == "gpt"
    assert _product_slug_from_start_arg("p_gpt-4o") == "gpt-4o"
    assert _product_slug_from_start_arg(None) is None
    assert _product_slug_from_start_arg("catalog") is None
