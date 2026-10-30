# -*- coding: utf-8 -*-
"""路径解析：兼容源码运行与 PyInstaller 打包后的单文件运行。"""
import os
import sys


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_dir() -> str:
    """app 包所在目录（打包后指向解包出来的临时目录）。"""
    if is_frozen():
        return os.path.join(getattr(sys, "_MEIPASS"), "app")
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def targets_dir() -> str:
    return os.path.join(app_dir(), "targets")


def packs_dir() -> str:
    return os.path.join(targets_dir(), "packs")


def chips_json() -> str:
    return os.path.join(targets_dir(), "chips.json")


def log_dir() -> str:
    """日志放在 exe 同目录，便于现场排查。"""
    if is_frozen():
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    d = os.path.join(base, "logs")
    os.makedirs(d, exist_ok=True)
    return d
