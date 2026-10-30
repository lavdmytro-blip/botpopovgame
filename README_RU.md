# POPOV TAP Python — установка на Northflank

Это новая Python-сборка вместо Node.js. **Ошибка `Cannot find module pg` здесь невозможна**, поскольку код на Python использует `psycopg`.

## 1. GitHub
Создай новый репозиторий `popov-tap-python`. Загрузи **содержимое** этого ZIP, так чтобы `main.py`, `requirements.txt`, `Procfile`, папка `public/` лежали в корне. Не загружай ZIP как единственный файл. Не загружай `.env`.

## 2. PostgreSQL
В Northflank создай проект и Addon → PostgreSQL (или используй уже существующую базу). В Secrets добавь связь с addon и передай `POSTGRES_URI` под именем `DATABASE_URL`. Не публикуй пароль.

## 3. Сервис
Create service → Combined → GitHub repository → `popov-tap-python` → Buildpack (Heroku) → root `/`.
- Buildpack определит Python из `requirements.txt`.
- Port HTTP: **3000**, Public.
- Start command (если поле обязательно): `uvicorn main:app --host 0.0.0.0 --port 3000`.
- Runtime secrets: `BOT_TOKEN` и `DATABASE_URL`.
- Runtime vars: `PORT=3000`, `PUBLIC_URL=https://...code.run` после появления домена (без завершающего слеша).
- Instances: **1**. JSON-хранилище в одной строке PostgreSQL рассчитано лишь на один экземпляр MVP.

После публикации открой `https://ТВОЙ-ДОМЕН/health`: ожидается `{"ok":true,"database":"connected",...}`. Игра доступна по `/`.

## 4. Telegram
В BotFather → `/mybots` → Bot Settings → Menu Button укажи публичный HTTPS-домен. Запускай игру внутри Telegram. Ник и аватар загружаются из Telegram WebApp initData, если Telegram передаёт photo_url. Если фото нет, показывается первая буква имени.

## 5. Проверка
Открой через Telegram, нажми несколько раз, перезапусти игру, проверь сохранение. Открой со второго Telegram-аккаунта для проверки общего лидерборда.

## Важно
- Игровые POPOV POINTS не являются криптовалютой и не обещают доход.
- Stars покупают только косметические скины. Покупку выдаёт сервер после `successful_payment`. Для production нужны дополнительные тесты оплаты, возвратов и обработка сбоев.
- Long polling требует отсутствия другого Telegram-процесса, получающего `getUpdates` с этим токеном, и отсутствия webhook. Если ранее настроен webhook, удали его через Telegram Bot API прежде чем запускать polling.
- Сервер должен иметь права чтения/записи в PostgreSQL. Не запускай несколько копий текущего MVP.
- Эта сборка новая; требует проверки на твоём Northflank и не переносит старые балансы автоматически.
