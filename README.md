# Keyshop Bot

Telegram-бот для продажи цифровых кодов и пакетов доступа: каталог товаров, склад данных доступа, резервирование заказа и выдача данных доступа после подтверждения оплаты.

Текущий платежный режим: ручная крипто-оплата (`manual_crypto`). ЮKassa оставлена в коде и может быть включена позже через `PAYMENT_PROVIDER=yookassa`.

## Что уже есть

- Каталог ассистентов/тарифов в Telegram.
- Склад цифровых данных доступа по каждому товару.
- Шифрование данных доступа в базе через Fernet.
- Резерв данных доступа при создании заказа.
- Оплата криптовалютой по указанному кошельку.
- Уведомление админа, когда пользователь нажал "Я оплатил".
- Ручное подтверждение заказа админом и автоматическая отправка данных доступа пользователю.
- Команды для товаров, склада и заказов.
- Веб-кабинет: регистрация, вход, профиль, телефон, Telegram-привязка, заказы и доступы.

Подробная схема деплоя: [DEPLOYMENT.md](DEPLOYMENT.md).

Используйте только цифровые данные доступа, которые вы имеете право продавать или выдавать пользователям. Для цифровых товаров внутри Telegram также проверьте актуальные правила Telegram и требования платежных провайдеров.

## Быстрый старт

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
python -m keyshop_bot.crypto
```

Скопируйте сгенерированный ключ в `KEY_ENCRYPTION_KEY`, затем заполните `.env`.

Минимально для запуска:

```env
BOT_TOKEN=token_from_botfather
ADMIN_IDS=your_telegram_id
PAYMENT_PROVIDER=manual_crypto
CRYPTO_ASSET=USDT
CRYPTO_NETWORK=TRC20
CRYPTO_WALLET_ADDRESS=your_wallet_address
CRYPTO_RUB_PER_UNIT=
EMAIL_VERIFICATION_DEV_CODES=true
```

Если `CRYPTO_RUB_PER_UNIT` пустой, бот покажет сумму как рублевый эквивалент. Если указать курс, например `95`, заказ на 950 рублей будет показан как `10.000000 USDT`.

Запуск:

```powershell
python -m keyshop_bot.main
```

## Админ-команды

Команды доступны только пользователям из `ADMIN_IDS`.

```text
/admin
/add_product <slug> <price_rub> <title>
/enable_product <slug>
/disable_product <slug>
/add_key <slug> <api_key>
/stock
/orders
/approve_order <order_id>
/reject_order <order_id>
```

Пример:

```text
/add_product claude-start 990 "Пакет доступа Claude API"
/add_key gpt sk-live-your-key
/stock
```

Когда пользователь оплатит криптой и нажмет "Я оплатил", админ получит сообщение с командами:

```text
/approve_order <short_order_id>
/reject_order <short_order_id>
```

`/approve_order` отправит пользователю купленные данные доступа и пометит их проданными.

## Пользовательские команды

```text
/start
/catalog
/my_orders
/paid <order_id> <tx_hash или комментарий>
/link <код из личного кабинета>
/phone
```

Кнопка "Я оплатил" делает то же самое, что и `/paid`, но без tx hash.
`/link` привязывает Telegram к аккаунту сайта. `/phone` показывает кнопку Telegram для отправки номера в аккаунт.

## Связка Сайта И Бота

Бот поднимает HTTP API на `WEBAPP_HOST:WEBAPP_PORT`, по умолчанию:

```text
http://localhost:8080
```

Каталог для сайта:

```text
GET /api/products
GET /api/products/<slug>
```

Ответ `/api/products` содержит товары, цены, остатки и готовую ссылку `telegram_url`.
Админ-команды бота обновляют ту же базу, из которой сайт читает каталог, поэтому цены и остатки будут одинаковыми.

Пример кнопки на сайте для конкретного товара:

```html
<a href="https://t.me/APYnexusAI_bot?start=product_gpt">Купить в Telegram</a>
```

Пример динамической загрузки каталога:

```html
<div id="products"></div>
<script>
async function loadProducts() {
  const response = await fetch("http://localhost:8080/api/products");
  const data = await response.json();
  document.querySelector("#products").innerHTML = data.products.map((product) => `
    <article>
      <h3>${product.title}</h3>
      <p>${product.price.formatted}</p>
      <p>В наличии: ${product.stock}</p>
      <a href="${product.telegram_url}">Купить в Telegram</a>
    </article>
  `).join("");
}
loadProducts();
</script>
```

Для продакшена поставьте `PUBLIC_BASE_URL` на домен сервера и настройте прокси/HTTPS к порту `8080`.

## Аккаунты На Сайте

Сайт использует API аккаунтов:

```text
POST /api/auth/register
POST /api/auth/login
GET /api/auth/me
POST /api/auth/logout
PATCH /api/account/profile
POST /api/account/telegram-link
GET /api/account/keys
GET /api/account/orders
```

Сессия хранится на сайте как Bearer token в `localStorage`. Пароли хранятся в базе как PBKDF2-хэш.
Регистрация проходит через 6-значный код подтверждения. Если SMTP не настроен и `EMAIL_VERIFICATION_DEV_CODES=true`, код показывается прямо на сайте для локального теста.

Чтобы отправлять код на указанную почту, заполните SMTP-настройки и перезапустите бота:

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=your_login
SMTP_PASSWORD=your_password_or_app_password
SMTP_FROM_EMAIL=no-reply@example.com
SMTP_FROM_NAME=Nexus AI
SMTP_STARTTLS=true
SMTP_SSL=false
EMAIL_VERIFICATION_DEV_CODES=false
```

В текущем MVP личный кабинет уже показывает:

- email аккаунта;
- баланс;
- телефон;
- привязанный Telegram;
- купленные доступы;
- историю заказов.

Заказы и выданные данные доступа из Telegram подтягиваются в кабинет после привязки Telegram.

Для фронтенда на Vercel backend URL задается в `config.js`:

```js
window.NEXUS_API_BASE = "https://api.example.com";
```

Следующий шаг: сделать сайт-чекаут, который будет создавать заказ аккаунта, принимать оплату и после подтверждения добавлять купленные данные доступа в личный кабинет.

## ЮKassa позже

Чтобы вернуть ЮKassa:

```env
PAYMENT_PROVIDER=yookassa
YOOKASSA_SHOP_ID=...
YOOKASSA_SECRET_KEY=...
YOOKASSA_RETURN_URL=https://t.me/your_bot_username
```

Webhook для ЮKassa:

```text
https://your-domain.com/webhooks/yookassa
```

События:

- `payment.succeeded`
- `payment.canceled`
