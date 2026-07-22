import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from keyshop_bot.accounts import (
    InvalidCredentials,
    InvalidTelegramLinkCode,
    InvalidVerificationCode,
    account_from_token,
    account_keys,
    account_orders,
    authenticate_account,
    create_account_session,
    create_email_verification,
    create_telegram_link_code,
    link_telegram_account,
    register_account,
    update_account_profile,
    update_account_phone_by_telegram_id,
    verify_email_code,
)
from keyshop_bot.crypto import KeyCipher, new_fernet_key
from keyshop_bot.db import init_db
from keyshop_bot.enums import OrderStatus
from keyshop_bot.models import Order
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


async def test_register_login_and_token_auth(session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        async with session.begin():
            account = await register_account(
                session,
                "USER@example.com",
                "very-secret-password",
                "User",
            )
            token, _ = await create_account_session(session, account)

    async with session_factory() as session:
        account = await account_from_token(session, token)
        assert account.email == "user@example.com"

    async with session_factory() as session:
        account = await authenticate_account(
            session,
            "user@example.com",
            "very-secret-password",
        )
        assert account.display_name == "User"


async def test_login_rejects_wrong_password(session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        async with session.begin():
            await register_account(session, "user@example.com", "right-password")

    async with session_factory() as session:
        with pytest.raises(InvalidCredentials):
            await authenticate_account(session, "user@example.com", "wrong-password")


async def test_email_verification_creates_account(session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        async with session.begin():
            _, code = await create_email_verification(
                session,
                "verify@example.com",
                "right-password",
                "Verify",
            )

    async with session_factory() as session:
        async with session.begin():
            with pytest.raises(InvalidVerificationCode):
                await verify_email_code(session, "verify@example.com", "000000")
            account = await verify_email_code(session, "verify@example.com", code)
            assert account.email == "verify@example.com"
            assert account.display_name == "Verify"


async def test_update_profile_saves_phone(session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        async with session.begin():
            account = await register_account(session, "profile@example.com", "right-password", "Old")
            updated = await update_account_profile(session, account, "New Name", "+7 999 123-45-67")
            token, _ = await create_account_session(session, updated)

    async with session_factory() as session:
        account = await account_from_token(session, token)
        assert account.display_name == "New Name"
        assert account.phone == "+7 999 123-45-67"


async def test_update_phone_by_telegram_id(session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        async with session.begin():
            account = await register_account(session, "phone@example.com", "right-password", "Phone User")
            account.telegram_id = 4242
            updated = await update_account_phone_by_telegram_id(session, 4242, "79991234567")

    assert updated is not None
    assert updated.phone == "+79991234567"


async def test_telegram_link_backfills_orders_and_keys(
    session_factory: async_sessionmaker,
    cipher: KeyCipher,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            product = await create_or_update_product(session, "gpt", 49000, "GPT")
            await add_stock_key(session, cipher, "gpt", "sk-test")
            customer = await upsert_customer(session, 1001, "buyer", "Buyer")
            order = await create_order_with_reservation(session, customer, product.id, 30)
            account = await register_account(session, "link@example.com", "very-secret-password", "Link User")
            code = await create_telegram_link_code(session, account)
            order_id = order.id
            account_id = account.id

    async with session_factory() as session:
        async with session.begin():
            linked_account = await link_telegram_account(session, code, 1001, "buyer")
            assert linked_account.telegram_id == 1001
            fresh_order = await session.get(Order, order_id)
            assert fresh_order is not None
            fresh_order.provider_payment_id = "payment-id"
            plain_key, first_delivery = await deliver_paid_order(
                session,
                cipher,
                fresh_order,
                "payment-id",
            )

    assert plain_key == "sk-test"
    assert first_delivery is True

    async with session_factory() as session:
        orders = await account_orders(session, account_id)
        keys = await account_keys(session, account_id)

    assert len(orders) == 1
    assert orders[0].id == order_id
    assert orders[0].status == OrderStatus.DELIVERED
    assert len(keys) == 1
    assert keys[0].order_id == order_id
    assert keys[0].key_ciphertext is not None


async def test_linking_with_invalid_code_fails(session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        async with session.begin():
            account = await register_account(session, "link2@example.com", "very-secret-password", "Link User")

    async with session_factory() as session:
        with pytest.raises(InvalidTelegramLinkCode):
            await link_telegram_account(session, "BADCODE", 1002, "buyer")
