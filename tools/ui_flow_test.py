# -*- coding: utf-8 -*-
"""界面流程测试：没有接目标板时，连接必须优雅失败并恢复可操作状态。

覆盖：线程信号往返、错误日志、忙碌状态复位。
运行：.venv\\Scripts\\python.exe tools\\ui_flow_test.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.chips import ChipLibrary  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


def pump(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main() -> int:
    app = QApplication([])
    lib = ChipLibrary()
    lib.register_packs()
    win = MainWindow(lib)
    win.show()

    if win.probe_combo.count() == 0:
        print("没有探针，跳过")
        return 0

    print("默认型号:", win.part_combo.currentText(), "|", win.lbl_capacity.text())
    print("连接前 busy=", win._busy, " btn_flash=", win.btn_flash.isEnabled())

    win._toggle_connect()
    pump(6000)
    print("连接后 busy=", win._busy, " 状态=", win.lbl_probe_state.text())
    log = win.log_view.toPlainText()
    print("--- 日志 ---")
    print(log.strip()[-600:])
    assert not win._busy, "连接失败后界面仍处于忙碌状态"
    assert ("连接失败" in log) or ("已连接" in log), "没有输出连接结果"

    win.close()
    print("UI FLOW OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
