# Решение типовых проблем

Если что-то идёт не так — этот документ закрывает 90% случаев.

---

## 🔧 Установка и GitHub

### ❌ «I understand my workflows» — кнопка Actions ничего не делает

GitHub иногда требует подтверждения от владельца аккаунта.

1. Settings → Actions → General.
2. **Actions permissions:** Allow all actions and reusable workflows → Save.
3. Вернись на вкладку Actions, обнови страницу.

---

### ❌ `Workflow failed: Resource not accessible by integration`

Для коммита `data/sent_signals.json` и `data/reports_archive/` workflow'у
нужны write-разрешения.

1. Settings → Actions → General.
2. **Workflow permissions:** Read and write permissions → Save.
3. Перезапусти workflow.

---

### ❌ `ModuleNotFoundError` в логах Actions

Проблема с `requirements.txt`.

1. Открой failed run → шаг **Install dependencies**.
2. Найди имя пропавшего модуля.
3. Убедись, что он указан в `requirements.txt` в корне репо.
4. Если файл целиком отсутствует — пересоздай репозиторий через
   **Use this template**.

---

## 🔐 Секреты

### ❌ Telegram `401 Unauthorized`

Bot token невалиден.

- Лишний пробел в начале/конце? Скопируй заново.
- Бот удалён в @BotFather? Создай новый через `/newbot`.
- Если потерял токен — `/mybots` → твой бот → **API Token** → **Revoke**.
- Обнови `TELEGRAM_BOT_TOKEN` в **Settings → Secrets → Actions**.

---

### ❌ Telegram `400 Bad Request: chat not found`

Бот не знает, кому слать.

1. Открой бота в Telegram → нажми **Start**.
2. Если `TELEGRAM_CHAT_ID` неизвестен — напиши `@userinfobot` `/start`.
3. Обнови `TELEGRAM_CHAT_ID` в Secrets.

---

### ❌ Claude `401 Authentication error`

API-ключ невалиден.

1. console.anthropic.com → **API Keys** → создай новый.
2. Скопируй полностью (начинается с `sk-ant-…`).
3. Обнови `CLAUDE_API_KEY` в GitHub Secrets.

---

### ❌ Claude `529 Overloaded`

Серверы Anthropic под нагрузкой.

- В коде уже стоит retry с exponential backoff (3 попытки).
- Если падает регулярно — попробуй через час, обычно проходит.

---

## 📊 Портфель

### ❌ «Portfolio is empty»

В `portfolio/` нет CSV И в `config.yaml` пустой `tickers:`.

**Вариант А — IBKR CSV:**
1. IBKR Client Portal → Performance & Reports → Statements.
2. Period: 30 дней. Format: **CSV**. Скачай.
3. На GitHub: открой папку `portfolio/` → **Add file → Upload files**.

**Вариант Б — список в config:**
```yaml
tickers:
  - AAPL
  - MSFT
  - NVDA
```

---

### ❌ «CSV format not recognized»

IBKR обновил формат экспорта, или ты выгрузил из другого источника.

Самый надёжный fallback — простой CSV:
```csv
ticker,quantity,price
AAPL,100,150.25
TSLA,50,250.00
```

---

### ❌ Кодировка ломается (кракозябры)

Excel-выгрузки иногда сохраняются в Windows-1252 с BOM.
Парсер автоматически пробует UTF-8 / UTF-8 BOM / CP1252 / Latin-1, так
что в большинстве случаев это не проблема. Если всё-таки сломалось —
открой CSV в **Notepad++**, **File → Encoding → UTF-8 (without BOM)**,
пересохрани, перезалей.

---

## 🌐 Источники данных

### ❌ SEC EDGAR `403 Forbidden`

SEC отклоняет запросы без User-Agent. Код проставляет дефолтный
`Claude Portfolio Watchdog research@example.com`, но если ты переопределял
его в `config.yaml` или окружении — проверь, что там валидный email.

---

### ❌ SEC EDGAR `429 Too Many Requests`

Превысили лимит 10 req/sec.

В клиенте уже стоит троттлинг (0.11s между запросами). Если по какой-то
причине падает:
- Уменьши `tickers` в config.yaml.
- Запускай monitor реже (поправь cron в `.github/workflows/monitor.yml`).

---

### ❌ yfinance возвращает пустые данные

Yahoo Finance бесплатный — и иногда нестабильный.

- Подожди 10–15 минут, попробуй снова.
- Workflow при следующем запуске по cron сам соберёт пропущенное.

---

## 💰 Расходы на API

### Claude API кушает много

Норма: **$1–3 в месяц** для портфеля 10–15 позиций.

Если больше:
- Подними `thresholds.news_importance_min` с 7 до 8 (меньше Claude-вызовов).
- Убери `monitoring.macro` / `monitoring.volatility`, если не нужно.
- Уменьши `tickers`.
- Убедись, что `data/news_cache.json` коммитится — это и есть кеш.

См. полный разбор в [API_COSTS.md](API_COSTS.md).

---

## 🔔 Уведомления

### Сигналы приходят слишком часто

```yaml
thresholds:
  price_movement_percent: 5.0     # было 3
  news_importance_min: 8          # было 7
  insider_min_value_usd: 5000000  # было 1M
```

### Сигналы не приходят вообще

- Проверь `monitoring.*: true` в `config.yaml`.
- Не слишком ли высокие пороги.
- Последний run в Actions: всё зелёное?
- В логах есть ошибки?

### Сигналы повторяются

- `data/sent_signals.json` существует в репозитории?
- В workflow `permissions: contents: write`?
- Git push в шаге `Commit updated state` успешный?

### Сообщение длиннее 4096 символов

Клиент сам разбивает его на части по строкам. Если визуально сломалось —
проверь, что шаблон не содержит одной строки длиннее 3900 символов.

---

## 💻 Локальный запуск (опционально)

### ❌ `pip install -r requirements.txt` падает на Python 3.14

На очень свежих версиях Python иногда нет готовых wheel'ов для
тяжёлых пакетов (`numpy`, `pandas`, `matplotlib`), и pip пытается
скомпилировать их из исходников — это часто падает на Windows без
Build Tools.

**Решение:** используй **Python 3.11 или 3.12** для локального запуска.
В GitHub Actions всегда используется 3.11 — там проблем не будет.

```powershell
# Скачай Python 3.11: https://www.python.org/downloads/release/python-3119/
py -3.11 -m pip install -r requirements.txt
```

### ❌ `config.yaml` после правки в GitHub Web UI выдаёт «YAML parse error»

YAML очень чувствителен к **отступам и табам**.

Самые частые ошибки:
- Случайно поставил **табы** вместо пробелов — переведи обратно на пробелы.
- Сдвинул отступ на одну позицию — сравни с `config.example.yaml`.
- Лишняя пустая строка внутри списка.

GitHub Web UI **показывает табы серым крестиком** в нижней панели редактора —
если видишь их в config.yaml, удали.

### ❌ DNS блокирует `api.github.com` или другие сервисы

Если ты используешь продукт **локально на Windows**, и `pip install` или
`git push` падает с SSL-ошибкой типа `certificate is valid for dns.google,
not api.github.com` — у тебя в `hosts`-файле перехвачены DNS-записи
(обычно ставит активатор Windows / антипиратский софт).

**Решение:** запусти PowerShell от админа и выполни:

```powershell
$hosts = "C:\Windows\System32\drivers\etc\hosts"
(Get-Content $hosts) | Where-Object {
  $_ -notmatch "8\.8\.4\.4\s+(codeload\.github\.com|api\.github\.com)"
} | Set-Content $hosts -Encoding UTF8
ipconfig /flushdns
```

В GitHub Actions этой проблемы нет.

---

## 🐛 Если ничего не помогает

1. Открой issue в репо: **Issues → New issue**.
2. Приложи:
   - Что делал.
   - Что ожидал.
   - Что получил.
   - Полный лог failed workflow (раздел Logs в Actions).
3. Не указывай в логах токены/ключи — отредактируй их перед публикацией.

Закажи личную консультацию ($300) — настрою всё под тебя, добавлю
кастомные сигналы и интеграцию с IBKR Web API.
