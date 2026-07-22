import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from keyshop_bot.crypto import KeyCipher, new_fernet_key
from keyshop_bot.db import init_db
from keyshop_bot.enums import ApiKeyStatus, OrderStatus
from keyshop_bot.models import ApiKey, Order
from keyshop_bot.services import (
    add_stock_key,
    create_or_update_product,
    create_order_with_reservation,
    deliver_paid_order,
    upsert_customer,
)


@pytest.fixture
async def session_factory() -> async_sessionmaker:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
def cipher() -> KeyCipher:
    return KeyCipher(new_fernet_key())


async def test_order_reserves_and_delivery_sells_key(
    session_factory: async_sessionmaker,
    cipher: KeyCipher,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            product = await create_or_update_product(session, "gpt", 49000, "GPT")
            await add_stock_key(session, cipher, "gpt", "sk-test")
            customer = await upsert_customer(session, 100, "user", "User")
            order = await create_order_with_reservation(session, customer, product.id, 30)
            order_id = order.id
            key_id = order.key_id

    async with session_factory() as session:
        key = await session.get(ApiKey, key_id)
        assert key is not None
        assert key.status == ApiKeyStatus.RESERVED

    async with session_factory() as session:
        async with session.begin():
            fresh_order = await session.get(Order, order_id)
            assert fresh_order is not None
            fresh_order.provider_payment_id = "payment-id"
            plain_key, first_delivery = await deliver_paid_order(
                session,
                cipher,
                fresh_order,
                "payment-id",
            )
            key = await session.get(ApiKey, key_id)

    assert plain_key == "sk-test"
    assert first_delivery is True
    assert fresh_order.status == OrderStatus.DELIVERED
    assert key is not None
    assert key.status == ApiKeyStatus.SOLD
