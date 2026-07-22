from decimal import Decimal
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from keyshop_bot.enums import PaymentProvider


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    bot_token: SecretStr = Field(alias="BOT_TOKEN")
    bot_username: str | None = Field(default=None, alias="BOT_USERNAME")
    admin_ids: Annotated[list[int], NoDecode] = Field(
        default_factory=list,
        alias="ADMIN_IDS",
    )

    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/keyshop.db",
        alias="DATABASE_URL",
    )
    key_encryption_key: SecretStr = Field(alias="KEY_ENCRYPTION_KEY")

    payment_provider: PaymentProvider = Field(
        default=PaymentProvider.MANUAL_CRYPTO,
        alias="PAYMENT_PROVIDER",
    )

    crypto_asset: str = Field(default="USDT", alias="CRYPTO_ASSET")
    crypto_network: str = Field(default="TRC20", alias="CRYPTO_NETWORK")
    crypto_wallet_address: str = Field(default="", alias="CRYPTO_WALLET_ADDRESS")
    crypto_rub_per_unit: Decimal | None = Field(default=None, alias="CRYPTO_RUB_PER_UNIT")
    crypto_payment_note: str = Field(default="", alias="CRYPTO_PAYMENT_NOTE")

    yookassa_shop_id: str | None = Field(default=None, alias="YOOKASSA_SHOP_ID")
    yookassa_secret_key: SecretStr | None = Field(default=None, alias="YOOKASSA_SECRET_KEY")
    yookassa_return_url: str | None = Field(default=None, alias="YOOKASSA_RETURN_URL")

    webapp_host: str = Field(default="0.0.0.0", alias="WEBAPP_HOST")
    webapp_port: int = Field(default=8080, alias="WEBAPP_PORT")
    public_base_url: str | None = Field(default=None, alias="PUBLIC_BASE_URL")
    site_cors_origin: str = Field(default="*", alias="SITE_CORS_ORIGIN")

    smtp_host: str | None = Field(default=None, alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str | None = Field(default=None, alias="SMTP_USERNAME")
    smtp_password: SecretStr | None = Field(default=None, alias="SMTP_PASSWORD")
    smtp_from_email: str | None = Field(default=None, alias="SMTP_FROM_EMAIL")
    smtp_from_name: str = Field(default="Nexus AI", alias="SMTP_FROM_NAME")
    smtp_starttls: bool = Field(default=True, alias="SMTP_STARTTLS")
    smtp_ssl: bool = Field(default=False, alias="SMTP_SSL")
    email_verification_dev_codes: bool = Field(
        default=True,
        alias="EMAIL_VERIFICATION_DEV_CODES",
    )

    payment_timeout_minutes: int = Field(default=30, alias="PAYMENT_TIMEOUT_MINUTES")
    support_username: str | None = Field(default=None, alias="SUPPORT_USERNAME")

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from_email)

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: object) -> list[int] | object:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            parts = value.replace(";", ",").split(",")
            return [int(part.strip()) for part in parts if part.strip()]
        return value

    @field_validator("crypto_rub_per_unit", mode="before")
    @classmethod
    def parse_optional_decimal(cls, value: object) -> Decimal | None | object:
        if value is None or value == "":
            return None
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
