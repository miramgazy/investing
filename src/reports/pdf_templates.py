"""Dark / light themes and ParagraphStyles for the weekly PDF.

Цветовая палитра проектируется под "Bloomberg-look": тёмный фон, акцент
cyan, зелёный/красный для P&L. Цвета вынесены в одно место — поменял
``accent_color`` в ``config.yaml`` и весь отчёт перекрасился.

Шрифт — DejaVu Sans (bundled с matplotlib): единственный гарантированно
доступный TTF с поддержкой кириллицы. Helvetica reportlab'а — Type-1
шрифт без кириллических глифов, на русском тексте даёт квадратики.
"""

from __future__ import annotations

import contextlib
import os
from typing import Final

import matplotlib
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ---------- Font registration ----------

_FONT_REGULAR: Final = "WatchdogSans"
_FONT_BOLD: Final = "WatchdogSans-Bold"
_FONT_OBLIQUE: Final = "WatchdogSans-Oblique"

_FONT_REGISTERED = False


def _register_fonts() -> None:
    """Register DejaVu Sans (bundled with matplotlib) as our PDF font family.

    Without this, ``reportlab.Helvetica`` is used — а у него нет кириллицы и
    почти нет unicode-символов, что превращает русский текст в квадратики.
    Идемпотентно: повторные вызовы no-op.
    """
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return

    mpl_ttf_dir = os.path.join(
        os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf"
    )
    candidates = {
        _FONT_REGULAR: "DejaVuSans.ttf",
        _FONT_BOLD: "DejaVuSans-Bold.ttf",
        _FONT_OBLIQUE: "DejaVuSans-Oblique.ttf",
    }
    for name, filename in candidates.items():
        path = os.path.join(mpl_ttf_dir, filename)
        if os.path.exists(path):
            # Already-registered fonts or other reportlab edge cases are fine.
            with contextlib.suppress(Exception):
                pdfmetrics.registerFont(TTFont(name, path))

    # Bind the family so that <b>..</b> / <i>..</i> inside Paragraph picks the
    # right TTF instead of falling back to Helvetica.
    with contextlib.suppress(Exception):
        from reportlab.pdfbase.pdfmetrics import registerFontFamily

        registerFontFamily(
            _FONT_REGULAR,
            normal=_FONT_REGULAR,
            bold=_FONT_BOLD,
            italic=_FONT_OBLIQUE,
            boldItalic=_FONT_BOLD,
        )

    _FONT_REGISTERED = True


_register_fonts()


class PDFTheme:
    bg_primary: HexColor
    bg_secondary: HexColor
    text_primary: HexColor
    text_secondary: HexColor
    accent: HexColor
    success: HexColor
    danger: HexColor
    warning: HexColor
    divider: HexColor

    def __init__(self, theme: str = "dark", accent: str = "#00d4ff") -> None:
        if theme == "dark":
            self.bg_primary = HexColor("#0a0e27")
            self.bg_secondary = HexColor("#1a1f3a")
            self.text_primary = HexColor("#ffffff")
            self.text_secondary = HexColor("#9ca3af")
            self.success = HexColor("#10b981")
            self.danger = HexColor("#ef4444")
            self.warning = HexColor("#f59e0b")
            self.divider = HexColor("#2d3548")
        else:  # light
            self.bg_primary = HexColor("#ffffff")
            self.bg_secondary = HexColor("#f9fafb")
            self.text_primary = HexColor("#111827")
            self.text_secondary = HexColor("#6b7280")
            self.success = HexColor("#059669")
            self.danger = HexColor("#dc2626")
            self.warning = HexColor("#d97706")
            self.divider = HexColor("#e5e7eb")
        self.theme_name = theme
        self.accent = HexColor(accent if accent else "#00d4ff")

    # ---------- Styles ----------

    def get_styles(self) -> dict[str, ParagraphStyle]:
        return {
            "title": ParagraphStyle(
                "Title",
                fontName=_FONT_BOLD,
                fontSize=30,
                textColor=self.text_primary,
                alignment=TA_LEFT,
                leading=34,
                spaceAfter=10,
            ),
            "subtitle": ParagraphStyle(
                "Subtitle",
                fontName=_FONT_REGULAR,
                fontSize=13,
                textColor=self.text_secondary,
                alignment=TA_LEFT,
                spaceAfter=20,
            ),
            "h1": ParagraphStyle(
                "H1",
                fontName=_FONT_BOLD,
                fontSize=20,
                textColor=self.text_primary,
                spaceBefore=14,
                spaceAfter=10,
            ),
            "h2": ParagraphStyle(
                "H2",
                fontName=_FONT_BOLD,
                fontSize=14,
                textColor=self.accent,
                spaceBefore=10,
                spaceAfter=6,
            ),
            "body": ParagraphStyle(
                "Body",
                fontName=_FONT_REGULAR,
                fontSize=10.5,
                textColor=self.text_primary,
                leading=15,
                spaceAfter=6,
            ),
            "body_secondary": ParagraphStyle(
                "BodySecondary",
                fontName=_FONT_REGULAR,
                fontSize=10,
                textColor=self.text_secondary,
                leading=14,
                spaceAfter=6,
            ),
            "metric_label": ParagraphStyle(
                "MetricLabel",
                fontName=_FONT_REGULAR,
                fontSize=9,
                textColor=self.text_secondary,
                alignment=TA_CENTER,
            ),
            "metric_value": ParagraphStyle(
                "MetricValue",
                fontName=_FONT_BOLD,
                fontSize=17,
                textColor=self.text_primary,
                alignment=TA_CENTER,
                leading=21,
            ),
            "metric_change_positive": ParagraphStyle(
                "MetricChangePos",
                fontName=_FONT_BOLD,
                fontSize=11,
                textColor=self.success,
                alignment=TA_CENTER,
            ),
            "metric_change_negative": ParagraphStyle(
                "MetricChangeNeg",
                fontName=_FONT_BOLD,
                fontSize=11,
                textColor=self.danger,
                alignment=TA_CENTER,
            ),
            "disclaimer": ParagraphStyle(
                "Disclaimer",
                fontName=_FONT_OBLIQUE,
                fontSize=8.5,
                textColor=self.text_secondary,
                alignment=TA_CENTER,
                leading=12,
            ),
        }


DISCLAIMER_TEXT: Final = (
    "<b>ВАЖНО:</b> Данный отчёт не является инвестиционной рекомендацией. "
    "Все данные получены из публичных источников. Аналитические наблюдения "
    "сгенерированы AI и не заменяют консультацию профессионального финансового "
    "советника. Решения о покупке/продаже принимает исключительно пользователь."
)
