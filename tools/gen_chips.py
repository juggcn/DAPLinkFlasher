# -*- coding: utf-8 -*-
"""从本机 Keil CMSIS-Pack 生成芯片库。

产物：
  app/targets/packs/<KEY>/...   —— 精简展开包（pdsc + 需要的 FLM）
  app/targets/chips.json        —— 型号 / 系列 / Flash 与 RAM 区间

只在开发期跑一次；运行时程序直接读 chips.json，不再碰 Keil 安装目录。
"""
import json
import os
import re
import shutil
import xml.etree.ElementTree as ET

PACK_ROOT = os.path.expanduser(r"~\AppData\Local\Arm\Packs")
OUT_PACKS = os.path.join("app", "targets", "packs")
OUT_JSON = os.path.join("app", "targets", "chips.json")

# 包键 -> (厂商目录, 包名, 界面显示厂商, 系列白名单或 None)
PACKS = {
    "STM32F1": ("Keil", "STM32F1xx_DFP", "ST 意法半导体", None),
    "STM32F4": ("Keil", "STM32F4xx_DFP", "ST 意法半导体", None),
    "HC32F460": ("HDSC", "HC32F460", "HDSC 小华半导体", None),
    "HC32F4A0": ("HDSC", "HC32F4A0", "HDSC 小华半导体", None),
    "CH32F2": ("Keil", "WCH32F2xx_DFP", "WCH 沁恒", None),
}


def latest_version_dir(base):
    vers = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))]
    vers.sort(key=lambda s: [int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", s)])
    return os.path.join(base, vers[-1]) if vers else None


def find_pdsc(dirpath):
    for f in os.listdir(dirpath):
        if f.lower().endswith(".pdsc"):
            return os.path.join(dirpath, f)
    return None


def norm_algo(base, name, copy_list):
    """把 pdsc 里的算法路径规整成相对包根的形式，并登记待拷贝文件。"""
    rel = name.replace("\\", "/")
    src = os.path.join(base, rel)
    if not os.path.isfile(src):
        # 少数包把文件放在约定子目录
        for sub in ("Flash", "FlashARM", "CMSIS/Flash"):
            cand = os.path.join(base, sub, os.path.basename(rel))
            if os.path.isfile(cand):
                rel = os.path.join(sub, os.path.basename(rel)).replace("\\", "/")
                src = cand
                break
    if os.path.isfile(src):
        copy_list.add(rel)
        return rel
    return None


def mem_list(node):
    out = []
    for m in node.findall("memory"):
        out.append({
            "id": m.get("id"),
            "start": int(m.get("start"), 0),
            "size": int(m.get("size"), 0),
            "access": (m.get("access") or ""),
        })
    return out


def algo_list(base, node, copy_list):
    out = []
    for a in node.findall("algorithm"):
        rel = norm_algo(base, a.get("name", ""), copy_list)
        if rel is None:
            continue
        out.append({
            "file": rel,
            "start": int(a.get("start"), 0),
            "size": int(a.get("size"), 0),
        })
    return out


def patch_pdsc_ram(pdsc_path):
    """删掉算法元素上的 RAMstart/RAMsize，让 pyOCD 用整块 IRAM 放算法。"""
    os.chmod(pdsc_path, 0o666)
    with open(pdsc_path, "r", encoding="utf-8") as f:
        text = f.read()
    new, n = re.subn(r'\s*RAMstart="[^"]*"\s*RAMsize="[^"]*"', "", text)
    if n:
        with open(pdsc_path, "w", encoding="utf-8") as f:
            f.write(new)
        print("  去掉 %d 处算法 RAM 限制" % n)


def pick_flash(mems):
    """主 Flash 区：IROM 且可执行，取起始地址最小的一个。"""
    cands = [m for m in mems if m["id"] and m["id"].upper().startswith("IROM")]
    if not cands:
        return None
    cands.sort(key=lambda m: m["start"])
    return cands[0]


def pick_ram(mems):
    cands = [m for m in mems if m["id"] and m["id"].upper().startswith("IRAM")]
    if not cands:
        return None
    cands.sort(key=lambda m: m["start"])
    return cands[0]


def main():
    chips = []
    if os.path.isdir(OUT_PACKS):
        shutil.rmtree(OUT_PACKS)
    os.makedirs(OUT_PACKS, exist_ok=True)

    for key, (vendor, packname, vendor_cn, only_series) in PACKS.items():
        vdir = latest_version_dir(os.path.join(PACK_ROOT, vendor, packname))
        if not vdir:
            print("跳过（未安装）:", vendor, packname)
            continue
        pdsc = find_pdsc(vdir)
        root = ET.parse(pdsc).getroot()
        copy_list = set()
        entries = []

        # 家族级继承（部分包把算法写在 <family>/<subFamily>）
        devices_node = root.find("devices")
        family_list = devices_node.findall("family") if devices_node is not None else root.findall("family")
        for family in family_list:
            fam_mems = mem_list(family)
            fam_algos = algo_list(vdir, family, copy_list)
            for sub in family.findall("subFamily"):
                sub_mems = fam_mems + mem_list(sub)
                sub_algos = fam_algos + algo_list(vdir, sub, copy_list)
                sub_name = sub.get("DsubFamily") or family.get("Dfamily")
                for dev in sub.findall("device"):
                    entries.append((sub_name, dev, sub_mems, sub_algos))
                # 个别包把 variant 再嵌一层
                for var in sub.findall("variant"):
                    for dev in var.findall("device"):
                        entries.append((sub_name, dev, sub_mems, sub_algos))
            # 没有 subFamily 时家族下直接挂 device
            for dev in family.findall("device"):
                entries.append((family.get("Dfamily"), dev, fam_mems, fam_algos))

        for series, dev, inherited_mems, inherited_algos in entries:
            if only_series and series not in only_series:
                continue
            part = dev.get("Dname", "")
            if not part:
                continue
            mems = inherited_mems + mem_list(dev)
            algos = inherited_algos + algo_list(vdir, dev, copy_list)
            flash = pick_flash(mems)
            ram = pick_ram(mems)
            if not flash or not ram:
                continue
            # 选与 Flash 起始地址匹配的第一条算法
            algo = next((a for a in algos if a["start"] == flash["start"]), None)
            if not algo:
                print("  ! 无算法:", part)
                continue
            chips.append({
                "vendor": vendor_cn,
                "series": series,
                "part": part,
                "pack": key,
                "flash_base": flash["start"],
                "flash_size": flash["size"],
                "ram_base": ram["start"],
                "ram_size": ram["size"],
                "algo": algo["file"],
            })

        # 拷 pdsc + 算法文件
        dst = os.path.join(OUT_PACKS, key)
        os.makedirs(dst, exist_ok=True)
        shutil.copy2(pdsc, dst)
        # 去掉 <algorithm> 上的 RAMstart/RAMsize：HC32 给算法只留 16 KB，
        # pyOCD 还要在这块里放两个页缓冲，栈只剩 12.8 KB，1 MB 写入会超时。
        patch_pdsc_ram(os.path.join(dst, os.path.basename(pdsc)))
        for rel in sorted(copy_list):
            src = os.path.join(vdir, rel.replace("/", os.sep))
            target = os.path.join(dst, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(src, target)
        print("%-9s %3d 个型号, %2d 个算法文件" % (key, len(entries), len(copy_list)))

    # 去重（同一 part 可能被 variant 重复收进来）
    uniq = {}
    for c in chips:
        uniq[(c["pack"], c["part"])] = c
    chips = sorted(uniq.values(), key=lambda c: (c["vendor"], c["series"], c["part"]))

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(chips, f, ensure_ascii=False, indent=1)
    print("共 %d 个型号 -> %s" % (len(chips), OUT_JSON))


if __name__ == "__main__":
    main()
