import base64
import hashlib
import hmac
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from keyshop_bot.crypto import KeyCipher
from keyshop_bot.formatting import format_money
from keyshop_bot.models import (
    Account,
    AccountEmailVerification,
    AccountOrder,
    AccountOwnedKey,
    AccountSession,
    AccountTelegramLink,
    utcnow,
)
from keyshop_bot.services import sync_account_records_for_telegram_id

PASSWORD_ITERATIONS = 260_000
SESSION_TTL_DAYS = 30


class AccountError(RuntimeError):
    pass


class AccountExists(AccountError):
    pass


class InvalidCredentials(AccountError):
    pass


class InvalidVerificationCode(AccountError):
    pass


class AuthRequired(AccountError):
    pass


class InvalidTelegramLinkCode(AccountError):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        salt = base64.urlsafe_b64decode(salt_raw.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_raw.encode("ascii"))
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verification_code_hash(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def new_verification_code() -> str:
    return f"{secrets.randbelow(900000) + 100000}"


def new_link_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def normalize_phone(phone: str) -> str:
    value = " ".join(phone.strip().split())
    if value and value[0].isdigit():
        value = f"+{value}"
    return value[:40]


async def register_account(
    session: AsyncSession,
    email: str,
    password: str,
    display_name: str = "",
) -> Account:
    email = normalize_email(email)
    existing = await session.scalar(select(Account).where(Account.email == email))
    if existing is not None:
        raise AccountExists(email)
    account = Account(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name.strip(),
        balance_kopecks=0,
    )
    session.add(account)
    await session.flush()
    return account


async def create_email_verification(
    session: AsyncSession,
    email: str,
    password: str,
    display_name: str = "",
) -> tuple[AccountEmailVerification, str]:
    email = normalize_email(email)
    existing = await session.scalar(select(Account).where(Account.email == email))
    if existing is not None:
        raise AccountExists(email)

    previous = await session.scalar(
        select(AccountEmailVerification).where(AccountEmailVerification.email == email)
    )
    if previous is not None:
        await session.delete(previous)
        await session.flush()

    code = new_verification_code()
    verification = AccountEmailVerification(
        email=email,
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        code_hash=verification_code_hash(code),
        expires_at=utcnow() + timedelta(minutes=15),
    )
    session.add(verification)
    await session.flush()
    return verification, code


async def verify_email_code(
    session: AsyncSession,
    email: str,
    code: str,
) -> Account:
    email = normalize_email(email)
    verification = await session.scalar(
        select(AccountEmailVerification).where(
            AccountEmailVerification.email == email,
            AccountEmailVerification.expires_at > utcnow(),
        )
    )
    if verification is None:
        raise InvalidVerificationCode()
    if not hmac.compare_digest(verification.code_hash, verification_code_hash(code)):
        raise InvalidVerificationCode()

    existing = await session.scalar(select(Account).where(Account.email == email))
    if existing is not None:
        await session.delete(verification)
        await session.flush()
        raise AccountExists(email)

    account = Account(
        email=email,
        password_hash=verification.password_hash,
        display_name=verification.display_name,
        balance_kopecks=0,
    )
    session.add(account)
    await session.delete(verification)
    await session.flush()
    return account


async def authenticate_account(
    session: AsyncSession,
    email: str,
    password: str,
) -> Account:
    account = await session.scalar(
        select(Account).where(Account.email == normalize_email(email))
    )
    if account is None or not account.is_active:
        raise InvalidCredentials()
    if not verify_password(password, account.password_hash):
        raise InvalidCredentials()
    return account


async def create_account_session(
    session: AsyncSession,
    account: Account,
) -> tuple[str, AccountSession]:
    token = secrets.token_urlsafe(32)
    account_session = AccountSession(
        account_id=account.id,
        token_hash=token_hash(token),
        expires_at=utcnow() + timedelta(days=SESSION_TTL_DAYS),
    )
    session.add(account_session)
    await session.flush()
    return token, account_session


async def account_from_token(
    session: AsyncSession,
    token: str | None,
) -> Account:
    if not token:
        raise AuthRequired()
    account_session = await session.scalar(
        select(AccountSession)
        .options(selectinload(AccountSession.account))
        .where(
            AccountSession.token_hash == token_hash(token),
            AccountSession.expires_at > utcnow(),
        )
    )
    if account_session is None or not account_session.account.is_active:
        raise AuthRequired()
    return account_session.account


async def revoke_account_session(session: AsyncSession, token: str | None) -> None:
    if not token:
        return
    account_session = await session.scalar(
        select(AccountSession).where(AccountSession.token_hash == token_hash(token))
    )
    if account_session is not None:
        await session.delete(account_session)
        await session.flush()


async def update_account_profile(
    session: AsyncSession,
    account: Account,
    display_name: str,
    phone: str,
) -> Account:
    account.display_name = display_name.strip()[:120]
    account.phone = normalize_phone(phone)
    account.updated_at = utcnow()
    await session.flush()
    return account


async def update_account_phone_by_telegram_id(
    session: AsyncSession,
    telegram_id: int,
    phone: str,
) -> Account | None:
    account = await session.scalar(select(Account).where(Account.telegram_id == telegram_id))
    if account is None:
        return None
    account.phone = normalize_phone(phone)
    account.updated_at = utcnow()
    await session.flush()
    return account


async def create_telegram_link_code(
    session: AsyncSession,
    account: Account,
) -> str:
    previous = await session.scalars(
        select(AccountTelegramLink).where(AccountTelegramLink.account_id == account.id)
    )
    for link in previous:
        await session.delete(link)
    await session.flush()

    code = new_link_code()
    link = AccountTelegramLink(
        account_id=account.id,
        code_hash=verification_code_hash(code),
        expires_at=utcnow() + timedelta(minutes=15),
    )
    session.add(link)
    await session.flush()
    return code


async def link_telegram_account(
    session: AsyncSession,
    code: str,
    telegram_id: int,
    telegram_username: str | None = None,
) -> Account:
    link = await session.scalar(
        select(AccountTelegramLink)
        .options(selectinload(AccountTelegramLink.account))
        .where(
            AccountTelegramLink.code_hash == verification_code_hash(code),
            AccountTelegramLink.expires_at > utcnow(),
        )
    )
    if link is None:
        raise InvalidTelegramLinkCode()

    existing = await session.scalar(
        select(Account).where(
            Account.telegram_id == telegram_id,
            Account.id != link.account_id,
        )
    )
    if existing is not None:
        existing.telegram_id = None
        existing.telegram_username = ""

    account = link.account
    account.telegram_id = telegram_id
    account.telegram_username = (telegram_username or "").strip().lstrip("@")[:64]
    account.updated_at = utcnow()
    await session.delete(link)
    await sync_account_records_for_telegram_id(session, telegram_id)
    await session.flush()
    return account


async def account_orders(session: AsyncSession, account_id: int) -> list[AccountOrder]:
    result = await session.scalars(
        select(AccountOrder)
        .options(selectinload(AccountOrder.product))
        .where(AccountOrder.account_id == account_id)
        .order_by(AccountOrder.created_at.desc())
        .limit(50)
    )
    return list(result)


async def account_keys(session: AsyncSession, account_id: int) -> list[AccountOwnedKey]:
    result = await session.scalars(
        select(AccountOwnedKey)
        .options(selectinload(AccountOwnedKey.product), selectinload(AccountOwnedKey.api_key))
        .where(AccountOwnedKey.account_id == account_id)
        .order_by(AccountOwnedKey.created_at.desc())
    )
    return list(result)


def account_payload(account: Account) -> dict[str, object]:
    return {
        "id": account.id,
        "email": account.email,
        "display_name": account.display_name,
        "phone": account.phone,
        "telegram_id": account.telegram_id,
        "telegram_username": account.telegram_username,
        "balance": {
            "kopecks": account.balance_kopecks,
            "formatted": format_money(account.balance_kopecks),
        },
    }


def order_payload(order: AccountOrder) -> dict[str, object]:
    return {
        "id": order.id,
        "status": order.status,
        "provider": order.provider,
        "product": {
            "slug": order.product.slug,
            "title": order.product.title,
        }
        if order.product is not None
        else None,
        "amount": {
            "kopecks": order.amount_kopecks,
            "currency": order.currency,
            "formatted": format_money(order.amount_kopecks, order.currency),
        },
        "created_at": order.created_at.isoformat(),
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
    }


def key_payload(owned_key: AccountOwnedKey, cipher: KeyCipher) -> dict[str, object]:
    ciphertext = owned_key.key_ciphertext
    if ciphertext is None and owned_key.api_key is not None:
        ciphertext = owned_key.api_key.ciphertext
    plain_key = cipher.decrypt(ciphertext) if ciphertext else None
    title = owned_key.title
    if not title and owned_key.product is not None:
        title = owned_key.product.title
    return {
        "id": owned_key.id,
        "title": title,
        "key": plain_key,
        "product": {
            "slug": owned_key.product.slug,
            "title": owned_key.product.title,
        }
        if owned_key.product is not None
        else None,
        "created_at": owned_key.created_at.isoformat(),
    }
