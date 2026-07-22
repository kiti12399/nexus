from datetime import timedelta
from uuid import uuid4

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from keyshop_bot.crypto import KeyCipher
from keyshop_bot.enums import ApiKeyStatus, OrderStatus, PaymentProvider
from keyshop_bot.models import Account, AccountOrder, AccountOwnedKey, ApiKey, Customer, Order, Product, utcnow


class ShopError(RuntimeError):
    pass


class ProductNotFound(ShopError):
    pass


class OutOfStock(ShopError):
    pass


class OrderNotFound(ShopError):
    pass


class PaymentMismatch(ShopError):
    pass


class DeliveryConflict(ShopError):
    pass


async def upsert_customer(
    session: AsyncSession,
    telegram_id: int,
    username: str | None,
    full_name: str,
) -> Customer:
    customer = await session.scalar(
        select(Customer).where(Customer.telegram_id == telegram_id)
    )
    if customer is None:
        customer = Customer(
            telegram_id=telegram_id,
            username=username,
            full_name=full_name,
        )
        session.add(customer)
    else:
        customer.username = username
        customer.full_name = full_name
    await session.flush()
    return customer


async def list_active_products(session: AsyncSession) -> list[Product]:
    result = await session.scalars(
        select(Product)
        .where(Product.is_active.is_(True))
        .order_by(Product.id.asc())
    )
    return list(result)


async def get_product_by_id(session: AsyncSession, product_id: int) -> Product | None:
    return await session.get(Product, product_id)


async def get_product_by_slug(session: AsyncSession, slug: str) -> Product | None:
    return await session.scalar(select(Product).where(Product.slug == slug))


async def available_stock_count(session: AsyncSession, product_id: int) -> int:
    count = await session.scalar(
        select(func.count(ApiKey.id)).where(
            ApiKey.product_id == product_id,
            ApiKey.status == ApiKeyStatus.AVAILABLE,
        )
    )
    return int(count or 0)


async def product_stock_rows(session: AsyncSession) -> list[tuple[Product, int, int, int]]:
    products = await session.scalars(select(Product).order_by(Product.id.asc()))
    rows: list[tuple[Product, int, int, int]] = []
    for product in products:
        available = await _count_keys(session, product.id, ApiKeyStatus.AVAILABLE)
        reserved = await _count_keys(session, product.id, ApiKeyStatus.RESERVED)
        sold = await _count_keys(session, product.id, ApiKeyStatus.SOLD)
        rows.append((product, available, reserved, sold))
    return rows


async def _count_keys(session: AsyncSession, product_id: int, status: ApiKeyStatus) -> int:
    count = await session.scalar(
        select(func.count(ApiKey.id)).where(
            ApiKey.product_id == product_id,
            ApiKey.status == status,
        )
    )
    return int(count or 0)


async def create_or_update_product(
    session: AsyncSession,
    slug: str,
    price_kopecks: int,
    title: str,
    description: str = "",
) -> Product:
    product = await get_product_by_slug(session, slug)
    if product is None:
        product = Product(
            slug=slug,
            price_kopecks=price_kopecks,
            title=title,
            description=description,
            is_active=True,
        )
        session.add(product)
    else:
        product.price_kopecks = price_kopecks
        product.title = title
        product.description = description
        product.is_active = True
    await session.flush()
    return product


async def set_product_active(
    session: AsyncSession,
    slug: str,
    is_active: bool,
) -> Product:
    product = await get_product_by_slug(session, slug)
    if product is None:
        raise ProductNotFound(slug)
    product.is_active = is_active
    await session.flush()
    return product


async def add_stock_key(
    session: AsyncSession,
    cipher: KeyCipher,
    product_slug: str,
    plain_key: str,
) -> ApiKey:
    product = await get_product_by_slug(session, product_slug)
    if product is None:
        raise ProductNotFound(product_slug)
    api_key = ApiKey(
        product_id=product.id,
        ciphertext=cipher.encrypt(plain_key),
        status=ApiKeyStatus.AVAILABLE,
    )
    session.add(api_key)
    await session.flush()
    return api_key


async def create_order_with_reservation(
    session: AsyncSession,
    customer: Customer,
    product_id: int,
    payment_timeout_minutes: int,
    provider: PaymentProvider = PaymentProvider.MANUAL_CRYPTO,
) -> Order:
    product = await session.get(Product, product_id)
    if product is None or not product.is_active:
        raise ProductNotFound(str(product_id))

    key = await session.scalar(
        select(ApiKey)
        .where(
            ApiKey.product_id == product_id,
            ApiKey.status == ApiKeyStatus.AVAILABLE,
        )
        .order_by(ApiKey.id.asc())
        .limit(1)
    )
    if key is None:
        raise OutOfStock(product.slug)

    now = utcnow()
    order = Order(
        id=str(uuid4()),
        customer_id=customer.id,
        telegram_id=customer.telegram_id,
        product_id=product.id,
        key_id=key.id,
        amount_kopecks=product.price_kopecks,
        currency=product.currency,
        status=OrderStatus.NEW,
        provider=provider,
        expires_at=now + timedelta(minutes=payment_timeout_minutes),
    )
    session.add(order)
    key.status = ApiKeyStatus.RESERVED
    key.reserved_order_id = order.id
    key.reserved_until = order.expires_at
    await _sync_account_order_for_telegram_order(session, order)
    await session.flush()
    return order


async def attach_payment_to_order(
    session: AsyncSession,
    order_id: str,
    provider_payment_id: str,
    payment_url: str,
) -> Order:
    order = await session.get(Order, order_id)
    if order is None:
        raise OrderNotFound(order_id)
    order.provider_payment_id = provider_payment_id
    order.payment_url = payment_url
    order.status = OrderStatus.WAITING_PAYMENT
    await _sync_account_order_for_telegram_order(session, order)
    await session.flush()
    return order


async def attach_manual_crypto_payment(session: AsyncSession, order_id: str) -> Order:
    order = await session.get(Order, order_id)
    if order is None:
        raise OrderNotFound(order_id)
    order.provider = PaymentProvider.MANUAL_CRYPTO
    order.provider_payment_id = f"manual_crypto:{order.id}"
    order.payment_url = None
    order.status = OrderStatus.WAITING_PAYMENT
    await _sync_account_order_for_telegram_order(session, order)
    await session.flush()
    return order


async def get_order_with_product(session: AsyncSession, order_id: str) -> Order | None:
    return await session.scalar(_order_query().where(Order.id == order_id))


async def get_recent_orders(session: AsyncSession, telegram_id: int, limit: int = 10) -> list[Order]:
    result = await session.scalars(
        _order_query()
        .where(Order.telegram_id == telegram_id)
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    return list(result)


async def get_order_by_payment_id(
    session: AsyncSession,
    provider_payment_id: str,
) -> Order | None:
    return await session.scalar(
        _order_query().where(Order.provider_payment_id == provider_payment_id)
    )


async def get_order_by_id_or_prefix(session: AsyncSession, value: str) -> Order | None:
    value = value.strip()
    if not value:
        return None
    exact = await get_order_with_product(session, value)
    if exact is not None:
        return exact
    result = await session.scalars(
        _order_query()
        .where(Order.id.like(f"{value}%"))
        .order_by(Order.created_at.desc())
        .limit(2)
    )
    matches = list(result)
    return matches[0] if len(matches) == 1 else None


async def list_pending_orders(session: AsyncSession, limit: int = 20) -> list[Order]:
    result = await session.scalars(
        _order_query()
        .where(Order.status == OrderStatus.WAITING_PAYMENT)
        .order_by(Order.created_at.asc())
        .limit(limit)
    )
    return list(result)


def _order_query() -> Select[tuple[Order]]:
    return select(Order).options(selectinload(Order.product), selectinload(Order.key))


async def cancel_order_and_release(session: AsyncSession, order: Order) -> None:
    if order.status in {OrderStatus.DELIVERED, OrderStatus.PAID}:
        return
    order.status = OrderStatus.CANCELED
    await _sync_account_order_for_telegram_order(session, order)
    await _release_reserved_key(session, order)


async def expire_order_and_release(session: AsyncSession, order: Order) -> None:
    if order.status in {OrderStatus.DELIVERED, OrderStatus.PAID, OrderStatus.CANCELED}:
        return
    order.status = OrderStatus.EXPIRED
    await _sync_account_order_for_telegram_order(session, order)
    await _release_reserved_key(session, order)


async def _release_reserved_key(session: AsyncSession, order: Order) -> None:
    if order.key_id is None:
        return
    key = await session.get(ApiKey, order.key_id)
    if key is None:
        return
    if key.status == ApiKeyStatus.RESERVED and key.reserved_order_id == order.id:
        key.status = ApiKeyStatus.AVAILABLE
        key.reserved_order_id = None
        key.reserved_until = None
    await session.flush()


async def deliver_paid_order(
    session: AsyncSession,
    cipher: KeyCipher,
    order: Order,
    provider_payment_id: str | None = None,
) -> tuple[str, bool]:
    if provider_payment_id and order.provider_payment_id != provider_payment_id:
        raise PaymentMismatch(order.id)
    if order.key_id is None:
        raise DeliveryConflict("Order has no reserved API key")

    key = await session.get(ApiKey, order.key_id)
    if key is None:
        raise DeliveryConflict("Reserved API key was not found")

    if order.status == OrderStatus.DELIVERED:
        return cipher.decrypt(key.ciphertext), False

    if key.status == ApiKeyStatus.SOLD and key.sold_order_id != order.id:
        raise DeliveryConflict("Reserved API key is already sold")

    if key.status == ApiKeyStatus.RESERVED and key.reserved_order_id not in {None, order.id}:
        raise DeliveryConflict("Reserved API key belongs to another order")

    now = utcnow()
    order.status = OrderStatus.DELIVERED
    order.paid_at = order.paid_at or now
    order.delivered_at = order.delivered_at or now
    key.status = ApiKeyStatus.SOLD
    key.sold_order_id = order.id
    key.reserved_order_id = None
    key.reserved_until = None
    await _sync_account_order_for_telegram_order(session, order, key)
    await session.flush()
    return cipher.decrypt(key.ciphertext), True


async def _account_by_telegram_id(session: AsyncSession, telegram_id: int) -> Account | None:
    return await session.scalar(select(Account).where(Account.telegram_id == telegram_id))


async def sync_account_records_for_telegram_id(session: AsyncSession, telegram_id: int) -> None:
    account = await _account_by_telegram_id(session, telegram_id)
    if account is None:
        return
    orders = await session.scalars(
        select(Order)
        .where(Order.telegram_id == telegram_id)
        .order_by(Order.created_at.asc())
    )
    for order in orders:
        await _sync_account_order_for_telegram_order(session, order)


async def _sync_account_order_for_telegram_order(
    session: AsyncSession,
    order: Order,
    key: ApiKey | None = None,
) -> None:
    account = await _account_by_telegram_id(session, order.telegram_id)
    if account is None:
        return

    account_order = await session.get(AccountOrder, order.id)
    if account_order is None:
        account_order = AccountOrder(
            id=order.id,
            account_id=account.id,
            product_id=order.product_id,
            amount_kopecks=order.amount_kopecks,
            currency=order.currency,
            status=order.status,
            provider=order.provider,
            external_order_id=order.provider_payment_id,
            paid_at=order.paid_at,
            delivered_at=order.delivered_at,
        )
        session.add(account_order)
    else:
        account_order.account_id = account.id
        account_order.product_id = order.product_id
        account_order.amount_kopecks = order.amount_kopecks
        account_order.currency = order.currency
        account_order.status = order.status
        account_order.provider = order.provider
        account_order.external_order_id = order.provider_payment_id
        account_order.paid_at = order.paid_at
        account_order.delivered_at = order.delivered_at

    if order.status != OrderStatus.DELIVERED or order.key_id is None:
        return

    key = key or await session.get(ApiKey, order.key_id)
    if key is None:
        return

    owned_key = await session.scalar(
        select(AccountOwnedKey).where(AccountOwnedKey.order_id == order.id)
    )
    if owned_key is None:
        owned_key = AccountOwnedKey(
            account_id=account.id,
            product_id=order.product_id,
            order_id=order.id,
            key_id=key.id,
            title="",
            key_ciphertext=key.ciphertext,
        )
        session.add(owned_key)
    else:
        owned_key.account_id = account.id
        owned_key.product_id = order.product_id
        owned_key.key_id = key.id
        owned_key.key_ciphertext = key.ciphertext


async def waiting_orders_expired(session: AsyncSession) -> list[Order]:
    result = await session.scalars(
        _order_query()
        .where(
            Order.status.in_([OrderStatus.NEW, OrderStatus.WAITING_PAYMENT]),
            Order.expires_at <= utcnow(),
        )
        .order_by(Order.created_at.asc())
    )
    return list(result)
