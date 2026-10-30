# -*- coding: utf-8 -*-
"""从 Keil 器件包 PDSC 中提取芯片的内存映射与烧录算法，生成 targets.json。

用法: python tools/dump_pack.py
只读本机已安装的 CMSIS-Pack，不做任何写入以外的操作。
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

PACK_ROOT = os.path.expanduser(r"~\AppData\Local\Arm\Packs")

# 需要纳入的器件包（厂商目录/包名）
PACKS = [
    ("Keil", "STM32F1xx_DFP"),
    ("Keil", "STM32F4xx_DFP"),
    ("HDSC", "HC32F460"),
    ("HDSC", "HC32F4A0"),
    ("Keil", "WCH32F2xx_DFP"),
]

# 只保留这些前缀的器件（Dname 前缀）
KEEP_PREFIX = ("STM32F103", "STM32F407", "STM32F405", "STM32F401", "STM32F411",
               "HC32F460", "HC32F4A0", "CH32F203", "CH32F205", "CH32F207", "CH32F208")


def find_pdsc(vendor, name):
    base = os.path.join(PACK_ROOT, vendor, name)
    if not os.path.isdir(base):
        return None
    # 取版本号最大的子目录
    vers = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))]
    if not vers:
        return None
    vers.sort(key=lambda s: [int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", s)])
    for v in reversed(vers):
        for f in os.listdir(os.path.join(base, v)):
            if f.lower().endswith(".pdsc"):
                return os.path.join(base, v, f)
    return None


def parse(pdsc):
    tree = ET.parse(pdsc)
    root = tree.getroot()
    base = os.path.dirname(pdsc)
    out = {}
    for dev in root.iter("device"):
        dname = dev.get("Dname", "")
        if not dname.startswith(KEEP_PREFIX):
            continue
        # 顺着 family/subFamily 继承（这里只处理 device 自身 + 直系 family 的 memory）
        mem = []
        algos = []
        for m in dev.findall("memory"):
            mem.append({"id": m.get("id"), "start": m.get("start"),
                        "size": m.get("size"), "access": m.get("access", "")})
        for a in dev.findall("algorithm"):
            fn = a.get("name", "")
            # PDSC 里算法名可能是文件名，也可能带路径
            cand = [os.path.join(base, fn), os.path.join(base, "Flash", fn),
                    os.path.join(base, "FlashARM", fn), os.path.join(base, "CMSIS", "Flash", fn)]
            for c in cand:
                if os.path.isfile(c):
                    fn = os.path.relpath(c, base)
                    break
            algos.append({"file": fn, "start": a.get("start"), "size": a.get("size")})
        out[dname] = {"memory": mem, "algorithms": algos}
    return out


def main():
    result = {}
    for vendor, name in PACKS:
        p = find_pdsc(vendor, name)
        if not p:
            print("缺少器件包:", vendor, name)
            continue
        devs = parse(p)
        print("%s/%s: %d 个器件" % (vendor, name, len(devs)))
        result[name] = {"pdsc": p, "devices": devs}
    with open("tools/targets_raw.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("已写入 tools/targets_raw.json")


if __name__ == "__main__":
    main()
