# -*- coding: utf-8 -*-
"""让 `from apps.emotion.judge import ...` 在任何工作目录下都能 import：把仓库根加进 sys.path。
apps/ 与 apps/emotion/ 没有 __init__.py，按 PEP 420 命名空间包处理。"""
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
