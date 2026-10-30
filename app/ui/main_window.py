# -*- coding: utf-8 -*-
"""主窗口。"""
import os
import time

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QTextCursor, QTextCharFormat, QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton, QSizePolicy,
    QTextEdit, QVBoxLayout, QWidget,
)

from ..core import firmware as fwmod
from ..core.chips import ChipLibrary
from ..core.worker import CANCEL_TEXT, Programmer
from . import theme

APP_TITLE = "DAPLink 下载工具"
APP_VERSION = "1.0.0"

LOG_COLORS = {
    "info": theme.TEXT,
    "ok": theme.OK,
    "warn": theme.WARN,
    "error": theme.ERR,
}


def _prefer(combo: QComboBox, names) -> None:
    """下拉框优先落在常用型号上，省得每次都手动翻。"""
    for n in names:
        idx = combo.findText(n)
        if idx >= 0:
            combo.setCurrentIndex(idx)
            return


class MainWindow(QMainWindow):
    sig_connect = Signal(str, object, int)
    sig_disconnect = Signal()
    sig_flash = Signal(dict)
    sig_cancel = Signal()

    def __init__(self, lib: ChipLibrary):
        super().__init__()
        self._lib = lib
        self._connected = False
        self._busy = False
        self._flashing = False
        self._chip = None
        self._connected_part = ""

        self.setWindowTitle("%s %s" % (APP_TITLE, APP_VERSION))
        self.resize(980, 720)
        self.setMinimumSize(880, 640)
        self.setWindowIcon(theme.app_icon())

        self._build_ui()
        self._start_worker()
        self._refresh_probes()
        self._reload_series()
        self._update_ready()

    # ------------------------------------------------------------------ 构建
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(12)

        # 标题
        title_row = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        lbl_title = QLabel(APP_TITLE)
        lbl_title.setObjectName("title")
        lbl_sub = QLabel("CMSIS-DAP 探针 · STM32 / HC32 / CH32 程序下载")
        lbl_sub.setObjectName("subtitle")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_sub)
        title_row.addLayout(title_box)
        title_row.addStretch(1)
        outer.addLayout(title_row)

        outer.addWidget(self._build_probe_card())
        outer.addWidget(self._build_chip_card())
        outer.addWidget(self._build_file_card())
        outer.addLayout(self._build_action_row())
        outer.addWidget(self._build_log_card(), 1)

        self.statusBar().showMessage(
            "型号库 %d 个 · pyOCD 0.46 · 就绪" % len(self._lib.chips))

    def _card(self, title: str) -> tuple:
        card = QFrame()
        card.setObjectName("card")
        box = QVBoxLayout(card)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(8)
        if title:
            lbl = QLabel(title)
            lbl.setObjectName("section")
            box.addWidget(lbl)
        return card, box

    def _build_probe_card(self) -> QFrame:
        card, box = self._card("调试探针")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.probe_combo = QComboBox()
        self.probe_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.probe_combo.setMinimumWidth(320)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setFixedWidth(64)
        self.btn_connect = QPushButton("连接")
        self.btn_connect.setFixedWidth(88)
        self.lbl_probe_state = QLabel("未连接")
        self.lbl_probe_state.setObjectName("hint")

        self.btn_refresh.clicked.connect(self._refresh_probes)
        self.btn_connect.clicked.connect(self._toggle_connect)

        # 下载速度：SWD 时钟，单位 kHz；可下拉也可手填
        self.speed_combo = QComboBox()
        self.speed_combo.setEditable(True)
        self.speed_combo.setFixedWidth(92)
        for khz in ("100", "500", "1000", "2000", "4000", "8000", "10000"):
            self.speed_combo.addItem(khz)
        self.speed_combo.setCurrentText("1000")
        self.speed_combo.setToolTip("SWD 时钟频率，上限 10000 kHz。信号差/杜邦线长时降到 100~500；"
                                    "超过 1 MHz 实际速率基本不再提升（受探针 HID 传输限制）")
        self.speed_combo.lineEdit().setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.speed_combo.currentTextChanged.connect(lambda _: self._update_ready())

        row.addWidget(QLabel("探针"))
        row.addWidget(self.probe_combo, 1)
        row.addSpacing(6)
        row.addWidget(QLabel("速度"))
        row.addWidget(self.speed_combo)
        row.addWidget(QLabel("kHz"))
        row.addSpacing(6)
        row.addWidget(self.btn_refresh)
        row.addWidget(self.btn_connect)
        row.addWidget(self.lbl_probe_state)
        box.addLayout(row)
        return card

    def _build_chip_card(self) -> QFrame:
        card, box = self._card("目标芯片")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        self.vendor_combo = QComboBox()
        self.series_combo = QComboBox()
        self.part_combo = QComboBox()
        for cb in (self.vendor_combo, self.series_combo, self.part_combo):
            cb.setMinimumWidth(190)

        self.vendor_combo.currentIndexChanged.connect(self._reload_series)
        self.series_combo.currentIndexChanged.connect(self._reload_parts)
        self.part_combo.currentIndexChanged.connect(self._on_part_changed)
        # 构建期间先屏蔽信号，等文件卡（base_edit）建好后再统一刷新
        self.vendor_combo.blockSignals(True)

        grid.addWidget(QLabel("厂商"), 0, 0)
        grid.addWidget(self.vendor_combo, 0, 1)
        grid.addWidget(QLabel("系列"), 0, 2)
        grid.addWidget(self.series_combo, 0, 3)
        grid.addWidget(QLabel("型号"), 0, 4)
        grid.addWidget(self.part_combo, 0, 5)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        grid.setColumnStretch(5, 1)

        self.lbl_capacity = QLabel("—")
        self.lbl_capacity.setObjectName("hint")
        self.lbl_base = QLabel("Flash 起始地址 —")
        self.lbl_base.setObjectName("hint")
        grid.addWidget(self.lbl_capacity, 1, 1, 1, 3)
        grid.addWidget(self.lbl_base, 1, 4, 1, 2)
        box.addLayout(grid)

        for v in self._lib.vendors():
            self.vendor_combo.addItem(v)
        self.vendor_combo.blockSignals(False)
        return card

    def _build_file_card(self) -> QFrame:
        card, box = self._card("固件与选项")
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("选择要下载的固件（.hex / .bin / .elf / .axf）")
        self.file_edit.textChanged.connect(self._update_ready)
        self.btn_browse = QPushButton("浏览")
        self.btn_browse.setFixedWidth(64)
        self.btn_browse.clicked.connect(self._browse_file)
        row1.addWidget(QLabel("固件"))
        row1.addWidget(self.file_edit, 1)
        row1.addWidget(self.btn_browse)
        box.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.base_edit = QLineEdit("0x08000000")
        self.base_edit.setFixedWidth(120)
        self.base_edit.setToolTip("BIN 文件没有地址信息，按这里填的地址写入；HEX/ELF 用文件内地址")
        lbl_base_hint = QLabel("BIN 起始地址")
        lbl_base_hint.setObjectName("hint")

        self.chk_erase = QCheckBox("全片擦除")
        self.chk_verify = QCheckBox("回读校验")
        self.chk_verify.setChecked(True)
        self.chk_reset = QCheckBox("下载后复位运行")
        self.chk_reset.setChecked(True)

        row2.addWidget(lbl_base_hint)
        row2.addWidget(self.base_edit)
        row2.addSpacing(18)
        row2.addWidget(self.chk_erase)
        row2.addWidget(self.chk_verify)
        row2.addWidget(self.chk_reset)
        row2.addStretch(1)
        box.addLayout(row2)
        return card

    def _build_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        self.btn_flash = QPushButton("开始下载")
        self.btn_flash.setObjectName("primary")
        self.btn_flash.setMinimumWidth(140)
        self.btn_flash.clicked.connect(self._start_flash)

        self.btn_cancel = QPushButton("中止")
        self.btn_cancel.setFixedWidth(64)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._request_cancel)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.lbl_state = QLabel("就绪")
        self.lbl_state.setObjectName("status")
        self.lbl_state.setMinimumWidth(150)
        self.lbl_pct = QLabel("0%")
        self.lbl_pct.setObjectName("pct")
        self.lbl_pct.setFixedWidth(40)
        self.lbl_pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        row.addWidget(self.btn_flash)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.progress, 1)
        row.addWidget(self.lbl_pct)
        row.addWidget(self.lbl_state)
        return row

    def _build_log_card(self) -> QFrame:
        card, box = self._card(None)
        head = QHBoxLayout()
        lbl = QLabel("日志")
        lbl.setObjectName("section")
        btn_clear = QPushButton("清空")
        btn_clear.setFixedWidth(64)
        btn_clear.clicked.connect(lambda: self.log_view.clear())
        btn_save = QPushButton("保存")
        btn_save.setFixedWidth(64)
        btn_save.clicked.connect(self._save_log)
        head.addWidget(lbl)
        head.addStretch(1)
        head.addWidget(btn_clear)
        head.addWidget(btn_save)
        box.addLayout(head)

        self.log_view = QTextEdit()
        self.log_view.setObjectName("log")
        self.log_view.setReadOnly(True)
        self.log_view.document().setMaximumBlockCount(4000)
        box.addWidget(self.log_view, 1)
        return card

    # ------------------------------------------------------------------ 线程
    def _start_worker(self) -> None:
        self._thread = QThread(self)
        self._worker = Programmer(self._lib)
        self._worker.moveToThread(self._thread)
        self.sig_connect.connect(self._worker.connect_probe)
        self.sig_disconnect.connect(self._worker.disconnect_probe)
        self.sig_flash.connect(self._worker.flash)
        # 中止必须直连：worker 线程正阻塞在 flash() 里，走队列的信号只有等
        # flash() 返回才会被处理，中点止要等全部写完才生效。
        self.sig_cancel.connect(self._worker.request_cancel, Qt.ConnectionType.DirectConnection)
        self._worker.log.connect(self._append_log)
        self._worker.progress.connect(self._on_progress)
        self._worker.state.connect(self.lbl_state.setText)
        self._worker.connected.connect(self._on_connected)
        self._worker.finished.connect(self._on_finished)
        self._worker.speed_changed.connect(self._on_speed_changed)
        self._thread.start()

    # ------------------------------------------------------------------ 探针
    def _refresh_probes(self) -> None:
        from pyocd.probe.aggregator import DebugProbeAggregator

        current = self.probe_combo.currentData()
        self.probe_combo.clear()
        try:
            probes = DebugProbeAggregator.get_all_connected_probes()
        except Exception as e:
            self._append_log("error", "枚举探针失败：%s" % e)
            probes = []
        for p in probes:
            name = p.product_name or "CMSIS-DAP"
            self.probe_combo.addItem("%s  (%s)" % (name, p.unique_id), p.unique_id)
        if current:
            idx = self.probe_combo.findData(current)
            if idx >= 0:
                self.probe_combo.setCurrentIndex(idx)
        if probes:
            self._append_log("info", "找到 %d 个探针" % len(probes))
        else:
            self._append_log("warn", "未检测到 CMSIS-DAP 探针，请确认已插入并被识别")
        self._update_ready()

    def _toggle_connect(self) -> None:
        if self._connected:
            self.sig_disconnect.emit()
            return
        chip = self._chip
        uid = self.probe_combo.currentData()
        if chip is None or not uid:
            return
        self._set_busy(True)
        self.sig_connect.emit(uid, chip, self._frequency())

    # ------------------------------------------------------------------ 芯片
    def _reload_series(self) -> None:
        vendor = self.vendor_combo.currentText()
        self.series_combo.blockSignals(True)
        self.series_combo.clear()
        for s in self._lib.series(vendor):
            self.series_combo.addItem(s)
        self.series_combo.blockSignals(False)
        _prefer(self.series_combo, ("STM32F103", "STM32F407", "HC32F460", "HC32F4A0", "CH32F203"))
        self._reload_parts()

    def _reload_parts(self) -> None:
        vendor = self.vendor_combo.currentText()
        series = self.series_combo.currentText()
        self.part_combo.blockSignals(True)
        self.part_combo.clear()
        for c in self._lib.parts(vendor, series):
            self.part_combo.addItem(c.part, c.part)
        self.part_combo.blockSignals(False)
        _prefer(self.part_combo, ("STM32F103C8", "STM32F407ZG", "HC32F460PETB",
                                  "HC32F4A0SGTB", "CH32F203C8"))
        self._on_part_changed()

    def _on_part_changed(self) -> None:
        vendor = self.vendor_combo.currentText()
        series = self.series_combo.currentText()
        part = self.part_combo.currentText()
        self._chip = self._lib.find(vendor, series, part)
        if self._chip:
            self.lbl_capacity.setText(self._chip.capacity_text)
            self.lbl_base.setText("Flash 起始地址 %s" % self._chip.base_text)
            self.base_edit.setText(self._chip.base_text)
        else:
            self.lbl_capacity.setText("—")
            self.lbl_base.setText("Flash 起始地址 —")
        # 换了芯片型号，之前建立的连接（目标类型不同）必须作废
        if self._connected and self._chip and self._connected_part != self._chip.part:
            self.sig_disconnect.emit()
        self._inspect_file()
        self._update_ready()

    # ------------------------------------------------------------------ 文件
    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择固件", "",
            "固件文件 (*.hex *.bin *.elf *.axf);;所有文件 (*.*)")
        if path:
            self.file_edit.setText(path)
            self._append_log("info", "已选择 %s" % path)
            self._inspect_file()

    def _inspect_file(self) -> None:
        """选中文件后先解析一遍，把大小和地址范围摆到日志里，出错早发现。"""
        path = self.file_edit.text().strip()
        if not path or not os.path.isfile(path):
            return
        chip = self._chip
        base = self._base_address() if chip is None else chip.flash_base
        try:
            fw = fwmod.load(path, base)
        except Exception as e:
            self._append_log("error", "固件解析失败：%s" % e)
            return
        self._append_log("info", "  %s，%d 段，共 %d 字节，地址 %s"
                         % (fw.file_type, len(fw.segments), fw.total_size, fw.span_text))
        if chip is not None:
            ok, msg = fwmod.check_range(fw, chip.flash_base, chip.flash_size)
            if not ok:
                self._append_log("warn", "  " + msg)

    def _frequency(self) -> int:
        """界面上的 kHz 数值转成 Hz，非法输入回落到 1 MHz。"""
        text = self.speed_combo.currentText().strip().replace("_", "").replace(",", "")
        try:
            khz = float(text)
        except ValueError:
            khz = 1000.0
        return max(10_000, min(10_000_000, int(khz * 1000)))

    def _base_address(self) -> int:
        text = self.base_edit.text().strip().replace("_", "")
        try:
            return int(text, 0)
        except ValueError:
            return self._chip.flash_base if self._chip else 0

    # ------------------------------------------------------------------ 烧录
    def _start_flash(self) -> None:
        path = self.file_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "提示", "请先选择固件文件")
            return
        if not os.path.isfile(path):
            QMessageBox.warning(self, "提示", "文件不存在：\n%s" % path)
            return
        chip = self._chip
        if chip is None:
            QMessageBox.warning(self, "提示", "请选择目标芯片型号")
            return
        uid = self.probe_combo.currentData()
        if not uid:
            QMessageBox.warning(self, "提示", "未检测到调试探针")
            return

        params = {
            "path": path,
            "chip": chip,
            "base": self._base_address(),
            "verify": self.chk_verify.isChecked(),
            "chip_erase": self.chk_erase.isChecked(),
            "reset": self.chk_reset.isChecked(),
            "frequency": self._frequency(),
            "probe_uid": uid,
        }
        self._append_log("info", "—— 开始下载 %s → %s ——" % (os.path.basename(path), chip.part))
        self._flashing = True
        self._set_busy(True, cancellable=True)
        self.progress.setValue(0)
        self.lbl_pct.setText("0%")
        self.sig_flash.emit(params)

    def _request_cancel(self) -> None:
        """点中止：先把按钮锁死给出反馈，再通知后台停。"""
        self.btn_cancel.setEnabled(False)
        self.lbl_state.setText("正在中止…")
        self.sig_cancel.emit()

    def _on_speed_changed(self, hz: int) -> None:
        """自动降速后，把上面的速度框同步成实际在用的值。"""
        khz = max(1, int(round(hz / 1000.0)))
        if self.speed_combo.currentText().strip() != str(khz):
            self.speed_combo.setCurrentText(str(khz))

    def _on_progress(self, value: int) -> None:
        self.progress.setValue(max(0, min(100, value)))
        self.lbl_pct.setText("%d%%" % max(0, min(100, value)))

    def _on_connected(self, ok: bool, name: str) -> None:
        self._connected = ok
        self.btn_connect.setText("断开" if ok else "连接")
        self.lbl_probe_state.setText("已连接 %s" % name if ok else "未连接")
        self._connected_part = name if ok else ""
        # 烧录流程里也会触发连接，此时不要解除忙碌状态
        if not self._flashing:
            self._set_busy(False)
        self._update_ready()

    def _on_finished(self, ok: bool, msg: str) -> None:
        self._flashing = False
        self._set_busy(False)
        self._update_ready()
        if ok:
            self.statusBar().showMessage("下载成功 · %s" % msg, 8000)
        elif msg == CANCEL_TEXT:
            # 中止不是故障，别用红色失败文案吓人
            self.statusBar().showMessage("已中止 · 连接已断开，点开始下载会自动重连", 8000)
        else:
            self.statusBar().showMessage("下载失败 · %s" % msg, 8000)

    def _set_busy(self, busy: bool, cancellable: bool = False) -> None:
        self._busy = busy
        for w in (self.btn_flash, self.btn_browse, self.btn_refresh,
                  self.vendor_combo, self.series_combo, self.part_combo,
                  self.chk_erase, self.chk_verify, self.chk_reset,
                  self.base_edit, self.file_edit, self.speed_combo):
            w.setEnabled(not busy)
        self.btn_connect.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy and cancellable)
        if not busy:
            self._update_ready()

    def _update_ready(self) -> None:
        has_probe = self.probe_combo.count() > 0
        has_file = bool(self.file_edit.text().strip())
        self.btn_flash.setEnabled(not self._busy and has_probe and has_file
                                  and self._chip is not None)
        self.btn_connect.setEnabled(not self._busy and has_probe and self._chip is not None)

    # ------------------------------------------------------------------ 日志
    def _append_log(self, level: str, text: str) -> None:
        color = LOG_COLORS.get(level, theme.TEXT)
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.End)

        ts = QTextCharFormat()
        ts.setForeground(QColor("#9AA6B8"))
        cursor.insertText("%s  " % time.strftime("%H:%M:%S"), ts)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if level == "error":
            fmt.setFontWeight(QFont.DemiBold)
        cursor.insertText(text + "\n", fmt)

        self.log_view.setTextCursor(cursor)
        self.log_view.ensureCursorVisible()

    def _save_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "保存日志", time.strftime("daplink_%Y%m%d_%H%M%S.log"),
            "日志文件 (*.log *.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_view.toPlainText())
            self._append_log("ok", "日志已保存到 %s" % path)
        except OSError as e:
            self._append_log("error", "保存失败：%s" % e)

    # ------------------------------------------------------------------ 关闭
    def closeEvent(self, event) -> None:
        try:
            self.sig_disconnect.emit()
            self._thread.quit()
            self._thread.wait(3000)
        except Exception:
            pass
        super().closeEvent(event)
