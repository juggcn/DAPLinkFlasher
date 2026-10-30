# -*- coding: utf-8 -*-
"""烧录核心：跑在独立线程里，UI 只通过信号交互。

为什么要单独线程：pyOCD 的 connect / erase / program 都是阻塞调用，
全片擦除在大芯片上要几秒到十几秒，放主线程会假死。
"""
import logging
import os
import time
import traceback
from typing import Dict, Optional

from PySide6.QtCore import QObject, Signal, Slot

from .chips import Chip, ChipLibrary
from . import firmware as fwmod


# 中止时的汇总文案；界面靠它跟真正的失败区分
CANCEL_TEXT = "用户中止"


class _Cancelled(Exception):
    """用户点中止时抛这个，跟真正的烧录失败区分开。"""


class _LogBridge(logging.Handler):
    """把 pyOCD 自己的日志转到界面上，现场排查不用再开控制台。"""

    # 精简包不带 SVD，pyOCD 会报缺文件；对烧录没有影响，不用打扰用户
    _IGNORE = ("SVD file error", "pack' does not contain")

    def __init__(self, emit):
        super().__init__(logging.WARNING)
        self._emit = emit
        self.setFormatter(logging.Formatter("%(name)s: %(message)s"))

    def emit(self, record):
        try:
            msg = record.getMessage()
            if any(k in msg for k in self._IGNORE):
                return
            self._emit("warn" if record.levelno < logging.ERROR else "error", msg)
        except Exception:
            pass


# ARM CPUID 的 PARTNO -> 内核名
_CORE_PARTS = {
    0xC20: "Cortex-M0", 0xC60: "Cortex-M0+", 0xC21: "Cortex-M1",
    0xC23: "Cortex-M3", 0xC24: "Cortex-M4", 0xC27: "Cortex-M7",
    0xD20: "Cortex-M23", 0xD21: "Cortex-M33",
}


def _expected_core(chip: Chip) -> str:
    """按系列推期望内核，用来兜住"选错型号"这类误操作。"""
    s = chip.series.upper()
    if s.startswith("STM32F1") or s.startswith("STM32F0") or s.startswith("CH32F"):
        return "Cortex-M3"
    if s.startswith("STM32F4") or s.startswith("STM32H7") or s.startswith("HC32F46") \
            or s.startswith("HC32F4A"):
        return "Cortex-M4"
    if s.startswith("HC32F005") or s.startswith("HC32L") or s.startswith("STM32G0"):
        return "Cortex-M0+"
    return ""


class Programmer(QObject):
    # 单次提交给 FlashLoader 的数据量；过大会让部分厂商算法卡死
    _CHUNK = 32 * 1024

    log = Signal(str, str)          # level, text
    progress = Signal(int)          # 0-100
    state = Signal(str)             # 状态文案
    connected = Signal(bool, str)   # 是否已连接, 描述
    finished = Signal(bool, str)    # 烧录是否成功, 汇总
    speed_changed = Signal(int)     # 自动降速后的实际时钟（Hz），界面同步

    def __init__(self, lib: ChipLibrary):
        super().__init__()
        self._lib = lib
        self._session = None
        self._chip: Optional[Chip] = None
        self._probe_uid: Optional[str] = None
        self._cancel = False
        self._degraded = False
        self._frequency = 1000000
        self._bridge = _LogBridge(lambda lv, msg: self.log.emit(lv, msg))
        pyocd_log = logging.getLogger("pyocd")
        pyocd_log.addHandler(self._bridge)
        pyocd_log.setLevel(logging.WARNING)

    # ------------------------------------------------------------------ 连接
    @Slot(str, object, int)
    def connect_probe(self, probe_uid: str, chip: Chip, frequency: int) -> None:
        self._cancel = False
        self._close_session()
        try:
            from pyocd.core.session import Session
            from pyocd.probe.aggregator import DebugProbeAggregator

            self.state.emit("正在连接 %s ..." % chip.part)
            self.log.emit("info", "查找探针 %s" % probe_uid)
            self.log.emit("info", "SWD 时钟 %d kHz" % (frequency // 1000))
            probe = None
            for p in DebugProbeAggregator.get_all_connected_probes():
                if p.unique_id == probe_uid:
                    probe = p
                    break
            if probe is None:
                raise RuntimeError("探针已断开，请重新插拔后点刷新")

            self._lib.ensure_target(chip)
            self.log.emit("info", "加载器件包 %s / 目标 %s" % (chip.pack, chip.target_name))

            session = Session(probe,
                              target_override=chip.target_name,
                              options={"frequency": frequency, "connect_mode": "halt",
                                       "flash.timeout.program": 10,
                                       "flash.timeout.erase_all": 300,
                                       "hide_programming_progress": True})
            session.open()
            self._session = session
            self._chip = chip
            self._probe_uid = probe_uid
            self._frequency = frequency

            target = session.target
            try:
                idcode = "0x%08X" % target.dp.read_reg(0x00)
            except Exception:
                idcode = "未知"
            self.log.emit("ok", "已连接：%s（IDCODE %s）" % (target.part_number.upper(), idcode))
            self._check_core(target, chip)
            for r in target.memory_map:
                if r.is_flash:
                    self.log.emit("info", "  Flash: 0x%08X  长度 %d KB" % (r.start, r.length // 1024))
            self.connected.emit(True, target.part_number.upper())
            self.state.emit("已连接")
        except Exception as e:
            self._close_session()
            self.log.emit("error", "连接失败：%s" % _brief(e))
            self.connected.emit(False, "")
            self.state.emit("未连接")

    @Slot()
    def disconnect_probe(self) -> None:
        self._close_session()
        self.connected.emit(False, "")
        self.state.emit("未连接")
        self.log.emit("info", "已断开")

    # ------------------------------------------------------------------ 烧录
    @Slot(dict)
    def flash(self, params: Dict) -> None:
        t_start = time.time()
        self._cancel = False          # 上一次中止的标志必须清掉，否则一进来就退出
        self._degraded = False
        path = params["path"]
        chip: Chip = params["chip"]
        do_verify = params.get("verify", True)
        chip_erase = params.get("chip_erase", False)
        reset_after = params.get("reset", True)

        try:
            self.progress.emit(0)
            self.state.emit("解析固件")
            fw = fwmod.load(path, params.get("base", chip.flash_base))
            ok, msg = fwmod.check_range(fw, chip.flash_base, chip.flash_size)
            if not ok:
                raise fwmod.FirmwareError(msg)
            self.log.emit("info", "固件 %s，%d 段，共 %d 字节，地址 %s"
                          % (os.path.basename(path), len(fw.segments),
                             fw.total_size, fw.span_text))

            if self._session is None or self._chip is None or self._chip.part != chip.part:
                self.log.emit("info", "尚未连接，先建立连接")
                uid = params.get("probe_uid") or self._probe_uid or ""
                self.connect_probe(uid, chip, params.get("frequency", 1000000))
                if self._session is None:
                    raise RuntimeError("连接未建立，无法烧录")

            self._erase_and_program(fw, chip_erase)
            if self._cancel:
                raise _Cancelled()
            if do_verify:
                self._verify(fw)
            if reset_after:
                self.state.emit("复位运行")
                self._session.target.reset()
                try:
                    self._session.target.resume()
                except Exception:
                    pass
                self.log.emit("ok", "已复位并运行")

            self.progress.emit(100)
            cost = time.time() - t_start
            summary = "烧录完成，用时 %.1f s" % cost
            self.log.emit("ok", summary)
            self.state.emit("完成")
            self.finished.emit(True, summary)
        except _Cancelled:
            self.log.emit("warn", "已中止：目标机可能停在半写状态，请重新下载")
            self._close_session()      # 中途打断后算法状态不可信，断开重连更稳
            self.connected.emit(False, "")   # 会话已关，界面上不能还显示"已连接"
            self.state.emit("已中止")
            self.progress.emit(0)
            self.finished.emit(False, CANCEL_TEXT)
        except Exception as e:
            self.log.emit("error", "烧录失败：%s" % _brief(e))
            if not isinstance(e, (fwmod.FirmwareError, RuntimeError, OSError)):
                for line in traceback.format_exc().splitlines()[-4:]:
                    self.log.emit("error", "  " + line)
            self.state.emit("失败")
            self.progress.emit(0)
            self.finished.emit(False, _brief(e))

    def _erase_and_program(self, fw: "fwmod.Firmware", chip_erase: bool) -> None:
        from pyocd.flash.loader import FlashLoader

        self.state.emit("擦除并写入")
        self.log.emit("info", "擦除方式：%s" % ("全片擦除" if chip_erase else "按扇区擦除"))
        if chip_erase:
            from pyocd.flash.eraser import FlashEraser

            FlashEraser(self._session, FlashEraser.Mode.CHIP).erase()

        # 分块提交：一次性提交几百 KB 时 HC32 的算法会卡死（实测 1MB 单次提交超时），
        # 每 32 KB 重新初始化一次算法最稳；块越小中止响应越快，但算法重启开销也越多。
        total = fw.total_size or 1
        done = 0
        for seg in fw.segments:
            offset = 0
            while offset < len(seg.data):
                if self._cancel:
                    raise _Cancelled()
                n = min(self._CHUNK, len(seg.data) - offset)
                addr = seg.addr + offset
                block = seg.data[offset:offset + n]
                try:
                    self._program_block(addr, block)
                except _Cancelled:
                    raise
                except Exception as e:
                    if self._cancel:
                        raise _Cancelled()      # 已经点了中止，别再花时间降速重连
                    if self._degraded:
                        raise
                    # 现场经验：长数据在 1 MHz 下偶发算法超时，降到 500 kHz 重来一次能过
                    self._degraded = True
                    fallback = max(100_000, self._frequency // 2)
                    self.log.emit("warn", "写入 0x%08X 失败（%s），降速到 %d kHz 重试"
                                  % (addr, _brief(e), fallback // 1000))
                    self._reopen(fallback)
                    self._frequency = fallback
                    self.speed_changed.emit(fallback)
                    self._program_block(addr, block)
                offset += n
                done += n
                self.progress.emit(1 + int(done * 78 / total))
        self.progress.emit(80)

    def _program_block(self, addr: int, block: bytes) -> None:
        from pyocd.flash.loader import FlashLoader

        # 把进度回调接上：pyOCD 每写完一页回调一次，借这个时机检查中止，
        # 否则 32KB 一个块要整体写完才有机会停（遇到算法卡住时要等到超时）。
        loader = FlashLoader(self._session, progress=self._page_progress,
                             chip_erase="sector", smart_flash=False)
        loader.add_data(addr, block)
        loader.commit()

    def _page_progress(self, fraction: float) -> None:
        if self._cancel:
            raise _Cancelled()

    def _reopen(self, frequency: int) -> None:
        """降速重连：探针不变，只重建会话。"""
        from pyocd.core.session import Session
        from pyocd.probe.aggregator import DebugProbeAggregator

        self._close_session()
        probe = None
        for p in DebugProbeAggregator.get_all_connected_probes():
            if p.unique_id == self._probe_uid:
                probe = p
                break
        if probe is None:
            raise RuntimeError("重连失败：探针已断开")
        session = Session(probe, target_override=self._chip.target_name,
                          options={"frequency": frequency, "connect_mode": "halt",
                                   "flash.timeout.program": 10,
                                   "flash.timeout.erase_all": 300,
                                   "hide_programming_progress": True})
        session.open()
        self._session = session

    def _verify(self, fw: "fwmod.Firmware") -> None:
        self.state.emit("回读校验")
        self.log.emit("info", "开始回读校验 %d 字节" % fw.total_size)
        target = self._session.target
        total = fw.total_size or 1
        done = 0
        chunk = 4096
        for seg in fw.segments:
            offset = 0
            while offset < len(seg.data):
                if self._cancel:
                    raise _Cancelled()
                n = min(chunk, len(seg.data) - offset)
                addr = seg.addr + offset
                expect = seg.data[offset:offset + n]
                got = bytes(target.read_memory_block8(addr, n))
                if got != expect:
                    for i in range(n):
                        if got[i] != expect[i]:
                            raise RuntimeError("校验失败：地址 0x%08X 期望 0x%02X 实际 0x%02X"
                                               % (addr + i, expect[i], got[i]))
                    raise RuntimeError("校验失败：地址 0x%08X 数据不一致" % addr)
                offset += n
                done += n
                self.progress.emit(80 + int(done * 18 / total))
        self.log.emit("ok", "回读校验通过")

    @Slot()
    def request_cancel(self) -> None:
        # 这个槽由界面线程直连调用：本线程此时正卡在 flash() 里出不来，
        # 走队列的话信号要等 flash() 返回才处理，中止就会失效。
        # 所以这里只允许写标志位 / 发信号，绝不能碰 session。
        if self._cancel:
            return
        self._cancel = True
        self.state.emit("正在中止…")
        self.log.emit("warn", "已请求中止，等当前写入块结束…")

    # ------------------------------------------------------------------ 内部
    def _check_core(self, target, chip: Chip) -> None:
        """读 CPUID 核对内核，型号选错时给出明确警告，避免往错误的芯片里写。"""
        try:
            cpuid = target.read32(0xE000ED00)
        except Exception:
            return
        name = _CORE_PARTS.get((cpuid >> 4) & 0xFFF, "")
        if not name:
            return
        self.log.emit("info", "  内核 %s（CPUID 0x%08X）" % (name, cpuid))
        expect = _expected_core(chip)
        if expect and expect != name:
            self.log.emit("warn", "  内核为 %s，与所选 %s（应为 %s）不符，请核对型号后再下载"
                          % (name, chip.part, expect))

    def _close_session(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
        self._session = None

    @property
    def is_connected(self) -> bool:
        return self._session is not None


def _brief(e: Exception) -> str:
    text = str(e).strip()
    if not text:
        text = e.__class__.__name__
    return text.splitlines()[0]
