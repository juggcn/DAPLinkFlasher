# -*- coding: utf-8 -*-
"""测各档 SWD 时钟的实际可用性：读 128 KB 计时，再在末扇区写 8 KB 计时。

写测试用的是备份里该扇区的原始数据，写完内容不变，属无损操作。
运行：.venv\\Scripts\\python.exe tools\\speed_probe.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QCoreApplication  # noqa: E402

from app.core.chips import ChipLibrary  # noqa: E402
from pyocd.core.session import Session  # noqa: E402
from pyocd.flash.loader import FlashLoader  # noqa: E402
from pyocd.probe.aggregator import DebugProbeAggregator  # noqa: E402

PART = "HC32F4A0SGTB"
SPEEDS = (100_000, 500_000, 1_000_000, 2_000_000, 4_000_000, 8_000_000, 24_000_000)
READ_KB = 128
SECTOR = 0x0FF000          # 末扇区，测试时写回原内容
BACKUP = os.path.join(ROOT, "backup", "HC32F4A0_20261030_100101.bin")


def main() -> int:
    app = QCoreApplication([])
    lib = ChipLibrary()
    lib.register_packs()
    chip = lib.by_name(PART)
    uid = DebugProbeAggregator.get_all_connected_probes()[0].unique_id
    original = None
    if os.path.isfile(BACKUP):
        with open(BACKUP, "rb") as f:
            f.seek(SECTOR)
            original = f.read(8192)

    def open_session(freq):
        probe = [p for p in DebugProbeAggregator.get_all_connected_probes()
                 if p.unique_id == uid][0]
        s = Session(probe, target_override=chip.target_name,
                    options={"frequency": freq, "connect_mode": "halt",
                             "hide_programming_progress": True,
                             "flash.timeout.program": 20})
        s.open()
        return s

    print("%-10s %-14s %-12s %s" % ("时钟", "读 128KB", "读速率", "写 8KB"))
    for f in SPEEDS:
        s = None
        try:
            s = open_session(f)
            t0 = time.time()
            for off in range(0, READ_KB * 1024, 4096):
                s.target.read_memory_block8(off, 4096)
            rt = time.time() - t0
            rate = READ_KB / rt if rt else 0
            wt = "-"
            if original is not None:
                t1 = time.time()
                loader = FlashLoader(s, progress=None, chip_erase="sector", smart_flash=False)
                loader.add_data(SECTOR, original)
                loader.commit()
                wt = "%.2fs" % (time.time() - t1)
            print("%-10s %-14s %-12s %s" % ("%d kHz" % (f // 1000), "%.3fs" % rt,
                                            "%.0f KB/s" % rate, wt))
        except Exception as e:
            print("%-10s 失败: %s" % ("%d kHz" % (f // 1000), str(e).splitlines()[0][:60]))
        finally:
            if s:
                try:
                    s.close()
                except Exception:
                    pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
