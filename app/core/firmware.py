# -*- coding: utf-8 -*-
"""固件文件解析：Intel HEX / 裸 BIN / ELF，统一成 (地址, 数据) 段列表。

自写解析而不直接交给 pyOCD 的原因：烧录前要先做地址越界检查，
烧录后要拿同一份数据做回读校验。
"""
import os
from dataclasses import dataclass
from typing import List, Tuple

from intelhex import IntelHex


class FirmwareError(Exception):
    pass


@dataclass
class Segment:
    addr: int
    data: bytes

    @property
    def end(self) -> int:
        return self.addr + len(self.data)


@dataclass
class Firmware:
    path: str
    file_type: str
    segments: List[Segment]

    @property
    def total_size(self) -> int:
        return sum(len(s.data) for s in self.segments)

    @property
    def start(self) -> int:
        return min(s.addr for s in self.segments)

    @property
    def end(self) -> int:
        return max(s.end for s in self.segments)

    @property
    def span_text(self) -> str:
        return "0x%08X - 0x%08X" % (self.start, self.end - 1)


SUPPORTED = (".hex", ".bin", ".elf", ".axf")


def load(path: str, base_addr: int) -> Firmware:
    if not os.path.isfile(path):
        raise FirmwareError("文件不存在: %s" % path)
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED:
        raise FirmwareError("不支持的文件格式 %s，仅支持 hex / bin / elf / axf" % ext)

    if ext == ".hex":
        segs = _load_hex(path)
    elif ext == ".bin":
        segs = _load_bin(path, base_addr)
    else:
        segs = _load_elf(path)

    segs = _merge(segs)
    if not segs:
        raise FirmwareError("文件里没有可烧录的数据")
    return Firmware(path=path, file_type=ext[1:].upper(), segments=segs)


def _load_hex(path: str) -> List[Segment]:
    try:
        ih = IntelHex(path)
    except Exception as e:
        raise FirmwareError("HEX 解析失败: %s" % e)
    segs = []
    for start, end in ih.segments():
        if end > start:
            # segments() 的 end 是开区间，tobinarray 的 size 直接给长度
            segs.append(Segment(start, bytes(ih.tobinarray(start=start, size=end - start))))
    return segs


def _load_bin(path: str, base_addr: int) -> List[Segment]:
    with open(path, "rb") as f:
        data = f.read()
    if not data:
        raise FirmwareError("BIN 文件为空")
    return [Segment(base_addr, data)]


def _load_elf(path: str) -> List[Segment]:
    try:
        from elftools.elf.elffile import ELFFile
    except ImportError:
        raise FirmwareError("缺少 pyelftools，无法解析 ELF")
    segs = []
    try:
        with open(path, "rb") as f:
            elf = ELFFile(f)
            for ph in elf.iter_segments():
                if ph["p_type"] != "PT_LOAD":
                    continue
                if ph["p_filesz"] == 0:
                    continue
                addr = int(ph["p_paddr"])
                data = ph.data()
                segs.append(Segment(addr, bytes(data)))
    except FirmwareError:
        raise
    except Exception as e:
        raise FirmwareError("ELF 解析失败: %s" % e)
    return segs


def _merge(segs: List[Segment]) -> List[Segment]:
    """按地址排序并合并相邻段，减少烧录时的碎片写入。"""
    segs = sorted([s for s in segs if s.data], key=lambda s: s.addr)
    out: List[Segment] = []
    for s in segs:
        if out and s.addr <= out[-1].end:
            prev = out[-1]
            if s.addr < prev.end:
                # 重叠：保留先到的数据，尾部补齐
                overlap = prev.end - s.addr
                if overlap >= len(s.data):
                    continue
                s = Segment(prev.end, s.data[overlap:])
            out[-1] = Segment(prev.addr, prev.data + s.data)
        else:
            out.append(s)
    return out


def check_range(fw: Firmware, flash_base: int, flash_size: int) -> Tuple[bool, str]:
    """所有数据必须落在主 Flash 区内。"""
    flash_end = flash_base + flash_size
    for s in fw.segments:
        if s.addr < flash_base or s.end > flash_end:
            return False, ("数据段 0x%08X-0x%08X 超出 Flash 范围 0x%08X-0x%08X"
                           % (s.addr, s.end - 1, flash_base, flash_end - 1))
    return True, ""
