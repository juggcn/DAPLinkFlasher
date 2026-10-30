# -*- coding: utf-8 -*-
"""程序入口。"""
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from .core.chips import ChipLibrary
from .ui import theme
from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("DAPLink 下载工具")
    app.setWindowIcon(theme.app_icon())
    app.setStyleSheet(theme.build_qss())

    try:
        lib = ChipLibrary()
        lib.register_packs()
    except Exception as e:
        QMessageBox.critical(None, "启动失败", "器件包加载失败：\n%s" % e)
        return 1

    win = MainWindow(lib)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
