# -*- coding: utf-8 -*-
"""无界面冒烟测试：验证芯片库、固件解析、界面构建三部分不抛异常。

运行：.venv\Scripts\python.exe tools\smoke_test.py
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from intelhex import IntelHex  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import firmware as fwmod  # noqa: E402
from app.core.chips import ChipLibrary  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


def make_hex(path: str, base: int, size: int) -> None:
    ih = IntelHex()
    ih.puts(base, bytes((i * 7 + 3) & 0xFF for i in range(size)))
    ih.write_hex_file(path)


def main() -> int:
    lib = ChipLibrary()
    print("型号 %d 个，厂商 %s" % (len(lib.chips), lib.vendors()))

    # 1. 三家的代表型号都要能注册
    for part in ("STM32F103C8", "STM32F407ZG", "HC32F460PETB", "HC32F4A0SGTB", "CH32F203C8"):
        chip = lib.by_name(part)
        assert chip is not None, part
        lib.ensure_target(chip)
        print("  ok %-14s flash %06X/%dK  algo=%s"
              % (part, chip.flash_base, chip.flash_size // 1024, chip.algo))

    # 2. 固件解析
    tmp = tempfile.mkdtemp()
    hex_path = os.path.join(tmp, "app.hex")
    make_hex(hex_path, 0x08000000, 1024)
    fw = fwmod.load(hex_path, 0x08000000)
    print("HEX 解析: %d 段 %d 字节 %s" % (len(fw.segments), fw.total_size, fw.span_text))
    ok, msg = fwmod.check_range(fw, 0x08000000, 64 * 1024)
    print("范围检查:", ok, msg)

    bin_path = os.path.join(tmp, "app.bin")
    with open(bin_path, "wb") as f:
        f.write(b"\xA5" * 512)
    fw2 = fwmod.load(bin_path, 0x00000000)
    print("BIN 解析: 起始 0x%08X 长度 %d" % (fw2.start, fw2.total_size))
    ok, msg = fwmod.check_range(fw2, 0x08000000, 64 * 1024)
    print("越界检查(应失败):", ok, msg)

    # 3. 界面构建
    app = QApplication([])
    win = MainWindow(lib)
    win.show()
    print("窗口构建成功：探针 %d 个，型号下拉 %d 项"
          % (win.probe_combo.count(), win.part_combo.count()))
    QTimer.singleShot(300, app.quit)
    app.exec()
    win.close()
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
