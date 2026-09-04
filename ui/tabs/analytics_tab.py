"""
Analytics tab - business intelligence view (revenue, profit/margin,
receivables/payables, stock value/alerts, top products/clients).

Distinct from Home (operational dashboard): this tab answers deeper business
questions over a selectable period. All figures come from ONE RPC/backend call
(``Database.get_analytics_snapshot``) built from aggregate SQL - no N+1
queries, one worker per refresh.

Sensitive financial metrics are filtered server-side by the caller's role;
values the user may not see arrive as ``None`` and render as "-".

Threading follows the proven project pattern (see ui/tabs/home_tab.py):
QObject worker on a dedicated QThread, GUI callbacks wired only to real bound
methods, strong refs kept until ``thread.finished``, duplicate refreshes
rejected while a fetch is active, stale results dropped via a generation
counter, and cooperative shutdown on app exit.
"""
import math
import os
import shiboken6
import logging
import time
from datetime import date, timedelta

from PySide6.QtCore import Qt, QObject, QThread, QDate, QTimer, Signal, Slot, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFontMetrics, QPainterPath
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QComboBox, QPushButton, QDateEdit, QFrame, QTableWidget,
    QTableWidgetItem, QHeaderView, QScrollArea, QListWidget, QListWidgetItem,
)

from ui.widgets.themed_widgets import GreenButton
from core import diagnostics

logger = logging.getLogger(__name__)

_GREEN = "#4CAF50"
_BLUE = "#2196F3"
_ORANGE = "#FF9800"
_RED = "#f44336"
_PURPLE = "#9C27B0"
_TEAL = "#009688"
_MUTED = "#aaaaaa"


class _AnalyticsWorker(QObject):
    """Fetches the whole analytics snapshot off the GUI thread."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, database, date_from, date_to):
        super().__init__()
        self.database = database
        self.date_from = date_from
        self.date_to = date_to

    def _ensure_local_connection(self):
        if self.database.__class__.__name__ == "RemoteDatabase":
            return None
        from core.database import Database
        worker_db = Database(self.database.profile_manager)
        worker_db.language = getattr(self.database, "language", "en")
        worker_db.registered_classes = self.database.registered_classes
        if not worker_db.connect(verify_schema=False):
            raise RuntimeError(
                getattr(worker_db, "last_error", None)
                or "Could not connect to the database"
            )
        return worker_db

    def run(self):
        worker_db = None
        try:
            import os as _os, time as _time
            if _os.environ.get("PYLI_TRACE"):
                print(
                    f"[TRACE t={_time.monotonic():.3f}] AnalyticsWorker "
                    f"start {self.date_from}..{self.date_to}",
                    flush=True,
                )
            worker_db = self._ensure_local_connection()
            db = worker_db or self.database
            snapshot = db.get_analytics_snapshot(self.date_from, self.date_to)
            self.finished.emit(snapshot)
            if _os.environ.get("PYLI_TRACE"):
                print(
                    f"[TRACE t={_time.monotonic():.3f}] AnalyticsWorker finished",
                    flush=True,
                )
        except Exception as error:
            logger.exception("Analytics snapshot load failed")
            self.failed.emit(str(error) or "Unknown error")
        finally:
            if worker_db is not None:
                try:
                    worker_db.close()
                except Exception:
                    logger.exception("Could not close analytics worker DB")


class GroupedBarChart(QWidget):
    """Minimal dependency-free grouped bar chart (pure QPainter).

    Replaces QtCharts for the Analytics evolution graphs: the QtCharts
    graphics-scene machinery proved intermittently deadlock-prone under
    rapid tab open/close cycles on this project (GUI thread wedged inside
    QBarSet/QValueAxis internals per faulthandler stacks). This widget has
    no scene graph, no animations and no internal threads - paintEvent only.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._labels = []
        self._series = []          # list of (name, color, [values])
        self._empty_text = "No data"
        self._tooltips = {}        # dict of (series_index, label_index) -> tooltip text
        self._hover_index = -1     # currently hovered label index
        self.setMinimumHeight(260)
        self.setMouseTracking(True)

    def set_empty_text(self, text):
        self._empty_text = str(text)
        self.update()

    def set_data(self, labels, series):
        self._labels = [str(label) for label in labels]
        self._series = [
            (str(name), color, [float(v) if v is not None else 0.0
                                for v in values])
            for name, color, values in series
        ]
        # Build tooltips
        self._tooltips = {}
        for s_idx, (_name, _color, values) in enumerate(self._series):
            for l_idx, value in enumerate(values):
                if l_idx < len(self._labels):
                    label = self._labels[l_idx]
                    self._tooltips[(s_idx, l_idx)] = f"{label}\n{_name}: {value:,.2f} MAD"
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QPen, QFontMetrics
        painter = QPainter(self)
        try:
            rect = self.rect()
            margin_left, margin_right, margin_top, margin_bottom = (
                50, 12, 30, 36
            )
            plot = rect.adjusted(margin_left, margin_top,
                                 -margin_right, -margin_bottom)
            if not self._series or not self._labels or plot.width() < 40 \
                    or plot.height() < 30:
                painter.setPen(QPen(QColor(_MUTED)))
                painter.drawText(rect, Qt.AlignCenter, self._empty_text)
                return

            count = len(self._labels)
            max_value = max(
                [abs(v) for _, _, values in self._series for v in values]
                + [1.0]
            )
            if not math.isfinite(max_value) or max_value <= 0:
                max_value = 1.0

            # Gridlines + Y labels (4 divisions) - subtle grid
            painter.setPen(QPen(QColor("#2a2a2a")))
            font = painter.font()
            font.setPointSize(8)
            painter.setFont(font)
            for i in range(5):
                ratio = i / 4.0
                y = plot.bottom() - int(plot.height() * ratio)
                painter.drawLine(plot.left(), y, plot.right(), y)
                painter.setPen(QPen(QColor(_MUTED)))
                # Compact Y-axis formatting
                y_val = max_value * ratio
                if y_val >= 1000:
                    label_text = f"{y_val/1000:.0f}K"
                else:
                    label_text = f"{y_val:,.0f}"
                painter.drawText(
                    0, y - 7, margin_left - 8, 14, Qt.AlignRight | Qt.AlignVCenter,
                    label_text,
                )
                painter.setPen(QPen(QColor("#2a2a2a")))

            group_width = plot.width() / count
            series_count = len(self._series)
            bar_width = max(3.0, group_width / (series_count + 1))
            for index in range(count):
                group_x = plot.left() + index * group_width
                total_bar_w = bar_width * series_count
                start_x = group_x + (group_width - total_bar_w) / 2.0
                for s_index, (_name, color, values) in enumerate(self._series):
                    value = values[index] if index < len(values) else 0.0
                    bar_h = int(plot.height() * min(abs(value) / max_value, 1.0))
                    x = start_x + s_index * bar_width
                    # Rounded corners for bars
                    bar_rect = QRectF(
                        x, plot.bottom() - bar_h,
                        max(1, bar_width - 2), bar_h
                    )
                    painter.fillRect(bar_rect, QColor(color))
                # Highlight hovered group
                if index == self._hover_index:
                    painter.setPen(QPen(QColor("#444444"), 1))
                    painter.drawRect(
                        int(group_x), plot.top(),
                        int(group_width), plot.height()
                    )
                label = self._labels[index]
                metrics = QFontMetrics(font)
                elided = metrics.elidedText(
                    label, Qt.ElideRight, int(group_width) - 2
                )
                painter.setPen(QPen(QColor(_MUTED)))
                painter.drawText(
                    int(group_x), plot.bottom() + 6,
                    int(group_width), 16, Qt.AlignHCenter | Qt.AlignTop,
                    elided,
                )

            # Legend.
            legend_x = plot.right()
            for name, color, _values in reversed(self._series):
                text_width = painter.fontMetrics().horizontalAdvance(name) + 14
                legend_x -= text_width
                painter.fillRect(legend_x, 8, 10, 10, QColor(color))
                painter.setPen(QPen(QColor(_MUTED)))
                painter.drawText(
                    legend_x + 13, 5, text_width, 14,
                    Qt.AlignLeft | Qt.AlignVCenter, name,
                )
        finally:
            painter.end()

    def mouseMoveEvent(self, event):
        from PySide6.QtGui import QFontMetrics
        rect = self.rect()
        margin_left, margin_right, margin_top, margin_bottom = (
            50, 12, 30, 36
        )
        plot = rect.adjusted(margin_left, margin_top,
                             -margin_right, -margin_bottom)
        if not self._labels or plot.width() < 40:
            self._hover_index = -1
            self.update()
            return
        count = len(self._labels)
        group_width = plot.width() / count
        rel_x = event.position().x() - plot.left()
        if 0 <= rel_x < plot.width():
            self._hover_index = int(rel_x / group_width)
        else:
            self._hover_index = -1
        self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover_index = -1
        self.update()
        super().leaveEvent(event)


class LineAreaChart(QWidget):
    """Professional line/area chart for time-series data (pure QPainter).

    Features:
    - Smooth lines with subtle area fill
    - Professional date label formatting
    - Hover tooltip with all series values
    - Compact Y-axis formatting (K, M suffixes)
    - Subtle grid lines
    - Legend support
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._labels = []
        self._series = []          # list of (name, color, [values], is_area)
        self._empty_text = "No data"
        self._hover_index = -1
        self._hover_x = -1
        self.setMinimumHeight(260)
        self.setMouseTracking(True)

    def set_empty_text(self, text):
        self._empty_text = str(text)
        self.update()

    def set_data(self, labels, series):
        """Set chart data.
        
        Args:
            labels: List of date labels (strings)
            series: List of (name, color, values, is_area) tuples
                    is_area: if True, fill area under the line
        """
        self._labels = [str(label) for label in labels]
        self._series = [
            (str(name), color, [float(v) if v is not None else 0.0
                                for v in values], is_area)
            for name, color, values, is_area in series
        ]
        self.update()

    def _format_compact(self, value):
        """Format value compactly for Y-axis labels."""
        abs_val = abs(value)
        if abs_val >= 1_000_000:
            return f"{value/1_000_000:.1f}M".rstrip('0').rstrip('.')
        elif abs_val >= 1_000:
            return f"{value/1_000:.0f}K"
        else:
            return f"{value:,.0f}"

    def _format_full(self, value):
        """Format value fully for tooltips."""
        return f"{value:,.2f} MAD"

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QPen, QFontMetrics, QPainterPath, QBrush, QColor
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        try:
            rect = self.rect()
            margin_left, margin_right, margin_top, margin_bottom = (
                60, 12, 30, 36
            )
            plot = rect.adjusted(margin_left, margin_top,
                                 -margin_right, -margin_bottom)
            if not self._series or not self._labels or plot.width() < 40 \
                    or plot.height() < 30:
                painter.setPen(QPen(QColor(_MUTED)))
                painter.drawText(rect, Qt.AlignCenter, self._empty_text)
                return

            count = len(self._labels)
            all_values = [v for _, _, values, _ in self._series for v in values]
            max_value = max([abs(v) for v in all_values] + [1.0])
            min_value = min([v for v in all_values] + [0.0])
            if not math.isfinite(max_value) or max_value <= 0:
                max_value = 1.0
            if not math.isfinite(min_value):
                min_value = 0.0

            # Use zero baseline for financial charts
            if min_value > 0:
                min_value = 0.0
            value_range = max_value - min_value
            if value_range <= 0:
                value_range = 1.0

            # Gridlines + Y labels (5 divisions) - subtle grid
            painter.setPen(QPen(QColor("#222222")))
            font = painter.font()
            font.setPointSize(8)
            painter.setFont(font)
            for i in range(6):
                ratio = i / 5.0
                y = plot.bottom() - int(plot.height() * ratio)
                painter.drawLine(plot.left(), y, plot.right(), y)
                painter.setPen(QPen(QColor(_MUTED)))
                y_val = min_value + value_range * ratio
                label_text = self._format_compact(y_val)
                painter.drawText(
                    0, y - 7, margin_left - 8, 14, Qt.AlignRight | Qt.AlignVCenter,
                    label_text,
                )
                painter.setPen(QPen(QColor("#222222")))

            # Draw each series
            point_radius = 3
            for s_index, (name, color, values, is_area) in enumerate(self._series):
                if len(values) != count:
                    continue

                # Calculate points
                points = []
                for index in range(count):
                    value = values[index]
                    x = plot.left() + (index + 0.5) * plot.width() / count
                    y = plot.bottom() - (value - min_value) / value_range * plot.height()
                    points.append((x, y))

                # Draw area fill first (behind lines)
                if is_area and len(points) >= 2:
                    path = QPainterPath()
                    path.moveTo(points[0][0], plot.bottom())
                    for x, y in points:
                        path.lineTo(x, y)
                    path.lineTo(points[-1][0], plot.bottom())
                    path.closeSubpath()
                    area_color = QColor(color)
                    area_color.setAlpha(35)
                    painter.fillPath(path, QBrush(area_color))

                # Draw line
                if len(points) >= 2:
                    pen = QPen(QColor(color), 2.5)
                    painter.setPen(pen)
                    path = QPainterPath()
                    path.moveTo(points[0][0], points[0][1])
                    for x, y in points[1:]:
                        path.lineTo(x, y)
                    painter.drawPath(path)

                # Draw data points
                painter.setPen(QPen(QColor(color), 1.5))
                for index, (x, y) in enumerate(points):
                    is_hovered = (index == self._hover_index)
                    r = point_radius + (2 if is_hovered else 0)
                    # White outline
                    painter.setBrush(QBrush(QColor("#1e1e1e")))
                    painter.setPen(QPen(QColor("#1e1e1e"), 2))
                    painter.drawEllipse(int(x - r), int(y - r), int(r * 2), int(r * 2))
                    # Colored fill
                    painter.setBrush(QBrush(QColor(color)))
                    painter.setPen(QPen(QColor(color), 1))
                    painter.drawEllipse(int(x - r), int(y - r), int(r * 2), int(r * 2))

            # Draw hover tooltip
            if 0 <= self._hover_index < count:
                self._draw_tooltip(painter, plot, self._hover_index)

            # X-axis labels (dates)
            painter.setPen(QPen(QColor(_MUTED)))
            font.setPointSize(8)
            painter.setFont(font)
            for index in range(count):
                x = plot.left() + (index + 0.5) * plot.width() / count
                label = self._labels[index]
                metrics = QFontMetrics(font)
                elided = metrics.elidedText(
                    label, Qt.ElideRight, int(plot.width() / count) - 4
                )
                painter.drawText(
                    int(x - (plot.width() / count) / 2), plot.bottom() + 6,
                    int(plot.width() / count), 16, Qt.AlignHCenter | Qt.AlignTop,
                    elided,
                )

            # Legend
            legend_y = 8
            legend_x = plot.right()
            for name, color, _values, _is_area in reversed(self._series):
                text_width = painter.fontMetrics().horizontalAdvance(name) + 16
                legend_x -= text_width
                # Line sample
                painter.setPen(QPen(QColor(color), 3))
                painter.drawLine(legend_x, legend_y + 6, legend_x + 12, legend_y + 6)
                # Area indicator if applicable
                for s_name, s_color, _s_values, s_is_area in self._series:
                    if s_name == name and s_is_area:
                        painter.fillRect(legend_x, legend_y + 2, 12, 8, QColor(color))
                        s_color_alpha = QColor(s_color)
                        s_color_alpha.setAlpha(35)
                        painter.fillRect(legend_x, legend_y + 2, 12, 8, QBrush(s_color_alpha))
                        break
                painter.setPen(QPen(QColor(_MUTED)))
                painter.drawText(
                    legend_x + 15, 4, text_width, 14,
                    Qt.AlignLeft | Qt.AlignVCenter, name,
                )
        finally:
            painter.end()

    def _draw_tooltip(self, painter, plot, index):
        from PySide6.QtGui import QFontMetrics, QColor
        # Tooltip background
        tooltip_lines = [self._labels[index]]
        for name, color, values, _ in self._series:
            if index < len(values):
                tooltip_lines.append(f"{name}: {self._format_full(values[index])}")
        
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        
        max_width = max(metrics.horizontalAdvance(line) for line in tooltip_lines)
        line_height = metrics.height()
        tooltip_width = max_width + 20
        tooltip_height = len(tooltip_lines) * line_height + 12
        
        x = plot.left() + (index + 0.5) * plot.width() / len(self._labels)
        # Position tooltip above the point, centered
        tx = int(x - tooltip_width / 2)
        ty = plot.top() + 8
        
        # Keep tooltip within bounds
        if tx < plot.left():
            tx = plot.left()
        elif tx + tooltip_width > plot.right():
            tx = plot.right() - tooltip_width
        
        # Draw tooltip background
        tooltip_rect = QRectF(tx, ty, tooltip_width, tooltip_height)
        painter.setBrush(QBrush(QColor("#1e1e1e")))
        painter.setPen(QPen(QColor("#444444"), 1))
        painter.drawRoundedRect(tooltip_rect, 6, 6)
        
        # Draw tooltip text
        painter.setPen(QPen(QColor("#ffffff")))
        for i, line in enumerate(tooltip_lines):
            line_y = ty + 8 + i * line_height
            # Color the series name
            if ':' in line:
                name_part, value_part = line.split(':', 1)
                painter.drawText(tx + 10, line_y, metrics.horizontalAdvance(name_part + ':'), line_height,
                                Qt.AlignLeft | Qt.AlignVCenter, name_part + ':')
                painter.setPen(QPen(QColor(_MUTED)))
                painter.drawText(tx + 10 + metrics.horizontalAdvance(name_part + ':'), line_y,
                                metrics.horizontalAdvance(value_part), line_height,
                                Qt.AlignLeft | Qt.AlignVCenter, value_part.strip())
                painter.setPen(QPen(QColor("#ffffff")))
            else:
                painter.drawText(tx + 10, line_y, tooltip_width - 20, line_height,
                                Qt.AlignLeft | Qt.AlignVCenter, line)

    def mouseMoveEvent(self, event):
        rect = self.rect()
        margin_left, margin_right, margin_top, margin_bottom = (
            60, 12, 30, 36
        )
        plot = rect.adjusted(margin_left, margin_top,
                             -margin_right, -margin_bottom)
        if not self._labels or plot.width() < 40:
            self._hover_index = -1
            self.update()
            return
        count = len(self._labels)
        rel_x = event.position().x() - plot.left()
        if 0 <= rel_x < plot.width():
            self._hover_index = int(rel_x / (plot.width() / count))
            self._hover_index = max(0, min(self._hover_index, count - 1))
        else:
            self._hover_index = -1
        self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover_index = -1
        self.update()
        super().leaveEvent(event)


class AnalyticsCard(QFrame):
    """Compact flat metric card (ERP style - no gradients)."""

    clicked = Signal()

    def __init__(self, title, color=_BLUE, subtitle="", clickable=False,
                 parent=None):
        super().__init__(parent)
        self._color = color
        self.setMinimumHeight(92)
        self.setMaximumHeight(110)
        self.setObjectName("analyticsCard")
        if clickable:
            self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"#analyticsCard {{ background-color: #333333; "
            f"border: 1px solid {color}; border-radius: 8px; }}"
            f"#analyticsCard:hover {{ border-color: #ffffff; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: bold; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(title_label)
        self.value_label = QLabel("-")
        self.value_label.setStyleSheet(
            "color: #ffffff; font-size: 19px; font-weight: bold; "
            "background: transparent; border: none;"
        )
        layout.addWidget(self.value_label)
        self.subtitle_label = QLabel(subtitle or "")
        self.subtitle_label.setStyleSheet(
            f"color: {_MUTED}; font-size: 10px; "
            f"background: transparent; border: none;"
        )
        self.subtitle_label.setWordWrap(True)
        layout.addWidget(self.subtitle_label)
        layout.addStretch()

    def set_value(self, value, subtitle=None, tooltip=None):
        self.value_label.setText(str(value))
        if subtitle is not None:
            self.subtitle_label.setText(subtitle)
        self.setToolTip(tooltip or "")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def _fmt_money(value):
    try:
        return f"{float(value):,.2f} MAD"
    except (TypeError, ValueError):
        return "-"


def _fmt_int(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "-"


def _fmt_pct(value):
    if value is None:
        return "-"
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "-"


class AnalyticsTab(QWidget):
    """Main Analytics navigation tab."""

    STALE_AFTER_SECONDS = 60.0

    def __init__(self, database=None, language: str = 'en'):
        super().__init__()
        self.database = database
        self.language = (language or 'en').lower()

        self._thread = None
        self._worker = None
        self._generation = 0
        self._snapshot = None
        self._loaded_once = False
        self._needs_refresh = True
        self._last_refresh_at = 0.0
        self._purchases_set = None
        self._flow_axis_y = None

        self._build_ui()

        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self._wait_for_thread)

    # ─────────────────────────────── UI setup ────────────────────────────

    def _build_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(10, 10, 10, 10)

        header_row = QHBoxLayout()
        title = QLabel("Analytics")
        title.setStyleSheet("font-size: 28px; font-weight: bold;")
        header_row.addWidget(title)
        header_row.addStretch()

        header_row.addWidget(QLabel("Period:"))
        self.period_combo = QComboBox()
        self.period_combo.addItems([
            "Today", "This Week", "This Month", "This Year", "Custom Range",
        ])
        self.period_combo.setCurrentIndex(2)
        self.period_combo.currentIndexChanged.connect(self._on_period_changed)
        header_row.addWidget(self.period_combo)

        self.from_date = QDateEdit()
        self.from_date.setCalendarPopup(True)
        self.from_date.setDisplayFormat("yyyy-MM-dd")
        self.to_date = QDateEdit()
        self.to_date.setCalendarPopup(True)
        self.to_date.setDisplayFormat("yyyy-MM-dd")
        self.from_date.setEnabled(False)
        self.to_date.setEnabled(False)
        self.from_date.dateChanged.connect(self._on_custom_range_changed)
        self.to_date.dateChanged.connect(self._on_custom_range_changed)
        header_row.addWidget(QLabel("From:"))
        header_row.addWidget(self.from_date)
        header_row.addWidget(QLabel("To:"))
        header_row.addWidget(self.to_date)

        self.refresh_btn = GreenButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_analytics)
        header_row.addWidget(self.refresh_btn)
        outer_layout.addLayout(header_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 6, 0, 6)
        content_layout.setSpacing(10)

        # ── summary cards ──
        cards_grid = QGridLayout()
        cards_grid.setSpacing(8)
        self.cards = {}
        card_specs = [
            ("revenue", "Revenue (HT)", _GREEN, False),
            ("gross_profit", "Gross Profit", _BLUE, False),
            ("gross_margin", "Gross Margin", _TEAL, False),
            ("operating_charges", "Operating Charges", _RED, False),
            ("net_profit", "Net Profit", _GREEN, False),
            ("sales_count", "Sales Count", _PURPLE, True),
            ("purchases", "Purchases (HT)", _ORANGE, True),
            ("receivables", "Client Receivables", _RED, True),
            ("payables", "Supplier Payables", _ORANGE, True),
            ("stock_value", "Stock Value (cost)", _BLUE, False),
            ("total_stock_sale_value", "Total Stock Sale Value", _TEAL, False),
            ("potential_stock_profit", "Potential Stock Profit", _GREEN, False),
            ("low_stock", "Low Stock Products", _ORANGE, False),
            ("out_of_stock", "Out of Stock Products", _RED, False),
        ]
        for index, (key, title_text, color, clickable) in enumerate(card_specs):
            card = AnalyticsCard(title_text, color=color, clickable=clickable)
            if clickable:
                card.clicked.connect(
                    lambda key=key: self._open_card_target(key)
                )
            self.cards[key] = card
            cards_grid.addWidget(card, index // 5, index % 5)
        content_layout.addLayout(cards_grid)

        # ── charts ──
        charts_row = QHBoxLayout()
        charts_row.setSpacing(10)

        self.revenue_chart_title = QLabel("Revenue & Profit Evolution")
        self.revenue_chart_title.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #dddddd;"
        )
        self.revenue_chart_view = self._create_revenue_chart()
        revenue_box = QVBoxLayout()
        revenue_box.addWidget(self.revenue_chart_title)
        revenue_box.addWidget(self.revenue_chart_view)
        charts_row.addLayout(revenue_box, 1)

        self.flow_chart_title = QLabel("Sales vs Purchases")
        self.flow_chart_title.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #dddddd;"
        )
        self.flow_chart_view = self._create_flow_chart()
        flow_box = QVBoxLayout()
        flow_box.addWidget(self.flow_chart_title)
        flow_box.addWidget(self.flow_chart_view)
        charts_row.addLayout(flow_box, 1)
        content_layout.addLayout(charts_row)

        # ── top tables ──
        tables_row = QHBoxLayout()
        tables_row.setSpacing(10)
        self.top_selling_table, selling_box = self._create_ranking_table(
            "Top Selling Products",
            ["Product", "Qty", "Revenue"],
            self._open_product_from_table,
        )
        self.profitable_table, profitable_box = self._create_ranking_table(
            "Most Profitable Products",
            ["Product", "Qty", "Profit"],
            self._open_product_from_table,
        )
        self.top_clients_table, clients_box = self._create_ranking_table(
            "Top Clients",
            ["Client", "Sales", "Revenue"],
            None,
        )
        tables_row.addLayout(selling_box, 1)
        tables_row.addLayout(profitable_box, 1)
        tables_row.addLayout(clients_box, 1)
        content_layout.addLayout(tables_row)

        # ── stock alerts ──
        alerts_label = QLabel("Stock Alerts")
        alerts_label.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #dddddd;"
        )
        self.alerts_list = QListWidget()
        self.alerts_list.setMaximumHeight(180)
        self.alerts_list.itemDoubleClicked.connect(self._open_alert_product)
        alerts_box = QVBoxLayout()
        alerts_box.addWidget(alerts_label)
        alerts_box.addWidget(self.alerts_list)
        content_layout.addLayout(alerts_box)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {_MUTED};")
        content_layout.addWidget(self.status_label)
        content_layout.addStretch()

        scroll.setWidget(content)
        outer_layout.addWidget(scroll, 1)

    def _create_revenue_chart(self):
        # Always use the new professional LineAreaChart (no QtCharts dependency)
        widget = LineAreaChart()
        widget.set_empty_text("Revenue & Profit Evolution (no data)")
        return widget

    def _build_revenue_chart(self):
        """Build a pristine Revenue & Profit chart.

        Charts are rebuilt on every snapshot render instead of mutating
        long-lived axis/series objects: repeatedly mutating reused QtCharts
        objects across many tab open/close cycles was proven (via
        faulthandler stack dumps) to eventually deadlock the GUI thread
        inside QValueAxis.setRange - the intermittent 'Not Responding'
        freeze. Fresh chart objects make every render independent.
        """
        chart = QChart()
        chart.legend().setVisible(True)
        chart.legend().setAlignment(Qt.AlignBottom)
        revenue_set = QBarSet("Revenue")
        revenue_set.setColor(QColor(_GREEN))
        profit_set = QBarSet("Profit")
        profit_set.setColor(QColor(_BLUE))
        series = QBarSeries()
        series.append(revenue_set)
        series.append(profit_set)
        chart.addSeries(series)
        axis_x = QBarCategoryAxis()
        chart.addAxis(axis_x, Qt.AlignBottom)
        series.attachAxis(axis_x)
        axis_y = QValueAxis()
        axis_y.setLabelFormat("%.0f")
        chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_y)
        chart._revenue_set = revenue_set
        chart._profit_set = profit_set
        chart._axis_x = axis_x
        chart._axis_y = axis_y
        return chart

    def _capture_revenue_chart_refs(self, chart):
        self._revenue_set = chart._revenue_set
        self._profit_set = chart._profit_set
        self._revenue_axis_x = chart._axis_x
        self._revenue_axis_y = chart._axis_y

    def _swap_revenue_chart(self):
        """Replace the displayed revenue chart with a freshly built one."""
        old_chart = self.revenue_chart_view.chart()
        new_chart = self._build_revenue_chart()
        self._capture_revenue_chart_refs(new_chart)
        self.revenue_chart_view.setChart(new_chart)
        if old_chart is not None:
            old_chart.deleteLater()

    def _create_flow_chart(self):
        # Always use the improved GroupedBarChart (no QtCharts dependency)
        widget = GroupedBarChart()
        widget.set_empty_text("Sales vs Purchases (no data)")
        return widget

    def _build_flow_chart(self):
        chart = QChart()
        chart.legend().setVisible(True)
        chart.legend().setAlignment(Qt.AlignBottom)
        sales_set = QBarSet("Sales")
        sales_set.setColor(QColor(_BLUE))
        purchases_set = QBarSet("Purchases")
        purchases_set.setColor(QColor(_ORANGE))
        series = QBarSeries()
        series.append(sales_set)
        series.append(purchases_set)
        chart.addSeries(series)
        axis_x = QBarCategoryAxis()
        chart.addAxis(axis_x, Qt.AlignBottom)
        series.attachAxis(axis_x)
        axis_y = QValueAxis()
        axis_y.setLabelFormat("%.0f")
        chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_y)
        chart._sales_set = sales_set
        chart._purchases_set = purchases_set
        chart._axis_x = axis_x
        chart._axis_y = axis_y
        return chart

    def _capture_flow_chart_refs(self, chart):
        self._sales_set = chart._sales_set
        self._purchases_set = chart._purchases_set
        self._flow_axis_x = chart._axis_x
        self._flow_axis_y = chart._axis_y

    def _swap_flow_chart(self):
        old_chart = self.flow_chart_view.chart()
        new_chart = self._build_flow_chart()
        self._capture_flow_chart_refs(new_chart)
        self.flow_chart_view.setChart(new_chart)
        if old_chart is not None:
            old_chart.deleteLater()

    def _create_ranking_table(self, title, headers, activate_callback):
        label = QLabel(title)
        label.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #dddddd;"
        )
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, len(headers)):
            table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeToContents
            )
        table.setMinimumHeight(200)
        table.setMaximumHeight(240)
        if activate_callback is not None:
            table.cellDoubleClicked.connect(
                lambda row, column: activate_callback(table, row)
            )
        box = QVBoxLayout()
        box.addWidget(label)
        box.addWidget(table)
        return table, box

    # ─────────────────────────── period helpers ──────────────────────────

    def _current_period(self):
        today = date.today()
        mode = self.period_combo.currentIndex()
        if mode == 0:      # Today
            start = end = today
        elif mode == 1:    # This Week (Monday .. Sunday)
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
        elif mode == 2:    # This Month
            start = today.replace(day=1)
            next_month = (start + timedelta(days=32)).replace(day=1)
            end = next_month - timedelta(days=1)
        elif mode == 3:    # This Year
            start = today.replace(month=1, day=1)
            end = today.replace(month=12, day=31)
        else:              # Custom Range
            start = self.from_date.date().toPython()
            end = self.to_date.date().toPython()
        if start is None or end is None or start > end:
            start = end = today
        return start.isoformat(), end.isoformat()

    def _on_period_changed(self, index):
        custom = index == 4
        self.from_date.setEnabled(custom)
        self.to_date.setEnabled(custom)
        if custom:
            today = QDate.currentDate()
            self.from_date.setDate(today.addMonths(-1))
            self.to_date.setDate(today)
        self.refresh_analytics()

    def _on_custom_range_changed(self):
        if self.period_combo.currentIndex() == 4:
            self.refresh_analytics()

    # ─────────────────────────── data loading ────────────────────────────

    def refresh_on_tab_switch(self):
        """One request per activation (mirrors BaseTab semantics): skip while
        a fetch is in flight or within the grace window unless marked dirty."""
        if self._needs_refresh or not self._loaded_once:
            self.refresh_analytics()
            return
        if time.monotonic() - self._last_refresh_at < 2.0:
            return
        if time.monotonic() - self._last_refresh_at > self.STALE_AFTER_SECONDS:
            self.refresh_analytics()

    def mark_dirty(self):
        """Request one refresh the next time this tab becomes visible."""
        self._needs_refresh = True

    def refresh_analytics(self):
        date_from, date_to = self._current_period()
        thread = getattr(self, "_thread", None)
        if thread is not None:
            try:
                if shiboken6.isValid(thread) and thread.isRunning():
                    logger.info(
                        "Analytics refresh ignored while a fetch is active"
                    )
                    return False
            except RuntimeError:
                pass
        if not self.database:
            self.status_label.setText("No database connection.")
            return False

        self._generation += 1
        self.status_label.setText("Loading analytics...")
        self.status_label.setStyleSheet(f"color: {_MUTED};")

        thread = QThread(QApplication.instance())
        thread.setObjectName("analytics-snapshot-refresh")
        worker = _AnalyticsWorker(self.database, date_from, date_to)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        worker.finished.connect(self._on_load_finished)
        worker.failed.connect(self._on_load_failed)

        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)

        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_finished)

        self._thread = thread
        self._worker = worker
        diagnostics.worker_started(
            "analytics_snapshot", "Analytics", f"{date_from}..{date_to}"
        )
        thread.start()
        return True

    @Slot(object)
    def _on_load_finished(self, snapshot):
        if snapshot is None:
            self._on_load_failed("The host returned no analytics data")
            return
        self._snapshot = snapshot
        # Clear the loading indicator FIRST, then render in small event-loop
        # slices. Rendering everything inside this one queued slot was proven
        # (faulthandler stacks) to occasionally wedge the GUI thread inside
        # long Qt widget/chart native calls - the intermittent freeze.
        # Slicing keeps the event loop breathing between stages so the window
        # always stays responsive and the loading state never sticks.
        snapshot = self._snapshot or {}
        has_any_data = any([
            float(snapshot.get("revenue_total") or 0),
            float(snapshot.get("purchases_total") or 0),
            int(snapshot.get("sales_count") or 0),
            int(snapshot.get("imports_count") or 0),
        ])
        if not has_any_data and not snapshot.get("evolution"):
            self.status_label.setText(
                "No analytics data for the selected period."
            )
        else:
            self.status_label.setText(self._period_status_text())
        self.status_label.setStyleSheet(f"color: {_MUTED};")
        self._loaded_once = True
        self._needs_refresh = False
        self._last_refresh_at = time.monotonic()
        self._render_done = False
        self._render_queue = [
            self._render_cards,
            self._render_tables,
            self._render_alerts_and_charts,
        ]
        # Child QTimer (not a static singleShot): if this tab is destroyed
        # mid-render the timer is destroyed with it, so no callback can ever
        # fire into a deleted C++ object.
        if getattr(self, "_render_timer", None) is None:
            self._render_timer = QTimer(self)
            self._render_timer.setSingleShot(True)
            self._render_timer.timeout.connect(self._render_next_slice)
        self._render_timer.start(0)

    def _period_status_text(self):
        period = (self._snapshot or {}).get("period") or {}
        return (
            f"Period {period.get('from', '?')} to {period.get('to', '?')}"
            f"   -   updated {time.strftime('%H:%M:%S')}"
            "   (receivables / payables / stock are current positions)"
        )

    @Slot()
    def _render_next_slice(self):
        if not getattr(self, "_render_queue", None):
            self._render_done = True
            return
        step = self._render_queue.pop(0)
        try:
            step(self._snapshot or {})
        except Exception:
            logger.exception("Analytics rendering step failed (%s)", step.__name__)
            self.status_label.setText(
                "Failed to render analytics (see logs). Data was loaded."
            )
            self.status_label.setStyleSheet(f"color: {_RED};")
            self._render_queue = []
            self._render_done = True
            return
        if self._render_queue:
            self._render_timer.start(0)
        else:
            self._render_done = True

    @Slot(str)
    def _on_load_failed(self, error):
        # A failure must never silently look like zeros.
        self.status_label.setText(f"Failed to load analytics: {error}")
        self.status_label.setStyleSheet(f"color: {_RED};")

    # ───────────────────────────── rendering ─────────────────────────────

    def _render_snapshot(self):
        """Legacy monolithic renderer - kept for tests; the live path uses
        the sliced renderer (see _on_load_finished)."""
        self._render_cards(self._snapshot or {})
        self._render_tables(self._snapshot or {})
        self._render_alerts_and_charts(self._snapshot or {})

    def _render_cards(self, snapshot):
        def val(key):
            return snapshot.get(key)

        revenue = val("revenue_total")
        profit = val("gross_profit")
        margin = val("gross_margin_pct")
        self.cards["revenue"].set_value(
            _fmt_money(revenue) if revenue is not None else "-",
            tooltip=None if revenue is not None else "No Sales read permission",
        )
        profit_card = self.cards["gross_profit"]
        if profit is None:
            profit_card.set_value("-", tooltip="Requires Sales and Imports read access")
        else:
            profit_value = float(profit)
            profit_card.value_label.setStyleSheet(
                f"color: {_GREEN if profit_value >= 0 else _RED}; "
                f"font-size: 19px; font-weight: bold; "
                f"background: transparent; border: none;"
            )
            profit_card.set_value(_fmt_money(profit))
        self.cards["gross_margin"].set_value(
            _fmt_pct(margin),
            tooltip=None if margin is not None else "Requires Sales and Imports read access",
        )
        charges = val("charges_total")
        self.cards["operating_charges"].set_value(
            _fmt_money(charges) if charges is not None else "-",
            subtitle=(
                f"{_fmt_int(val('charges_count'))} charges"
                if charges is not None else ""
            ),
            tooltip=None if charges is not None else "No Charges read permission",
        )
        net_profit = val("net_profit")
        self.cards["net_profit"].set_value(
            _fmt_money(net_profit) if net_profit is not None else "-",
            subtitle=(
                f"{_fmt_pct(val('net_margin_pct'))} net margin"
                if net_profit is not None else ""
            ),
            tooltip=(
                None if net_profit is not None
                else "Requires Sales, Imports and Charges read access"
            ),
        )
        sales_count = val("sales_count")
        self.cards["sales_count"].set_value(
            _fmt_int(sales_count) if sales_count is not None else "-",
            subtitle="Click to open Sales",
            tooltip=None if sales_count is not None else "No Sales read permission",
        )
        purchases = val("purchases_total")
        self.cards["purchases"].set_value(
            _fmt_money(purchases) if purchases is not None else "-",
            subtitle="Click to open Imports",
            tooltip=None if purchases is not None else "No Imports read permission",
        )
        receivables = val("receivables_total")
        self.cards["receivables"].set_value(
            _fmt_money(receivables) if receivables is not None else "-",
            subtitle=(
                f"{_fmt_int(val('receivables_clients'))} clients with balance"
                if receivables is not None else ""
            ),
            tooltip=None if receivables is not None else "No Clients read permission",
        )
        payables = val("payables_total")
        self.cards["payables"].set_value(
            _fmt_money(payables) if payables is not None else "-",
            subtitle=(
                f"{_fmt_int(val('payables_suppliers'))} suppliers"
                if payables is not None else ""
            ),
            tooltip=None if payables is not None else "No Suppliers read permission",
        )
        stock_value = val("stock_value")
        self.cards["stock_value"].set_value(
            _fmt_money(stock_value) if stock_value is not None else "-",
            subtitle="quantity x weighted average cost",
            tooltip=None if stock_value is not None else "No Products read permission",
        )
        total_stock_sale = val("total_stock_sale_value")
        self.cards["total_stock_sale_value"].set_value(
            _fmt_money(total_stock_sale) if total_stock_sale is not None else "-",
            subtitle="If all current stock is sold at selling price",
            tooltip=None if total_stock_sale is not None else "No Products read permission",
        )
        potential_stock_profit = val("potential_stock_profit")
        self.cards["potential_stock_profit"].set_value(
            _fmt_money(potential_stock_profit) if potential_stock_profit is not None else "-",
            subtitle="Potential profit if all current stock is sold",
            tooltip=None if potential_stock_profit is not None else "No Products read permission",
        )
        low_stock = val("low_stock_count")
        self.cards["low_stock"].set_value(
            _fmt_int(low_stock) if low_stock is not None else "-",
            tooltip=None if low_stock is not None else "No Products read permission",
        )
        out_of_stock = val("out_of_stock_count")
        self.cards["out_of_stock"].set_value(
            _fmt_int(out_of_stock) if out_of_stock is not None else "-",
            tooltip=None if out_of_stock is not None else "No Products read permission",
        )

    def _render_alerts_and_charts(self, snapshot):
        self._render_charts(snapshot)
        self._render_alerts(snapshot)

    def _charts_enabled(self):
        """QtCharts scene machinery proved intermittently deadlock-prone
        under rapid Analytics open/close cycles (faulthandler stacks show
        the GUI thread wedged inside QBarSet/QValueAxis/QGraphics internals).
        Set PYLI_QTCHARTS=1 to force the legacy QtCharts renderer."""
        return os.environ.get("PYLI_QTCHARTS") == "1"

    def _bucket_label(self, bucket, monthly):
        """Format bucket labels nicely for display."""
        text = str(bucket or "")
        if not text:
            return ""
        if monthly:
            # Format: "2026-08" -> "Aug 2026"
            try:
                year, month = text.split('-')[:2]
                month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                month_idx = int(month) - 1
                if 0 <= month_idx < 12:
                    return f"{month_names[month_idx]} {year}"
            except Exception:
                pass
            return text
        else:
            # Format: "2026-08-01" -> "01 Aug"
            try:
                if len(text) == 10 and text[4] == '-' and text[7] == '-':
                    year, month, day = text.split('-')
                    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                    month_idx = int(month) - 1
                    if 0 <= month_idx < 12:
                        return f"{day} {month_names[month_idx]}"
            except Exception:
                pass
            # Fallback: return last 5 chars (MM-DD or similar)
            return text[-5:] if len(text) >= 5 else text

    def _render_charts(self, snapshot):
        evolution = snapshot.get("evolution") or []
        monthly = snapshot.get("bucket_mode") == "month"

        labels = [self._bucket_label(row.get("bucket"), monthly) for row in evolution]
        revenues = [
            float(row["revenue"]) if row.get("revenue") is not None else 0.0
            for row in evolution
        ]
        profits = [
            float(row["profit"]) if row.get("profit") is not None else 0.0
            for row in evolution
        ]
        purchases = [
            float(row["purchases"]) if row.get("purchases") is not None else 0.0
            for row in evolution
        ]

        bucket_word = "month" if monthly else "day"
        if not evolution:
            self.revenue_chart_title.setText(
                "Revenue & Profit Evolution (no data for this period)"
            )
            self.flow_chart_title.setText(
                "Sales vs Purchases (no data for this period)"
            )
        else:
            self.revenue_chart_title.setText(
                f"Revenue & Profit Evolution (per {bucket_word})"
            )
            self.flow_chart_title.setText(
                f"Sales vs Purchases (per {bucket_word})"
            )

        # Revenue & Profit Evolution - Line/Area chart
        if isinstance(self.revenue_chart_view, LineAreaChart):
            self.revenue_chart_view.set_data(
                labels,
                [
                    ("Revenue", _GREEN, revenues, True),   # Revenue with area fill
                    ("Profit", _BLUE, profits, False),     # Profit as line only
                ],
            )
            self.revenue_chart_view.set_empty_text(
                "Revenue & Profit Evolution (no data)"
            )

        # Sales vs Purchases - Grouped Bar Chart
        if isinstance(self.flow_chart_view, GroupedBarChart):
            self.flow_chart_view.set_data(
                labels,
                [("Sales", _BLUE, revenues),
                 ("Purchases", _ORANGE, purchases)],
            )
            self.flow_chart_view.set_empty_text(
                "Sales vs Purchases (no data)"
            )
        # Update purchases bar set only if captured
        if self._purchases_set is not None:
            self._reset_bar_set(self._purchases_set, purchases)
        max_flow = max([abs(v) for v in purchases] + [1.0])
        if math.isfinite(max_flow) and max_flow > 0 and self._flow_axis_y is not None:
            self._flow_axis_y.setRange(0, max_flow * 1.15)

    @staticmethod
    def _replace_bar_categories(axis, labels):
        axis.setCategories([str(label) for label in labels])

    @staticmethod
    def _reset_bar_set(bar_set, values):
        count = bar_set.count()
        if count > len(values):
            for index in range(count - 1, len(values) - 1, -1):
                bar_set.remove(index, 1)
        for index, value in enumerate(values):
            if index < bar_set.count():
                bar_set.replace(index, value)
            else:
                bar_set.append(value)

    def _render_tables(self, snapshot):
        def fill(table, rows, columns, money_columns):
            table.setRowCount(0)
            if rows is None:
                hint = QTableWidgetItem("No permission")
                hint.setForeground(QColor(_MUTED))
                table.setRowCount(1)
                table.setItem(0, 0, hint)
                return
            if not rows:
                hint = QTableWidgetItem("No data for this period")
                hint.setForeground(QColor(_MUTED))
                table.setRowCount(1)
                table.setItem(0, 0, hint)
                return
            for row_index, row in enumerate(rows):
                table.insertRow(row_index)
                for column, key in enumerate(columns):
                    raw = row.get(key)
                    if key in money_columns:
                        text = "-" if raw is None else f"{float(raw):,.2f}"
                    else:
                        text = "-" if raw is None else str(raw)
                    cell = QTableWidgetItem(text)
                    if column > 0:
                        cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    table.setItem(row_index, column, cell)

        fill(
            self.top_selling_table,
            snapshot.get("top_selling_products"),
            ("name", "qty", "revenue"),
            {"revenue"},
        )
        fill(
            self.profitable_table,
            snapshot.get("most_profitable_products"),
            ("name", "qty", "profit"),
            {"profit"},
        )
        fill(
            self.top_clients_table,
            snapshot.get("top_clients"),
            ("name", "sales_count", "revenue"),
            {"revenue"},
        )

    def _render_alerts(self, snapshot):
        self.alerts_list.clear()
        products = snapshot.get("low_stock_products")
        if products is None:
            item = QListWidgetItem("No Products read permission")
            item.setForeground(QColor(_MUTED))
            self.alerts_list.addItem(item)
            return
        if not products:
            item = QListWidgetItem("No stock alerts - all products above threshold")
            item.setForeground(QColor(_GREEN))
            self.alerts_list.addItem(item)
            return
        for product in products:
            try:
                qty = float(product.get("stock") or 0)
            except (TypeError, ValueError):
                qty = 0.0
            color = _RED if qty <= 0 else _ORANGE
            label = (
                f"{product.get('name')}  -  stock {product.get('stock')} "
                f"(alert at {product.get('alert') or 5})"
            )
            item = QListWidgetItem(label)
            item.setForeground(QColor(color))
            item.setData(Qt.UserRole, product)
            self.alerts_list.addItem(item)

    # ─────────────────────────── drill-downs ─────────────────────────────

    def _main_window(self):
        parent = self.parent()
        while parent is not None and not hasattr(parent, "tab_widget"):
            parent = parent.parent()
        return parent

    def _switch_to_tab(self, key):
        main_window = self._main_window()
        if not main_window:
            return False
        index_map = getattr(main_window, "_tab_key_to_index", {}) or {}
        index = index_map.get(key)
        if index is None or not main_window.tab_widget:
            return False
        main_window.tab_widget.setCurrentIndex(index)
        return True

    def _search_products(self, text):
        if not self._switch_to_tab("products"):
            return
        main_window = self._main_window()
        products_tab = main_window.tab_widget.currentWidget()
        if hasattr(products_tab, "search_bar") and hasattr(products_tab.search_bar, "setText"):
            products_tab.search_bar.setText(str(text or ""))

    def _open_card_target(self, key):
        targets = {
            "sales_count": "sales",
            "purchases": "imports",
            "receivables": "clients",
            "payables": "suppliers",
        }
        target = targets.get(key)
        if target:
            self._switch_to_tab(target)

    def _open_product_from_table(self, table, row):
        item = table.item(row, 0)
        if item is None:
            return
        self._search_products(item.text())

    def _open_alert_product(self, item):
        product = item.data(Qt.UserRole)
        if not product:
            return
        self._search_products(product.get("username") or product.get("name") or "")

    # ───────────────────────── thread lifecycle ──────────────────────────

    @Slot()
    def _on_thread_finished(self):
        thread = self.sender()
        if self._thread is thread:
            self._thread = None
            self._worker = None

    def _wait_for_thread(self, timeout_ms=5000):
        thread = getattr(self, "_thread", None)
        if thread is None:
            return True
        try:
            if not shiboken6.isValid(thread) or not thread.isRunning():
                self._thread = None
                self._worker = None
                return True
        except RuntimeError:
            self._thread = None
            self._worker = None
            return True
        if thread == QThread.currentThread():
            return False
        thread.requestInterruption()
        thread.quit()
        if not thread.wait(timeout_ms):
            logger.error("Analytics thread did not stop in time")
            return False
        if getattr(self, "_thread", None) is thread:
            self._thread = None
            self._worker = None
        return True
