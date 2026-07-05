"""
运行时完整性校验模块
=====================
对自身的 SHA256 进行校验，检测文件是否被篡改。
由 Q_main_window.py 在启动时显式调用，不自动执行。
"""

import hashlib
import os
import sys


def _get_exe_path() -> str | None:
    """获取当前 .exe 路径"""
    if getattr(sys, 'frozen', False):
        return sys.executable
    return os.path.abspath(sys.argv[0]) if sys.argv else None


def verify_integrity(expected_sha256: str | None = None) -> bool:
    """
    校验自身 .exe 文件的 SHA256。
    如果不传 expected_sha256, 则从模块属性 _EXPECTED_SHA256 读取。
    如果两者都为空, 跳过校验 (开发模式)。
    """
    exe_path = _get_exe_path()
    if not exe_path or not os.path.exists(exe_path):
        return True

    expected = expected_sha256 or getattr(
        sys.modules[__name__], '_EXPECTED_SHA256', None
    )
    if expected is None:
        return True  # 开发模式: 没有预设值, 跳过

    try:
        h = hashlib.sha256()
        with open(exe_path, 'rb') as f:
            while chunk := f.read(65536):
                h.update(chunk)
        actual = h.hexdigest()
        return actual == expected
    except Exception:
        return True  # 校验失败不阻塞运行
