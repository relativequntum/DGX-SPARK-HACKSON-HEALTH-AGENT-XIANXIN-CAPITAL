# -*- coding: utf-8 -*-
"""阶段三 · 面部与身体观察通道（face_body）。

视频 → MediaPipe 面部 478 点 + 52 个 blendshape + 姿态 33 点 → 头姿、目光偏离、眨眼、
面部动作单元（AU）近似、坐姿与小动作，按时间窗输出。只记录可观察量：
不做人脸识别（身份）、不做表情或情绪分类（apps/emotion/research/决策记录.md 第 11、12 条）。
"""
