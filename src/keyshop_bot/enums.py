from enum import StrEnum


class ApiKeyStatus(StrEnum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    SOLD = "sold"


class OrderStatus(StrEnum):
    NEW = "new"
    WAITING_PAYMENT = "waiting_payment"
    PAID = "paid"
    DELIVERED = "delivered"
    CANCELED = "canceled"
    EXPIRED = "expired"


class PaymentProvider(StrEnum):
    MANUAL_CRYPTO = "manual_crypto"
    YOOKASSA = "yookassa"
