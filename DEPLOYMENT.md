# Deployment

Проект состоит из двух частей:

- `index.html` и `config.js` - фронтенд для Vercel.
- `src/keyshop_bot/` - Python backend, Telegram-бот, API аккаунтов и платежи.

Vercel не должен запускать Telegram-бота как постоянный процесс. Для backend-а нужен VPS, Render, Railway или другой хостинг, где процесс `python -m keyshop_bot.main` может работать постоянно.

## Что заливать на GitHub

Заливайте:

- `index.html`
- `config.js`
- `vercel.json`
- `pyproject.toml`
- `README.md`
- `DEPLOYMENT.md`
- `.env.example`
- `src/`
- `tests/`
- `deploy/`

Не заливайте:

- `.env`
- `data/`
- `logs/`
- `.venv/`
- `.pytest_cache/`
- `__pycache__/`

Проверьте это перед коммитом:

```powershell
git status --short
```

В списке не должно быть `.env`, базы данных или логов.

## Vercel

1. Создайте GitHub repository и загрузите проект.
2. В Vercel импортируйте repository.
3. Framework Preset: `Other`.
4. Build Command: пусто.
5. Output Directory: пусто.

Пока backend не развернут публично, аккаунты и live-каталог на домене могут не работать. После деплоя backend-а укажите его URL в `config.js`:

```js
window.NEXUS_API_BASE = "https://api.example.com";
```

После этого сделайте новый deploy на Vercel.

## VPS backend

Пример для Ubuntu VPS:

```bash
sudo adduser --system --group --home /opt/nexus-ai nexus
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git nginx
sudo git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git /opt/nexus-ai
sudo chown -R nexus:nexus /opt/nexus-ai
cd /opt/nexus-ai
sudo -u nexus python3 -m venv .venv
sudo -u nexus .venv/bin/pip install -e .
sudo -u nexus cp .env.example .env
```

Заполните `/opt/nexus-ai/.env` реальными значениями. Не храните реальные токены в GitHub.

Проверочный запуск:

```bash
sudo -u nexus /opt/nexus-ai/.venv/bin/python -m keyshop_bot.main
```

Для автозапуска:

```bash
sudo cp /opt/nexus-ai/deploy/keyshop-bot.service.example /etc/systemd/system/keyshop-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now keyshop-bot
sudo systemctl status keyshop-bot
```

Для прокси API через nginx:

```bash
sudo cp /opt/nexus-ai/deploy/nginx-api.example.conf /etc/nginx/sites-available/nexus-api
sudo ln -s /etc/nginx/sites-available/nexus-api /etc/nginx/sites-enabled/nexus-api
sudo nginx -t
sudo systemctl reload nginx
```

После подключения домена и HTTPS укажите backend-домен в:

```env
PUBLIC_BASE_URL=https://api.example.com
SITE_CORS_ORIGIN=https://your-vercel-site.vercel.app
```

И в `config.js` на фронтенде:

```js
window.NEXUS_API_BASE = "https://api.example.com";
```

## Security checklist

- Перед продакшеном перевыпустите Telegram bot token в BotFather.
- Не публикуйте `.env`.
- Не публикуйте `data/keyshop.db`.
- Сделайте резервную копию базы перед обновлениями backend-а.
- Для домена backend-а включите HTTPS.
