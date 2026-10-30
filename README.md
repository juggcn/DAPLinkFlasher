# DAPLink 下载工具

基于 CMSIS-DAP 探针（DAPLink / XV-Link 等）给 **STM32 / HC32 / CH32** 单片机下载程序的 Windows 图形工具。
烧录算法直接取自各厂家 CMSIS-Pack 里的 `.FLM`，由工具加载进目标机 RAM 执行，因此不依赖 Keil、ST-Link 驱动或 OpenOCD。

## 支持的芯片

型号库由本机已装的器件包生成，当前共 **275 个型号**：

| 厂商 | 系列 | 型号示例 | Flash 起始 |
|---|---|---|---|
| ST 意法半导体 | STM32F1xx | STM32F103C8 / RB / RC / VE / ZE … | 0x08000000 |
| ST 意法半导体 | STM32F4xx | STM32F401CC / F405RG / F407VG / ZG … | 0x08000000 |
| HDSC 小华半导体 | HC32F460 | HC32F460JETA / KETA / PETB（256K/512K） | 0x00000000 |
| HDSC 小华半导体 | HC32F4A0 | HC32F4A0SGTB（1M）/ SITB（2M）… | 0x00000000 |
| WCH 沁恒 | CH32F203/205/207/208 | CH32F203C8 / CB / RC … | 0x08000000 |

> CH32V 系列（V003/V307 等）是 RISC-V 内核，调试口是沁恒自家的单线 SDI，
> **标准 CMSIS-DAP 无法访问**，不在本工具支持范围内。

## 使用

1. 插入 DAPLink 探针，点「刷新」，在下拉框选中探针。
   「速度」是 SWD 时钟，单位 kHz：默认 1000，**上限 10000**，可下拉也可手填。杜邦线长、信号差时降到 100~500；实测超过 1 MHz 后速率基本不再提升（瓶颈在探针的 HID 传输，不在 SWD 时钟）。
2. 选厂商 → 系列 → 型号（选完会显示 Flash/RAM 容量和起始地址）。
3. 选固件：`.hex` / `.bin` / `.elf` / `.axf`。
   - HEX / ELF 用文件里自带的地址；
   - BIN 用「BIN 起始地址」框里的地址（切换型号时自动填该芯片的 Flash 基址）。
4. 按需勾选「全片擦除」「回读校验」「下载后复位运行」，点「开始下载」。

日志区会打印连接信息（含 IDCODE）、Flash 容量、固件段数与地址范围、擦写与校验结果，可保存成文件。

## 从源码运行

```bat
python -m venv .venv
.venv\Scripts\pip install pyocd pyusb libusb hidapi PySide6 pyinstaller
.venv\Scripts\python tools\gen_chips.py     :: 仅在新增/更新器件包时需要
.venv\Scripts\python run.py
```

## 打包

```bat
.venv\Scripts\pyinstaller.exe --noconfirm --clean build\DAPLinkFlasher.spec
```

产物 `dist\DAPLinkFlasher.exe`（单文件，器件包已内嵌，目标机不需装 Python 或 Keil）。

## 加新芯片

1. 用 Keil Pack Installer 装对应厂商的 DFP（或手动解压到 `%LOCALAPPDATA%\Arm\Packs`）。
2. 在 `tools/gen_chips.py` 的 `PACKS` 里加一行：包键 → (厂商目录, 包名, 界面显示名)。
3. 跑 `python tools/gen_chips.py`，会重新生成 `app/targets/packs/` 与 `chips.json`。
4. 重新打包。

## 目录结构

```
app/
  main.py           入口
  core/
    chips.py        型号库 + 器件包注册
    firmware.py     HEX/BIN/ELF 解析与地址越界检查
    worker.py       连接、擦除、写入、回读校验（独立线程）
    paths.py        源码/打包两种运行方式的路径解析
  ui/               界面与样式
  targets/          器件包（pdsc + FLM）与 chips.json
tools/
  gen_chips.py      从 Keil 器件包生成型号库
  selftest.py       离线自检：型号注册 + 算法解析
  smoke_test.py     无界面冒烟测试
  cancel_test.py    中止逻辑（离线）
  hw_test.py        真机：备份 / 烧录 / 恢复
build/              PyInstaller 配置
```

## 实现要点

- **连接**：pyOCD 的 CMSIS-DAP 后端，SWD，时钟由界面「速度」控制（默认 1 MHz，上限 10 MHz），连接模式 halt。
- **速率实测**（HC32F4A0 + XV-Link）：1 MHz 读 54 KB/s、写约 25 KB/s；4~10 MHz 无提升（HID 64 字节包限制）。
- **擦写**：`FlashLoader`（芯片算法在 RAM 中执行）。全片擦除用 `FlashEraser`，按扇区擦除由 `FlashLoader` 自动处理。
- **分块提交**：每 32 KB 重新初始化一次算法。一次性提交整片（1 MB）会让 HC32 的算法卡死，实测第 900 KB 左右超时；块也负责给中止提供检查点。
- **降速重试**：某一块写入失败时，自动降到当前速度的一半（最低 100 kHz）重连并重试一次；界面上「速度」框会同步显示实际在用的值。
- **中止**：`FlashLoader` 的进度回调每写完一页触发一次，就在回调里查中止标志并抛异常。因此中止在页边界生效（1 MB 镜像实测 1.5 s 内停下），不用等整个块写完。中止后会话不可信，程序主动断开连接，再点「开始下载」会自动重连。
- **校验**：烧完按 4 KB 分块回读，与解析出的固件数据逐字节比对，报第一个不一致的地址。
- **越界保护**：写入前检查所有数据段是否落在该型号的主 Flash 区间内，越界直接拒绝，不碰目标机。
- **内核核对**：连接后读 CPUID，与所选系列应有的内核比对，型号选错时直接给警告。

## 实测记录

在 HC32F4A0SGTB（1 MB Flash，XV-Link CMSIS-DAP 探针）上跑通：

| 项目 | 结果 |
|---|---|
| 整片读取 1 MB | 18.8 s |
| 1 KB 写入 + 回读校验 | 0.2 s，通过 |
| 全片擦除 + 写 1 MB + 校验 | 70.3 s，通过 |
| 写入前备份、测试后恢复 | 整片逐字节比对差异 0 |
| 写 256 KB 中途点中止 | 1.5 s 内停下，会话自动断开 |
| 中止后立刻再下载（不手动重连） | 自动重连，写入 + 校验通过 |

STM32 / CH32 目前只做了离线验证（型号注册、算法解析、固件解析全部通过），**尚未在真实板卡上烧录**。

## 验证脚本

| 脚本 | 用途 | 需要硬件 |
|---|---|---|
| `tools/selftest.py` | 275 个型号注册 + 17 个 FLM 解析 | 否 |
| `tools/smoke_test.py` | 芯片查询、固件解析、窗口构建 | 否 |
| `tools/ui_flow_test.py` | 无目标板时点连接，检查状态复位 | 否 |
| `tools/cancel_test.py` | 中止时机 + 中止标志不残留 | 否 |
| `tools/cancel_thread_test.py` | 跨线程中止：直连 vs 队列连接对比 | 否 |
| `tools/hw_test.py` | 备份 → 烧录 → 校验 → 恢复 | 是 |
| `tools/hw_cancel_test.py` | 真机中止 → 再下载 → 恢复 | 是 |

### HC32 器件包的一个坑

HDSC 的 PDSC 给烧录算法只声明了 `RAMsize="0x4000"`（16 KB）。pyOCD 要在这 16 KB 里同时放算法本体（约 1.5 KB）、两个页缓冲（各 1 KB）和栈，栈只剩 12800 字节，大镜像写入必超时。`tools/gen_chips.py` 在生成精简包时会删掉算法元素上的 `RAMstart/RAMsize`，让 pyOCD 改用整块 IRAM（512 KB），问题消失。

