# -*- coding: utf-8 -*-
"""离线自检：不接目标板也能验证器件包与算法是否可用。

检查项：
 1. chips.json 里每个型号都能在 pyOCD 中注册出目标类
 2. 每个包的 FLM 都能被 pyOCD 解析（符号表 / FlashDevice 结构完整）
运行：.venv\\Scripts\\python.exe tools\\selftest.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyocd.target.pack import pack_target
from pyocd.target import TARGET
from pyocd.target.pack.flash_algo import PackFlashAlgo

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "targets")


def main():
    chips = json.load(open(os.path.join(ROOT, "chips.json"), encoding="utf-8"))
    packs = sorted({c["pack"] for c in chips})
    for p in packs:
        pack_target.PackTargets.populate_targets_from_pack([os.path.join(ROOT, "packs", p)])

    missing = []
    for c in chips:
        if c["part"].lower() not in TARGET:
            missing.append(c["part"])
    print("型号总数 %d，未注册 %d" % (len(chips), len(missing)))
    if missing:
        print("  未注册示例:", missing[:10])

    bad = []
    seen = set()
    for c in chips:
        key = (c["pack"], c["algo"])
        if key in seen:
            continue
        seen.add(key)
        path = os.path.join(ROOT, "packs", c["pack"], c["algo"].replace("/", os.sep))
        try:
            algo = PackFlashAlgo(path)
            if algo.page_size <= 0 or algo.flash_size <= 0:
                bad.append((path, "页大小/容量异常"))
        except Exception as e:
            bad.append((path, "%s: %s" % (type(e).__name__, e)))
    print("算法文件 %d 个，解析失败 %d" % (len(seen), len(bad)))
    for b in bad[:10]:
        print("  ", b)
    return 0 if not missing and not bad else 1


if __name__ == "__main__":
    sys.exit(main())
