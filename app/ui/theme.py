# -*- coding: utf-8 -*-
"""界面配色、样式表与运行时生成的小图标。"""
import os
import tempfile

BG = "#F4F6FA"
CARD = "#FFFFFF"
BORDER = "#E2E8F0"
TEXT = "#1E293B"
MUTED = "#64748B"
ACCENT = "#2563EB"
ACCENT_DARK = "#1D4ED8"
OK = "#15803D"
WARN = "#B45309"
ERR = "#B91C1C"


def _asset_dir() -> str:
    d = os.path.join(tempfile.gettempdir(), "daplink_flasher_assets")
    os.makedirs(d, exist_ok=True)
    return d


def ensure_check_icon() -> str:
    """生成复选框的对勾图标：QSS 的 indicator 只能靠图片，不能用字符。"""
    path = os.path.join(_asset_dir(), "check.png")
    if os.path.exists(path):
        return path
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

    pm = QPixmap(28, 28)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor("#FFFFFF"))
    pen.setWidth(4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawPolyline([QPointF(7, 14.5), QPointF(12, 19.5), QPointF(21, 8.5)])
    p.end()
    pm.save(path, "PNG")
    return path


def ensure_chevron_icon() -> str:
    """下拉框箭头。自定义 QSS 后 Qt 不再画默认箭头，只能自己给图片。"""
    path = os.path.join(_asset_dir(), "chevron.png")
    if os.path.exists(path):
        return path
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

    pm = QPixmap(20, 20)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor("#64748B"))
    pen.setWidth(2)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawPolyline([QPointF(5, 8), QPointF(10, 13), QPointF(15, 8)])
    p.end()
    pm.save(path, "PNG")
    return path


def app_icon():
    """窗口/任务栏图标：蓝底圆角 + 向下箭头。"""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(ACCENT))
    p.drawRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
    pen = QPen(QColor("#FFFFFF"))
    pen.setWidth(6)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawLine(QPointF(32, 14), QPointF(32, 40))
    p.drawPolyline([QPointF(22, 31), QPointF(32, 41), QPointF(42, 31)])
    p.drawLine(QPointF(19, 50), QPointF(45, 50))
    p.end()
    return QIcon(pm)


def build_qss() -> str:
    check = ensure_check_icon().replace("\\", "/")
    chevron = ensure_chevron_icon().replace("\\", "/")
    return f"""
* {{
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI";
    font-size: 13px;
    color: {TEXT};
}}
QWidget#root {{ background: {BG}; }}

QFrame#card {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QLabel#title {{ font-size: 17px; font-weight: 600; }}
QLabel#subtitle {{ color: {MUTED}; font-size: 12px; }}
QLabel#section {{ font-weight: 600; color: {TEXT}; }}
QLabel#hint {{ color: {MUTED}; font-size: 12px; }}
QLabel#status {{ color: {MUTED}; }}
QLabel#pct {{ color: {ACCENT}; font-weight: 600; }}

QComboBox, QLineEdit {{
    background: #FFFFFF;
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    min-height: 22px;
    selection-background-color: {ACCENT};
}}
QComboBox:hover, QLineEdit:hover {{ border-color: #C4CFDE; }}
QComboBox:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url("{chevron}"); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{
    background: #FFFFFF;
    border: 1px solid {BORDER};
    selection-background-color: #E8F0FF;
    selection-color: {TEXT};
    outline: none;
}}

QPushButton {{
    background: #FFFFFF;
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
    min-height: 22px;
}}
QPushButton:hover {{ background: #F1F5FB; border-color: #C4CFDE; }}
QPushButton:pressed {{ background: #E8EEF8; }}
QPushButton:disabled {{ color: #A8B3C2; background: #F7F9FC; border-color: #EDF1F7; }}

QPushButton#primary {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: #FFFFFF;
    font-weight: 600;
    padding: 8px 26px;
}}
QPushButton#primary:hover {{ background: {ACCENT_DARK}; border-color: {ACCENT_DARK}; }}
QPushButton#primary:disabled {{ background: #AFC5EE; border-color: #AFC5EE; color: #FFFFFF; }}

QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid #C4CFDE; border-radius: 3px; background: #FFFFFF;
}}
QCheckBox::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT};
    image: url("{check}");
}}
QCheckBox::indicator:checked:hover {{ background: {ACCENT_DARK}; }}

QProgressBar {{
    background: #DCE5F2;
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}

QTextEdit#log {{
    background: #FFFFFF;
    border: 1px solid {BORDER};
    border-radius: 8px;
    font-family: "Cascadia Mono", "Consolas", "Courier New";
    font-size: 12px;
    padding: 6px;
}}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #CFD8E5; border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #B6C2D4; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""
