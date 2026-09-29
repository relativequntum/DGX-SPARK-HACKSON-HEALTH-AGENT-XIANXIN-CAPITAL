# -*- coding: utf-8 -*-
"""doctor_service.py 的接口测试：开发机上跑（需要 fastapi、httpx、pytest；和阶段三对照的那条还要 numpy），不连 Spark。

    python -m pytest apps/multimodal/deploy/livetalking/tests -q

doctor_service 是单文件脚本、不是包：把它所在目录和仓库根加进 sys.path 再 import。
每个测试把数据目录指到 tmp_path，并把 LiveTalking 在线会话查询换成空表——
开发机的 8010 可能正转发着 Spark，测试绝不能碰真实服务。
"""
import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_ROOT = _HERE.parents[4]
for p in (str(_HERE.parent), str(_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import doctor_service  # noqa: E402


@pytest.fixture
def ds(tmp_path, monkeypatch):
    dirs = {name: tmp_path / name for name in ("rec", "judge", "obs")}
    for d in dirs.values():
        d.mkdir()
    monkeypatch.setattr(doctor_service, "RECORD_DIR", str(dirs["rec"]))
    monkeypatch.setattr(doctor_service, "JUDGE_DIR", str(dirs["judge"]))
    monkeypatch.setattr(doctor_service, "OBS_DIR", str(dirs["obs"]))
    monkeypatch.setattr(doctor_service, "_lt_sessions", lambda: {})
    monkeypatch.delenv("DOCTOR_OBSERVE", raising=False)
    return doctor_service, dirs
