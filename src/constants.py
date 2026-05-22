"""Project-wide constants. Заполняется по мере необходимости в ПРОМПТах 2–9."""

PROJECT_NAME = "Claude Portfolio Watchdog"
PROJECT_VERSION = "0.1.0"

# Дефолтный User-Agent для SEC EDGAR — обязателен по требованиям SEC.
DEFAULT_SEC_USER_AGENT = "Claude Portfolio Watchdog research@example.com"

# Лимиты Telegram Bot API.
TELEGRAM_MAX_MESSAGE_LENGTH = 4096
TELEGRAM_SAFE_MESSAGE_LENGTH = 3900  # запас под HTML-эскейп

# Пути к файлам состояния.
PATH_SENT_SIGNALS = "data/sent_signals.json"
PATH_CIK_CACHE = "data/cik_cache.json"
PATH_NEWS_CACHE = "data/news_cache.json"
PATH_PRICE_HISTORY = "data/price_history.json"
PATH_REPORTS_ARCHIVE = "data/reports_archive"
