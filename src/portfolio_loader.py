"""IBKR CSV portfolio loader.

Поддерживает 4 формата:

* **Activity Statement** — стандартный многосекционный экспорт IBKR
  (нужная секция начинается с ``Positions,Header,…`` / ``Positions,Data,…``).
* **Flex Query** — обычный single-table CSV с заголовками.
* **Portfolio Analyst** — компактная таблица позиций.
* **Simple** — ручной CSV вида ``ticker,quantity,price``.

Если в ``portfolio/`` нет CSV — fallback на список тикеров из config.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger("portfolio_loader")


class PortfolioError(RuntimeError):
    """Raised when the portfolio cannot be parsed and no fallback is possible."""


# ---------- Position dataclass ----------


@dataclass
class Position:
    ticker: str
    quantity: float
    average_cost: float = 0.0
    market_value: float = 0.0
    currency: str = "USD"
    asset_type: str = "STK"
    sector: str = ""
    company_name: str = ""

    @property
    def total_cost(self) -> float:
        return self.quantity * self.average_cost

    @property
    def unrealized_pnl(self) -> float:
        return self.market_value - self.total_cost

    @property
    def unrealized_pnl_percent(self) -> float:
        if self.total_cost == 0:
            return 0.0
        return (self.unrealized_pnl / self.total_cost) * 100


# ---------- Loader ----------


@dataclass
class PortfolioLoader:
    portfolio_dir: str | Path = "portfolio"
    config_tickers: list[str] = field(default_factory=list)
    market_data: object | None = None  # optional MarketDataClient for sector enrichment

    def __post_init__(self) -> None:
        self.portfolio_dir = Path(self.portfolio_dir)

    # ---------- Public ----------

    def load(self) -> list[Position]:
        csv_path = self._find_latest_csv()
        if csv_path is None:
            logger.info("No CSV in %s, falling back to config tickers", self.portfolio_dir)
            return self._fallback_to_config()

        try:
            fmt = self._detect_format(csv_path)
            logger.info("Detected format %s for %s", fmt, csv_path.name)
            parser = {
                "activity": self._parse_activity_statement,
                "flex": self._parse_flex_query,
                "portfolio_analyst": self._parse_portfolio_analyst,
                "simple": self._parse_simple_csv,
            }[fmt]
            positions = parser(csv_path)
        except PortfolioError:
            raise
        except Exception as exc:
            raise PortfolioError(
                f"Не удалось распарсить CSV {csv_path.name}: {exc}\n"
                "Подсказка: убедись, что это экспорт из IBKR Client Portal, "
                "или используй формат `ticker,quantity,price`."
            ) from exc

        positions = self._normalize_positions(positions)
        if self.market_data is not None:
            positions = self._enrich_with_sector(positions)
        return positions

    # ---------- File discovery ----------

    def _find_latest_csv(self) -> Path | None:
        if not self.portfolio_dir.exists():
            return None
        candidates = sorted(
            self.portfolio_dir.glob("*.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    # ---------- Format detection ----------

    def _detect_format(self, csv_path: Path) -> str:
        text = self._read_text(csv_path)
        head = "\n".join(text.splitlines()[:50]).lower()

        if "positions,header,symbol" in head or "positions,data," in head:
            return "activity"
        # Flex Query — обычно строго со столбцом Symbol + Quantity + AverageCost.
        if "symbol" in head and "quantity" in head and "averagecost" in head:
            return "flex"
        # Portfolio Analyst — короткая таблица.
        if "symbol" in head and "quantity" in head and "value" in head:
            return "portfolio_analyst"
        # Simple — заголовки 'ticker' и 'quantity'.
        if "ticker" in head and "quantity" in head:
            return "simple"
        # Fallback — пробуем как simple.
        return "simple"

    # ---------- Parsers ----------

    def _parse_activity_statement(self, csv_path: Path) -> list[Position]:
        text = self._read_text(csv_path)
        reader = csv.reader(io.StringIO(text))
        header: list[str] | None = None
        out: list[Position] = []

        for row in reader:
            if not row or len(row) < 2:
                continue
            if row[0] != "Positions":
                continue
            if row[1] == "Header":
                header = [c.strip() for c in row[2:]]
                continue
            if row[1] == "Data" and header is not None:
                fields = dict(zip(header, row[2:], strict=False))
                pos = self._position_from_activity_row(fields)
                if pos is not None:
                    out.append(pos)
        return out

    def _parse_flex_query(self, csv_path: Path) -> list[Position]:
        text = self._read_text(csv_path)
        reader = csv.DictReader(io.StringIO(text))
        out: list[Position] = []
        for raw in reader:
            row = {(k or "").strip(): v for k, v in raw.items()}
            ticker = (row.get("Symbol") or "").strip().upper()
            if not ticker:
                continue
            qty = _to_float(row.get("Quantity"))
            avg = _to_float(row.get("AverageCost") or row.get("CostPrice"))
            value_raw = row.get("Value")
            # Только MarkPrice — это цена за акцию, поэтому домножаем на qty.
            mv = _to_float(value_raw) if value_raw else _to_float(row.get("MarkPrice")) * qty
            currency = (row.get("CurrencyPrimary") or row.get("Currency") or "USD").strip() or "USD"
            asset_type = (row.get("AssetClass") or "STK").strip() or "STK"
            out.append(
                Position(
                    ticker=ticker,
                    quantity=qty,
                    average_cost=avg,
                    market_value=mv,
                    currency=currency,
                    asset_type=asset_type,
                )
            )
        return out

    def _parse_portfolio_analyst(self, csv_path: Path) -> list[Position]:
        text = self._read_text(csv_path)
        reader = csv.DictReader(io.StringIO(text))
        out: list[Position] = []
        for raw in reader:
            row = {(k or "").strip(): v for k, v in raw.items()}
            ticker = (row.get("Symbol") or row.get("Ticker") or "").strip().upper()
            if not ticker:
                continue
            qty = _to_float(row.get("Quantity") or row.get("Position"))
            avg = _to_float(row.get("CostPrice") or row.get("AverageCost"))
            mv = _to_float(row.get("Value") or row.get("MarketValue"))
            currency = (row.get("Currency") or "USD").strip() or "USD"
            out.append(
                Position(
                    ticker=ticker,
                    quantity=qty,
                    average_cost=avg,
                    market_value=mv,
                    currency=currency,
                )
            )
        return out

    def _parse_simple_csv(self, csv_path: Path) -> list[Position]:
        text = self._read_text(csv_path)
        reader = csv.DictReader(io.StringIO(text))
        out: list[Position] = []
        for raw in reader:
            row = {(k or "").strip().lower(): v for k, v in raw.items()}
            ticker = (row.get("ticker") or row.get("symbol") or "").strip().upper()
            if not ticker:
                continue
            qty = _to_float(row.get("quantity") or row.get("qty"))
            price = _to_float(row.get("price") or row.get("cost"))
            out.append(
                Position(
                    ticker=ticker,
                    quantity=qty,
                    average_cost=price,
                    market_value=qty * price if price else 0.0,
                )
            )
        return out

    # ---------- Normalization ----------

    def _normalize_positions(self, positions: list[Position]) -> list[Position]:
        """Drop closed/FX/options, sum duplicates, sort by market value."""
        merged: dict[str, Position] = {}
        for pos in positions:
            if pos.asset_type in {"FX", "CASH"}:
                continue
            if pos.asset_type == "OPT":
                logger.info("Skipping option position %s", pos.ticker)
                continue
            if pos.quantity == 0:
                continue

            key = pos.ticker
            if key in merged:
                merged[key] = _merge_positions(merged[key], pos)
            else:
                merged[key] = pos

        return sorted(
            merged.values(),
            key=lambda p: (p.market_value or p.total_cost or 0.0),
            reverse=True,
        )

    def _enrich_with_sector(self, positions: list[Position]) -> list[Position]:
        for pos in positions:
            if pos.sector:
                continue
            try:
                info = self.market_data.get_company_info(pos.ticker)  # type: ignore[attr-defined]
            except Exception:
                continue
            pos.sector = info.get("sector", "") or ""
            pos.company_name = pos.company_name or info.get("long_name", "")
        return positions

    # ---------- Fallbacks ----------

    def _fallback_to_config(self) -> list[Position]:
        if not self.config_tickers:
            logger.warning("Portfolio is empty and no fallback tickers configured")
            return []
        return [Position(ticker=t.strip().upper(), quantity=0) for t in self.config_tickers if t]

    # ---------- File reading ----------

    @staticmethod
    def _read_text(csv_path: Path) -> str:
        raw = csv_path.read_bytes()
        # Skip BOM if present.
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        # Try UTF-8 first, then Windows-1252 (common for Excel exports).
        for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def _position_from_activity_row(fields: dict[str, str]) -> Position | None:
        ticker = (fields.get("Symbol") or "").strip().upper()
        if not ticker:
            return None
        qty = _to_float(fields.get("Quantity"))
        cost_price = _to_float(fields.get("Cost Price") or fields.get("CostPrice"))
        market_value = _to_float(fields.get("Value") or fields.get("Market Value"))
        currency = (fields.get("Currency") or "USD").strip() or "USD"
        asset_type = (fields.get("Asset Category") or "STK").strip() or "STK"
        # Activity Statement иногда даёт лишь Cost Basis (= qty * cost_price).
        if not cost_price:
            cost_basis = _to_float(fields.get("Cost Basis"))
            if cost_basis and qty:
                cost_price = cost_basis / qty
        return Position(
            ticker=ticker,
            quantity=qty,
            average_cost=cost_price,
            market_value=market_value,
            currency=currency,
            asset_type=asset_type,
        )


# ---------- Helpers ----------


def _to_float(value: str | float | int | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    text = text.replace(",", "").replace("$", "").replace("%", "")
    if text in {"-", "—", "N/A", "NA"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _merge_positions(a: Position, b: Position) -> Position:
    total_qty = a.quantity + b.quantity
    if total_qty == 0:
        return a
    avg = ((a.average_cost * a.quantity) + (b.average_cost * b.quantity)) / total_qty
    return Position(
        ticker=a.ticker,
        quantity=total_qty,
        average_cost=avg,
        market_value=(a.market_value or 0.0) + (b.market_value or 0.0),
        currency=a.currency,
        asset_type=a.asset_type,
        sector=a.sector or b.sector,
        company_name=a.company_name or b.company_name,
    )
