# -*- coding: utf-8 -*-
"""真机验证中止：写一半点中止 -> 立刻再下载一次 -> 跑完 -> 恢复原固件。

对应现场反馈："下载中按中止没立刻停，进度条走完显示失败，再点开始就报用户中止"。
运行：.venv\\Scripts\\python.exe tools\\hw_cancel_test.py
"""
import os
import sys
import threading
import time
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QCoreApplication  # noqa: E402

from app.core.chips import ChipLibrary  # noqa: E402
from app.core.worker import CANCEL_TEXT, Programmer  # noqa: E402

PART = "HC32F4A0SGTB"
IMG_SIZE = 256 * 1024          # 够长，能在中途打断
CANCEL_DELAY = 1.5             # 开始写入 1.5s 后点中止


def read_flash(target, base: int, size: int) -> bytes:
    out = bytearray()
    for off in range(0, size, 4096):
        n = min(4096, size - off)
        out += bytes(target.read_memory_block8(base + off, n))
    return bytes(out)


def make_image() -> bytes:
    img = bytearray(IMG_SIZE)
    for i in range(IMG_SIZE):
        img[i] = (i * 31 + 7) & 0xFF
    return bytes(img)


def main() -> int:
    app = QCoreApplication([])      # noqa: F841
    lib = ChipLibrary()
    lib.register_packs()
    chip = lib.by_name(PART)

    from pyocd.probe.aggregator import DebugProbeAggregator
    probes = DebugProbeAggregator.get_all_connected_probes()
    if not probes:
        print("没有探针")
        return 1
    uid = probes[0].unique_id
    print("探针:", probes[0].product_name, uid)

    prog = Programmer(lib)
    prog.log.connect(lambda lv, m: print("   [%s] %s" % (lv, m), flush=True))
    result = {"ok": None, "msg": ""}

    def on_finished(ok, msg):
        result["ok"] = ok
        result["msg"] = msg
        print("   >> 结束: ok=%s msg=%s 连接=%s" % (ok, msg, prog.is_connected), flush=True)

    prog.finished.connect(on_finished)

    print("== 1. 连接 + 备份 ==")
    prog.connect_probe(uid, chip, 1000000)
    if not prog.is_connected:
        print("连接失败")
        return 1
    target = prog._session.target
    t0 = time.time()
    backup = read_flash(target, chip.flash_base, chip.flash_size)
    print("   备份 %d KB，%.1f s，CRC32=%08X"
          % (len(backup) // 1024, time.time() - t0, zlib.crc32(backup) & 0xFFFFFFFF))

    os.makedirs("backup", exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    bak = os.path.join("backup", "cancel_bak_%s.bin" % stamp)
    with open(bak, "wb") as f:
        f.write(backup)
    img_path = os.path.join("backup", "cancel_img_%s.bin" % stamp)
    with open(img_path, "wb") as f:
        f.write(make_image())
    print("   备份 %s" % bak)

    params = {"path": img_path, "chip": chip, "base": chip.flash_base,
              "verify": True, "chip_erase": False, "reset": False,
              "frequency": 1_000_000, "probe_uid": uid}

    print("== 2. 写到一半点中止 ==")
    result["ok"] = None
    timer = threading.Timer(CANCEL_DELAY, prog.request_cancel)
    timer.start()
    t1 = time.time()
    prog.flash(dict(params))
    cost = time.time() - t1
    timer.cancel()
    print("   中止耗时 %.1f s，结果 %s" % (cost, result))
    aborted = (result["ok"] is False and result["msg"] == CANCEL_TEXT
               and not prog.is_connected and cost < 6)

    print("== 3. 紧接着再下载（不手动重连） ==")
    result["ok"] = None
    t2 = time.time()
    prog.flash(dict(params))
    cost2 = time.time() - t2
    ok2 = result["ok"] is True
    print("   第二次耗时 %.1f s，结果 %s" % (cost2, result))

    print("== 4. 比对镜像 ==")
    got = read_flash(prog._session.target, chip.flash_base, IMG_SIZE)
    same = got == make_image()
    print("   回读与镜像: %s" % ("一致" if same else "不一致"))

    print("== 5. 恢复原固件 ==")
    used = len(backup.rstrip(b"\xFF"))
    restore_len = min(chip.flash_size, ((used + 8191) // 8192) * 8192)
    restore_path = os.path.join("backup", "cancel_restore_%s.bin" % stamp)
    with open(restore_path, "wb") as f:
        f.write(backup[:restore_len])
    result["ok"] = None
    prog.flash({"path": restore_path, "chip": chip, "base": chip.flash_base,
                "verify": True, "chip_erase": True, "reset": True,
                "frequency": 1_000_000, "probe_uid": uid})
    ok3 = result["ok"] is True
    after = read_flash(prog._session.target, chip.flash_base, chip.flash_size)
    diff = sum(1 for a, b in zip(after, backup) if a != b)
    print("   恢复 %s，整片差异 %d 字节" % ("成功" if ok3 else "失败", diff))
    prog.disconnect_probe()

    print()
    print("中止及时生效 :", "是" if aborted else "否")
    print("中止后可再下载:", "是" if ok2 and same else "否")
    print("原固件已恢复  :", "是" if ok3 and diff == 0 else "否")
    return 0 if (aborted and ok2 and same and ok3 and diff == 0) else 2


if __name__ == "__main__":
    sys.exit(main())
