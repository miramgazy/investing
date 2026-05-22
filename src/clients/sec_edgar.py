"""SEC EDGAR API client.

Минимальный набор для нужд монитора инсайдеров:
* список последних подач компании по CIK,
* детали Form 4 (имя + должность + тип сделки + сумма).

SEC требует валидный ``User-Agent`` и не любит больше 10 запросов в секунду.
Соблюдаем оба требования: User-Agent передаём явно, между запросами ставим
короткую задержку.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from typing import Final

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.constants import DEFAULT_SEC_USER_AGENT
from src.utils.logger import get_logger

_BASE_URL: Final = "https://data.sec.gov"
_ARCHIVE_URL: Final = "https://www.sec.gov/Archives"
_REQUEST_TIMEOUT: Final = 30
_MIN_REQUEST_INTERVAL: Final = 0.11  # ≈9 req/sec, под лимитом 10/sec.


class SECEdgarClient:
    """Thin wrapper over the EDGAR submissions / Archives endpoints."""

    def __init__(self, user_agent: str = DEFAULT_SEC_USER_AGENT) -> None:
        if not user_agent or "@" not in user_agent:
            raise ValueError(
                "SEC EDGAR требует User-Agent в формате 'Name email@example.com'. "
                "Заполни поле profile.contact_email в config.yaml."
            )
        self._user_agent = user_agent
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip",
                "Accept": "application/json",
            }
        )
        self._logger = get_logger("sec_edgar")
        self._last_request_at: float = 0.0

    # ---------- Public API ----------

    def get_recent_filings(
        self,
        cik: str,
        form_type: str = "4",
        days: int = 1,
    ) -> list[dict]:
        """Return recent filings of ``form_type`` for the given CIK.

        Args:
            cik: 10-digit zero-padded CIK (use :meth:`TickerUtils.get_cik`).
            form_type: e.g. ``"4"`` (insiders), ``"8-K"`` (material events).
            days: how many days back to consider.

        Returns:
            List of dicts with ``form``, ``filed_at``, ``accession_number``,
            ``primary_document`` keys. Empty if nothing matches or on error.
        """
        if not cik:
            return []
        url = f"{_BASE_URL}/submissions/CIK{cik}.json"
        try:
            payload = self._get_json(url)
        except requests.HTTPError as exc:
            self._logger.warning("EDGAR submissions error for CIK %s: %s", cik, exc)
            return []
        except requests.RequestException as exc:
            self._logger.warning("EDGAR network error for CIK %s: %s", cik, exc)
            return []

        recent = payload.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        accession_numbers = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])

        cutoff = datetime.now().date() - timedelta(days=days)
        out: list[dict] = []
        for i, form in enumerate(forms):
            if form != form_type:
                continue
            try:
                filed_at = datetime.strptime(filing_dates[i], "%Y-%m-%d").date()
            except (IndexError, ValueError):
                continue
            if filed_at < cutoff:
                continue
            out.append(
                {
                    "form": form,
                    "filed_at": filed_at.isoformat(),
                    "accession_number": accession_numbers[i] if i < len(accession_numbers) else "",
                    "primary_document": primary_docs[i] if i < len(primary_docs) else "",
                    "cik": cik.lstrip("0") or "0",
                }
            )
        return out

    def get_form4_details(self, cik: str, accession_number: str) -> dict:
        """Pull and lightly parse the Form 4 XML for a single filing.

        Returns a dict with keys ``insider_name``, ``insider_title``,
        ``transaction_type`` (``P`` purchase / ``S`` sale / ``A`` award /
        ``D`` disposition / ``M`` exercise / ``G`` gift / ``""``),
        ``shares``, ``price_per_share``, ``total_value``.

        On any parsing error the dict is empty.
        """
        accession_clean = accession_number.replace("-", "")
        url = f"{_ARCHIVE_URL}/edgar/data/{cik.lstrip('0') or '0'}/{accession_clean}/{accession_number}-index.htm"
        try:
            index_html = self._get_text(url)
        except requests.RequestException as exc:
            self._logger.debug("Form4 index unreachable: %s", exc)
            return {}

        # Ищем .xml файл в индексе.
        xml_match = re.search(r'href="([^"]+\.xml)"', index_html)
        if not xml_match:
            return {}
        xml_href = xml_match.group(1)
        if xml_href.startswith("/"):
            xml_url = f"https://www.sec.gov{xml_href}"
        else:
            xml_url = (
                f"{_ARCHIVE_URL}/edgar/data/"
                f"{cik.lstrip('0') or '0'}/{accession_clean}/{xml_href}"
            )

        try:
            xml = self._get_text(xml_url)
        except requests.RequestException as exc:
            self._logger.debug("Form4 XML unreachable: %s", exc)
            return {}

        return _parse_form4_xml(xml)

    def get_company_filings_url(self, cik: str) -> str:
        """Human-facing URL for use in Telegram notifications."""
        clean = cik.lstrip("0") or "0"
        return (
            f"https://www.sec.gov/cgi-bin/browse-edgar?"
            f"action=getcompany&CIK={clean}&type=4&dateb=&owner=include&count=40"
        )

    # ---------- Internals ----------

    def _throttle(self) -> None:
        """Sleep just enough to stay under SEC's 10 req/sec cap."""
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_at = time.monotonic()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
        reraise=True,
    )
    def _get_json(self, url: str) -> dict:
        self._throttle()
        response = self._session.get(url, timeout=_REQUEST_TIMEOUT)
        if response.status_code == 429:
            time.sleep(2)
            raise requests.HTTPError("429 Too Many Requests", response=response)
        response.raise_for_status()
        return response.json()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
        reraise=True,
    )
    def _get_text(self, url: str) -> str:
        self._throttle()
        response = self._session.get(url, timeout=_REQUEST_TIMEOUT)
        if response.status_code == 429:
            time.sleep(2)
            raise requests.HTTPError("429 Too Many Requests", response=response)
        response.raise_for_status()
        response.encoding = response.encoding or "utf-8"
        return response.text


# ---------- Form 4 XML parsing ----------


def _parse_form4_xml(xml: str) -> dict:
    """Extract the fields we care about from a Form 4 XML document."""
    def _first(pattern: str) -> str:
        m = re.search(pattern, xml, re.IGNORECASE | re.DOTALL)
        return (m.group(1).strip() if m else "")

    name = _first(r"<rptOwnerName>(.*?)</rptOwnerName>")
    title = ""
    if re.search(r"<isDirector>\s*1\s*</isDirector>", xml):
        title = "Director"
    if re.search(r"<isOfficer>\s*1\s*</isOfficer>", xml):
        officer_title = _first(r"<officerTitle>(.*?)</officerTitle>") or "Officer"
        title = officer_title if title == "" else f"{officer_title}, {title}"
    if re.search(r"<isTenPercentOwner>\s*1\s*</isTenPercentOwner>", xml):
        title = title or "10% Owner"

    transaction_code = _first(
        r"<transactionCode>(.*?)</transactionCode>"
    )
    shares = _first(
        r"<transactionShares>.*?<value>([\d\.]+)</value>"
    )
    price = _first(
        r"<transactionPricePerShare>.*?<value>([\d\.]+)</value>"
    )

    try:
        shares_f = float(shares) if shares else 0.0
        price_f = float(price) if price else 0.0
    except ValueError:
        shares_f = 0.0
        price_f = 0.0

    return {
        "insider_name": name,
        "insider_title": title,
        "transaction_type": transaction_code.upper(),
        "shares": shares_f,
        "price_per_share": price_f,
        "total_value": shares_f * price_f,
    }
