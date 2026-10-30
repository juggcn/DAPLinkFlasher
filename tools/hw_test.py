# -*- coding: utf-8 -*-
"""硬件联调脚本：备份 -> 烧录测试镜像 -> 校验 -> 恢复。

只用于开发期验证，正常使用直接跑界面程序即可。
运行：.venv\\Scripts\\python.exe tools\\hw_test.py
"""
import os
import sys
import time
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QCoreApplication  # noqa: E402

from app.core.chips import ChipLibrary  # noqa: E402
from app.core.worker import Programmer  # noqa: E402

PART = "HC32F4A0SGTB"
CHUNK = 4096


def read_flash(target, base: int, size: int) -> bytes:
    out = bytearray()
    for off in range(0, size, CHUNK):
        n = min(CHUNK, size - off)
        out += bytes(target.read_memory_block8(base + off, n))
    return bytes(out)


def make_test_image() -> bytes:
    """最小可运行镜像：SP 指向 RAM，复位向量进死循环，其余填特征码。"""
    import struct

    img = bytearray(b"\xFF" * 1024)
    struct.pack_into("<I", img, 0x00, 0x20020000)      # 初始 SP（HC32F4A0 RAM 内）
    struct.pack_into("<I", img, 0x04, 0x00000101)      # Reset_Handler = 0x100 | thumb
    img[0x100:0x102] = b"\xFE\xE7"                     # b .
    for i in range(0x200, 0x400):
        img[i] = (i * 31 + 7) & 0xFF
    return bytes(img)


def main() -> int:
    app = QCoreApplication([])
    lib = ChipLibrary()
    lib.register_packs()
    chip = lib.by_name(PART)
    assert chip, PART

    from pyocd.probe.aggregator import DebugProbeAggregator
    probes = DebugProbeAggregator.get_all_connected_probes()
    if not probes:
        print("没有探针")
        return 1
    uid = probes[0].unique_id
    print("探针:", probes[0].product_name, uid)

    prog = Programmer(lib)
    prog.log.connect(lambda lv, m: print("   [%s] %s" % (lv, m), flush=True))
    result = {"ok": False}

    def on_finished(ok, msg):
        result["ok"] = ok
        print("   >> 完成: %s (%s)" % (ok, msg), flush=True)

    prog.finished.connect(on_finished)

    print("== 1. 连接 ==")
    prog.connect_probe(uid, chip, 1000000)
    if not prog.is_connected:
        print("连接失败")
        return 1

    target = prog._session.target
    print("== 2. 备份整片 Flash ==")
    t0 = time.time()
    backup = read_flash(target, chip.flash_base, chip.flash_size)
    print("   读回 %d KB，用时 %.1f s，CRC32=%08X"
          % (len(backup) // 1024, time.time() - t0, zlib.crc32(backup) & 0xFFFFFFFF))
    used = len(backup.rstrip(b"\xFF"))
    print("   非空区 %d 字节（%.1f KB）" % (used, used / 1024))

    os.makedirs("backup", exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    bak_path = os.path.join("backup", "HC32F4A0_%s.bin" % stamp)
    with open(bak_path, "wb") as f:
        f.write(backup)
    print("   备份已保存:", bak_path)

    print("== 3. 烧录测试镜像 ==")
    test_path = os.path.join("backup", "test_pattern_%s.bin" % stamp)
    img = make_test_image()
    with open(test_path, "wb") as f:
        f.write(img)
    result["ok"] = False
    prog.flash({"path": test_path, "chip": chip, "base": chip.flash_base,
                "verify": True, "chip_erase": False, "reset": True,
                "probe_uid": uid})
    ok = result["ok"]
    time.sleep(0.5)
    got = read_flash(prog._session.target, chip.flash_base, len(img))
    same = got == img
    print("   烧录结果: %s，回读比对: %s" % ("成功" if ok else "失败", "一致" if same else "不一致"))
    if not same:
        for i in range(len(img)):
            if got[i] != img[i]:
                print("   首个差异 @0x%X 期望 %02X 实际 %02X" % (i, img[i], got[i]))
                break

    print("== 4. 恢复原固件 ==")
    # 只写回有内容的部分，末尾补到扇区边界（8KB）
    used = len(backup.rstrip(b"\xFF"))
    restore_len = min(chip.flash_size, ((used + 8191) // 8192) * 8192)
    restore_path = os.path.join("backup", "restore_%s.bin" % stamp)
    with open(restore_path, "wb") as f:
        f.write(backup[:restore_len])
    print("   恢复 %d 字节（%.1f KB）" % (restore_len, restore_len / 1024))
    result["ok"] = False
    prog.flash({"path": restore_path, "chip": chip, "base": chip.flash_base,
                "verify": True, "chip_erase": True, "reset": True,
                "probe_uid": uid})
    ok2 = result["ok"]

    print("== 5. 恢复后整片比对 ==")
    after = read_flash(prog._session.target, chip.flash_base, chip.flash_size)
    diff = sum(1 for a, b in zip(after, backup) if a != b)
    print("   恢复结果: %s，与备份差异字节数: %d" % ("成功" if ok2 else "失败", diff))
    prog.disconnect_probe()
    return 0 if (ok and same and ok2 and diff == 0) else 2


if __name__ == "__main__":
    sys.exit(main())
