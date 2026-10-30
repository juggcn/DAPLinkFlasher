# -*- coding: utf-8 -*-
"""中止信号的跨线程验证：worker 放 QThread 里，跟界面用法一致。

对比两种连接方式，确认「直连」是必须的：
  队列连接（改之前）→ 点中止后 flash() 还在跑，信号排到最后才处理，等于没中止；
  直连（改之后）  → 中止在下一个写入块边界生效。
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication, QObject, QThread, QTimer, Qt, Signal  # noqa: E402

from app.core.chips import ChipLibrary  # noqa: E402
from app.core.worker import Programmer  # noqa: E402

BLOCK = 0.20          # 每块耗时，7 块共约 1.4s
CANCEL_AT = 450       # 400ms 时点中止：落在第 3 块中间


class FakeTarget:
    def reset(self):
        pass

    def resume(self):
        pass


class FakeSession:
    def __init__(self):
        self.target = FakeTarget()

    def close(self):
        pass


class Host(QObject):
    """模仿主窗口：只负责把信号发出去、把结果收回来。"""
    sig_cancel = Signal()
    sig_flash = Signal(dict)

    def __init__(self, conn):
        super().__init__()
        self.cancelled_at = None
        self.finished = []
        self.blocks = 0

        self.thread = QThread()
        self.worker = Programmer(lib)
        self.worker.moveToThread(self.thread)

        worker = self.worker

        def slow_block(addr, block):
            # 模拟 pyOCD 写一个块：内部按页推进，每页回调一次（真实的中止检查点）
            self.blocks += 1
            for _ in range(8):
                time.sleep(BLOCK / 8)
                worker._page_progress(0.5)

        self.worker._program_block = slow_block
        self.sig_flash.connect(self.worker.flash)      # 排队，跟界面一样进 worker 线程
        self.sig_cancel.connect(self.worker.request_cancel, conn)
        self.worker.finished.connect(self._on_finished)
        self.thread.start()

    def start(self, chip, path):
        params = {"path": path, "chip": chip, "base": chip.flash_base,
                  "verify": False, "chip_erase": False, "reset": False,
                  "frequency": 1_000_000, "probe_uid": "fake"}
        QTimer.singleShot(CANCEL_AT, self._do_cancel)
        QTimer.singleShot(0, lambda: self.sig_flash.emit(params))

    def _do_cancel(self):
        self.t0 = time.time()
        self.sig_cancel.emit()

    def _on_finished(self, ok, msg):
        self.finished.append((ok, msg, self.blocks))
        self.thread.quit()


lib = None


def run(conn, chip, path):
    app = QCoreApplication.instance() or QCoreApplication([])
    host = Host(conn)
    host.worker._session = FakeSession()
    host.worker._chip = chip
    host.start(chip, path)
    QTimer.singleShot(8000, app.quit)      # 兜底，别挂死
    app.exec()
    return host.finished[0]


def main() -> int:
    global lib
    lib = ChipLibrary()
    chip = lib.by_name("HC32F4A0SGTB")
    path = os.path.join(tempfile.gettempdir(), "cancel_test.bin")
    if not os.path.isfile(path):
        with open(path, "wb") as f:
            f.write(bytes(200 * 1024))

    bad = run(Qt.ConnectionType.AutoConnection, chip, path)
    good = run(Qt.ConnectionType.DirectConnection, chip, path)

    print("队列连接（旧行为）：%d 块，结果 %s" % (bad[2], bad[:2]))
    print("直连（新行为）  ：%d 块，结果 %s" % (good[2], good[:2]))

    problems = []
    if bad[2] != 7 or not bad[0]:
        problems.append("旧行为预期是跑完全部 7 块并报成功，实测 %s" % (bad,))
    if good[2] > 4 or good[0]:
        problems.append("直连中止没能及时生效：%s" % (good,))
    for p in problems:
        print("  ✗ " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
