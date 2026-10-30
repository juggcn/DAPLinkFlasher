# -*- coding: utf-8 -*-
"""中止逻辑的离线验证：不开硬件，用假会话把 flash() 跑起来。

覆盖三件事：
1. 写入途中点中止，要立刻停（不是等全部写完）；
2. 中止后会话被关闭，界面收到"未连接"；
3. 上一次的中止标志不能残留 —— 紧接着再下载一次必须能正常跑完。
"""
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from app.core.chips import ChipLibrary  # noqa: E402
from app.core.worker import CANCEL_TEXT, Programmer  # noqa: E402


class FakeTarget:
    def reset(self):
        pass

    def resume(self):
        pass

    def read_memory_block8(self, addr, n):
        return bytearray(n)


class FakeSession:
    def __init__(self):
        self.target = FakeTarget()
        self.closed = False

    def close(self):
        self.closed = True


def collect(prog):
    """把信号收进列表，方便断言。"""
    box = {"finished": [], "connected": [], "log": []}
    prog.finished.connect(lambda ok, msg: box["finished"].append((ok, msg)))
    prog.connected.connect(lambda ok, name: box["connected"].append((ok, name)))
    prog.log.connect(lambda lv, txt: box["log"].append((lv, txt)))
    return box


def main() -> int:
    app = QCoreApplication([])          # noqa: F841  建个事件循环上下文，保证信号行为真实
    # 先把 pyocd 导入掉：首次 import 要 1s 左右，会把计时点带偏
    from pyocd.flash.loader import FlashLoader  # noqa: F401
    lib = ChipLibrary()
    chip = lib.by_name("HC32F4A0SGTB")
    if chip is None:
        print("找不到测试型号")
        return 1

    path = os.path.join(tempfile.gettempdir(), "cancel_test.bin")
    with open(path, "wb") as f:
        f.write(bytes((i * 7) & 0xFF for i in range(200 * 1024)))

    prog = Programmer(lib)
    box = collect(prog)

    # ---- 第一轮：写到一半点中止 ----
    blocks = {"n": 0}
    prog._session = FakeSession()
    prog._chip = chip

    def slow_block(addr, block):
        blocks["n"] += 1
        time.sleep(0.25)

    prog._program_block = slow_block

    # 模拟界面线程里点"中止"：直连调用，只写标志位
    threading.Timer(0.35, prog.request_cancel).start()
    t0 = time.time()
    prog.flash({"path": path, "chip": chip, "base": chip.flash_base,
                "verify": True, "chip_erase": False, "reset": True,
                "frequency": 1_000_000, "probe_uid": "fake"})
    cost1 = time.time() - t0

    ok_fail = [x for x in box["finished"] if not x[0] and x[1] == CANCEL_TEXT]
    problems = []
    if blocks["n"] != 2:
        problems.append("中止时机不对：写了 %d 个块（期望 2 个，即 0.35s 处停下）" % blocks["n"])
    if not ok_fail:
        problems.append("没有收到中止汇总，收到的是 %s" % box["finished"])
    if prog.is_connected:
        problems.append("中止后会话没有关闭")
    if (False, "") not in box["connected"]:
        problems.append("中止后没有通知界面断开")

    print("第一轮：写了 %d 块，耗时 %.2fs（全写完约 1.75s），结果 %s"
          % (blocks["n"], cost1, box["finished"]))

    # ---- 第二轮：上一次中止过的状态，直接再下载 ----
    box["finished"].clear()
    box["connected"].clear()
    prog._cancel = True                 # 还原用户遇到的现场：标志卡在 True
    prog._session = FakeSession()
    prog._program_block = lambda addr, block: time.sleep(0.01)
    prog.flash({"path": path, "chip": chip, "base": chip.flash_base,
                "verify": False, "chip_erase": False, "reset": False,
                "frequency": 1_000_000, "probe_uid": "fake"})

    if not (box["finished"] and box["finished"][0][0]):
        problems.append("中止后再次下载失败：%s" % box["finished"])
    print("第二轮：%s" % (box["finished"],))

    if problems:
        for p in problems:
            print("  ✗ " + p)
        return 1
    print("中止逻辑正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
