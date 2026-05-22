# Кастомизация через Claude Code

Хочешь добавить функциональность, которой нет из коробки? Используй
[Claude Code](https://claude.ai/code) — он напишет код по твоим словесным
инструкциям. Ниже — готовые промпты для самых частых доработок.

---

## Что такое Claude Code

Claude Code — это AI-ассистент Anthropic, который умеет читать твой
репозиторий, писать новые файлы и редактировать существующие. Тебе не
нужно знать Python: ты описываешь задачу словами, проверяешь результат и
коммитишь, если нравится.

Установка: открой `claude.ai/code` и следуй инструкциям (доступен на
Windows / macOS / Linux).

---

## Принципы

1. **Не ломай основное.** Перед серьёзной правкой — `git checkout -b
   my-customization`.
2. **Тестируй локально** через `python -m src.main --task=demo` или
   `python -m src.main --task=monitor`.
3. **Один промпт = одна задача.** Не пытайся за один присест добавить
   3 фичи — Claude Code справится лучше, если разбить.

---

## Готовые промпты

### 1. Мониторинг крипты

```text
Добавь монитор для криптовалют. Источник — CoinGecko API (бесплатный, не
требует ключа). Поддерживай BTC, ETH и любые тикеры из списка
config.yaml → crypto_tickers.

Структура: создай src/monitors/crypto.py по образцу src/monitors/price.py.
Триггер: дневное изменение > config.thresholds.price_movement_percent.

В config.example.yaml добавь раздел
crypto:
  enabled: true
  tickers: ["BTC", "ETH", "SOL"]

В src/main.py подключи новый монитор в _build_monitors() с условным
включением по crypto.enabled.
```

### 2. Двойная сводка — утром и вечером

```text
Добавь второй workflow .github/workflows/evening-summary.yml — запуск в
18:00 МСК (15:00 UTC) понедельник–пятница. Использует тот же
python -m src.main --task=daily.

Если нужно отдельный текст для вечернего варианта — добавь параметр
--task=evening, который генерирует ту же DailySummary, но с заголовком
"ВЕЧЕРНЯЯ СВОДКА" и сравнением с открытием дня вместо вчера.
```

### 3. Уведомления в Discord

```text
Добавь возможность дублировать сигналы в Discord помимо Telegram.

1. В config.example.yaml добавь:
   notifications:
     telegram: true
     discord: true
     discord_webhook: ""    # URL Webhook'а

2. Создай src/clients/discord.py — отправка через webhook (POST с JSON).

3. В src/main.py: вместо self.telegram.send_message(text) вызывай
   self._broadcast(text), который шлёт во все включённые каналы.
```

### 4. Свой стиль шаблонов уведомлений

```text
Открой src/utils/templates.py. Шаблоны лежат в функциях _render_insider,
_render_analyst и т.д. Поменяй текст / эмодзи / структуру под мой стиль:
[опиши, что хочешь].

После правки обнови юнит-тесты в tests/test_monitors/test_*.py, чтобы они
не сравнивали по точному тексту.
```

### 5. Дополнительный источник новостей

```text
Добавь парсинг RSS-feed'ов с Seeking Alpha и Benzinga. Они бесплатные.

1. Создай src/clients/news_sources.py с функцией fetch_rss(url, since)
   → list[dict] вида {"title": ..., "publisher": ..., "link": ..., "ts": ...}.

2. В src/monitors/news.py NewsMonitor.check добавь объединение с этим
   источником.

3. URLs:
   - https://seekingalpha.com/feed.xml
   - https://www.benzinga.com/feed
```

### 6. Прямая интеграция с IBKR Web API (Pro)

```text
Замени CSV-логику в src/portfolio_loader.py на чтение позиций напрямую
из IBKR Web API.

Используй библиотеку ib_insync (https://github.com/erdewit/ib_insync) или
официальную ibapi. Документация:
https://interactivebrokers.github.io/

Учти: IBKR Web API требует запущенного IB Gateway, а GitHub Actions
не сможет до него подключиться. Этот вариант имеет смысл только для
локального запуска или собственного сервера.
```

---

## Если нужна помощь автора

Заказ персональной консультации ($300) включает:
- Установку и настройку под твой портфель.
- Прямую интеграцию с IBKR Web API.
- Кастомные типы сигналов (опционы, дивиденды, byline-новости и т.д.).
- 1-часовой Zoom-разбор.

Ссылка на заказ — в шапке репозитория продавца.
