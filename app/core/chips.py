# -*- coding: utf-8 -*-
"""芯片库：从 targets/chips.json 读取型号表，并负责把器件包注册给 pyOCD。"""
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from .paths import chips_json, packs_dir


@dataclass(frozen=True)
class Chip:
    vendor: str
    series: str
    part: str
    pack: str
    flash_base: int
    flash_size: int
    ram_base: int
    ram_size: int
    algo: str

    @property
    def target_name(self) -> str:
        """pyOCD 的 target 名，pack_target 里按型号小写注册。"""
        return self.part.lower()

    @property
    def flash_end(self) -> int:
        return self.flash_base + self.flash_size

    @property
    def capacity_text(self) -> str:
        return "Flash %s / RAM %s" % (kb(self.flash_size), kb(self.ram_size))

    @property
    def base_text(self) -> str:
        return "0x%08X" % self.flash_base


def kb(n: int) -> str:
    if n >= 1024 * 1024 and n % (1024 * 1024) == 0:
        return "%d MB" % (n // (1024 * 1024))
    if n % 1024 == 0:
        return "%d KB" % (n // 1024)
    return "%d B" % n


class ChipLibrary:
    def __init__(self) -> None:
        with open(chips_json(), "r", encoding="utf-8") as f:
            raw = json.load(f)
        self.chips: List[Chip] = [Chip(**item) for item in raw]
        self.chips.sort(key=lambda c: (c.vendor, c.series, c.part))
        self._registered = False

    # ---- 查询 ----
    def vendors(self) -> List[str]:
        """固定展示顺序：ST → 小华 → 沁恒。"""
        order = ["ST 意法半导体", "HDSC 小华半导体", "WCH 沁恒"]
        present = _ordered_unique([c.vendor for c in self.chips])
        head = [v for v in order if v in present]
        return head + [v for v in present if v not in head]

    def series(self, vendor: str) -> List[str]:
        return _ordered_unique([c.series for c in self.chips if c.vendor == vendor])

    def parts(self, vendor: str, series: str) -> List[Chip]:
        return [c for c in self.chips if c.vendor == vendor and c.series == series]

    def find(self, vendor: str, series: str, part: str) -> Optional[Chip]:
        for c in self.chips:
            if c.vendor == vendor and c.series == series and c.part == part:
                return c
        return None

    def by_name(self, part: str) -> Optional[Chip]:
        for c in self.chips:
            if c.part.lower() == part.lower():
                return c
        return None

    # ---- pyOCD 注册 ----
    def register_packs(self) -> int:
        """把所有器件包注册进 pyOCD 的 TARGET 表，返回注册包数量。"""
        if self._registered:
            return 0
        from pyocd.target.pack import pack_target

        packs = _ordered_unique([c.pack for c in self.chips])
        paths = [os.path.join(packs_dir(), p) for p in packs]
        paths = [p for p in paths if os.path.isdir(p)]
        if paths:
            pack_target.PackTargets.populate_targets_from_pack(paths)
        self._registered = True
        return len(paths)

    def ensure_target(self, chip: Chip) -> None:
        from pyocd.target import TARGET

        self.register_packs()
        if chip.target_name not in TARGET:
            raise RuntimeError("型号 %s 未在器件包中注册（缺少 %s）" % (chip.part, chip.pack))


def _ordered_unique(items: List[str]) -> List[str]:
    seen: Dict[str, bool] = {}
    out = []
    for i in items:
        if i not in seen:
            seen[i] = True
            out.append(i)
    return out
