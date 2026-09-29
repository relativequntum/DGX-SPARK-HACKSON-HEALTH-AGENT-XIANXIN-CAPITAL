# -*- coding: utf-8 -*-
"""让 `from apps.emotion.face_body import ...` 在任何工作目录下都能 import：把仓库根加进 sys.path。"""
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
