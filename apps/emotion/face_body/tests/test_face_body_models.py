# -*- coding: utf-8 -*-
import hashlib

import pytest

from apps.emotion.face_body import models as M


def test_registry_points_to_official_urls_with_sha256():
    assert set(M.MODELS) == {"face", "pose"}
    for spec in M.MODELS.values():
        assert spec.url.startswith("https://storage.googleapis.com/mediapipe-models/")
        assert spec.url.endswith("/" + spec.filename)
        assert len(spec.sha256) == 64


def test_default_model_dir_honours_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FACE_BODY_MODEL_DIR", str(tmp_path))
    assert M.default_model_dir() == tmp_path
    monkeypatch.delenv("FACE_BODY_MODEL_DIR")
    assert M.default_model_dir().name == "models"


def test_ensure_models_returns_paths_when_files_present(tmp_path):
    for spec in M.MODELS.values():
        (tmp_path / spec.filename).write_bytes(b"x")
    paths = M.ensure_models(tmp_path)
    assert paths["face"].name == "face_landmarker.task" and paths["pose"].name == "pose_landmarker_full.task"


def test_ensure_models_missing_explains_how_to_fetch(tmp_path):
    with pytest.raises(FileNotFoundError) as info:
        M.ensure_models(tmp_path)
    assert "fetch-models" in str(info.value)


def _fake_registry(payload):
    return {k: M.ModelSpec(s.filename, s.url, hashlib.sha256(payload[s.filename]).hexdigest())
            for k, s in M.MODELS.items()}


def test_fetch_verifies_checksum_and_skips_files_already_good(tmp_path, monkeypatch):
    payload = {s.filename: b"model-bytes-" + s.filename.encode() for s in M.MODELS.values()}
    monkeypatch.setattr(M, "MODELS", _fake_registry(payload))
    calls = []

    def fake_download(url, dest, proxy=None, timeout=120):
        calls.append((url, proxy))
        dest.write_bytes(payload[dest.name.removesuffix(".part")])

    monkeypatch.setattr(M, "_download", fake_download)
    M.fetch_models(tmp_path, proxy="http://p:1")
    assert len(calls) == 2 and calls[0][1] == "http://p:1"
    M.fetch_models(tmp_path)  # 已存在且校验通过：不再下载
    assert len(calls) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(payload)


def test_fetch_rejects_checksum_mismatch_and_leaves_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "_download", lambda url, dest, proxy=None, timeout=120: dest.write_bytes(b"tampered"))
    with pytest.raises(ValueError):
        M.fetch_models(tmp_path)
    assert not any(tmp_path.iterdir())


def test_load_models_checks_sha256_of_the_bytes_it_returns(tmp_path, monkeypatch):
    payload = {s.filename: b"model-bytes-" + s.filename.encode() for s in M.MODELS.values()}
    monkeypatch.setattr(M, "MODELS", _fake_registry(payload))
    for name, data in payload.items():
        (tmp_path / name).write_bytes(data)
    assert M.load_models(tmp_path) == {k: payload[s.filename] for k, s in M.MODELS.items()}
    (tmp_path / M.MODELS["pose"].filename).write_bytes(b"tampered")  # 例如下载中断后留下的半个文件
    with pytest.raises(ValueError) as info:
        M.load_models(tmp_path)
    assert "fetch-models" in str(info.value)
