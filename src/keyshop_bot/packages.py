from dataclasses import dataclass
import re

from keyshop_bot.models import Product


@dataclass(frozen=True)
class PackagePlan:
    code: str
    title: str
    emoji: str
    aliases: tuple[str, ...]
    description: str


PACKAGE_PLANS: tuple[PackagePlan, ...] = (
    PackagePlan(
        code="start",
        title="Start",
        emoji="🚀",
        aliases=("start", "старт", "basic", "base", "mini"),
        description="Быстрый вход: недорогой пакет доступа для тестов и первых запусков.",
    ),
    PackagePlan(
        code="comfort",
        title="Comfort",
        emoji="💎",
        aliases=("comfort", "комфорт", "middle", "standard", "plus"),
        description="Оптимальный вариант для стабильной работы и частого использования.",
    ),
    PackagePlan(
        code="premium",
        title="Premium",
        emoji="👑",
        aliases=("premium", "премиум", "vip", "pro", "max"),
        description="Максимальный пакет доступа для серьезных задач и приоритетной работы.",
    ),
)

DEFAULT_PACKAGE_CODE = "start"


def package_by_code(code: str | None) -> PackagePlan:
    normalized = (code or "").strip().lower()
    for plan in PACKAGE_PLANS:
        if plan.code == normalized:
            return plan
    return PACKAGE_PLANS[0]


def package_for_product(product: Product) -> PackagePlan:
    haystack = " ".join(
        value
        for value in (
            product.slug,
            product.title,
            product.description,
        )
        if value
    ).lower()
    tokens = re.findall(r"[a-zа-яё0-9]+", haystack)
    for plan in PACKAGE_PLANS:
        if any(_alias_matches(alias, tokens) for alias in plan.aliases):
            return plan
    return package_by_code(DEFAULT_PACKAGE_CODE)


def products_in_package(products: list[Product], code: str) -> list[Product]:
    return [product for product in products if package_for_product(product).code == code]


def _alias_matches(alias: str, tokens: list[str]) -> bool:
    return alias in tokens or any(token.startswith(alias) for token in tokens if len(alias) >= 4)
