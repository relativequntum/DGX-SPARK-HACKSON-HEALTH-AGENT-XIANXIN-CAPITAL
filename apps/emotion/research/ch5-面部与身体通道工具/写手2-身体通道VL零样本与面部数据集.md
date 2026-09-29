## 第5章 情绪采集 · 面部与身体通道工具 · 身体通道、VL 零样本与面部数据集

核实日期：2026-09-14（第 2 版，按第 1 轮审查意见修订）。Stars 取自 GitHub API 当日值（只记数量级），"最近推送"取 API `pushed_at`；早于 2025-03-14 的标"停更风险"。PyPI 数据取自 JSON API。aarch64 + CUDA 13 一栏只写有页面证据的结论。许可一栏统一按「商用友好 / 需替换 / 仅研究用途」标注。

### 一览表

| 名称 | 类型 | 一句话 | Stars 与活跃度 | 许可 | aarch64 + CUDA 13 | 中文 | 对应通道或组件 | 推荐等级 |
|---|---|---|---|---|---|---|---|---|
| MediaPipe Pose Landmarker | 工具 | 33 关键点（2D + 米制世界坐标 + 可见度），`num_poses` 可设多人，CPU 即可实时 | ~37k；推送 2026-09-11；PyPI 1.0.1（2026-08-14） | 商用友好（Apache-2.0，模型卡同） | 可：PyPI 官方 `manylinux_2_28_aarch64` wheel（CPU 推理） | 语言无关 | 身体（坐姿 / 坐立不安） | A |
| rtmlib + RTMPose（OpenMMLab） | 工具 | 无 mmcv 依赖的 RTMPose / RTMO / RTMW ONNX 推理，17 / 26 / 133 点（含手指） | rtmlib ~0.7k，推送 2026-08-03，PyPI 0.0.16（2026-08-04）；mmpose ~7.9k，推送 2025-08-04 | 商用友好（Apache-2.0） | 可：纯 Python + onnxruntime-gpu（aarch64 wheel，1.27 起默认 CUDA 13）；注意其依赖钉的是 CPU 版 `onnxruntime`，须 `--no-deps` 安装 | 语言无关 | 身体（含手部小动作）、多人场景 | A |
| Ultralytics YOLO26-pose | 工具 | 唯一有厂商官方 DGX Spark 部署文档与 arm64 镜像的检测 + 姿态一体模型 | ~62k；推送 2026-09-13 | 需替换（AGPL-3.0，内部使用亦适用） | 可：官方 `latest-nvidia-arm64` 镜像（PyTorch 26.08 / CUDA 13.4 / TensorRT 11）+ 原生 pip 路径 | 语言无关 | 身体；开赛前"环境冒烟测试"基线 | B |
| ViTPose / ViTPose++（HF transformers 移植） | 模型 | 精度最高的自顶向下 17 点姿态，纯 PyTorch | 原仓库 ~2.1k，推送 2025-12-25 | 商用友好（Apache-2.0） | 可：纯 PyTorch（cu130 aarch64 wheel），需外接检测器 | 语言无关 | 身体（精度备选） | C |
| CODY 运动学特征包（Cif 等 2026） | 工具 + 论文 | 门诊视频 → YOLOv8-pose → 每窗 22 × 17 = 374 项可解释运动学描述子 | 0 star；推送 2026-09-04；论文 T2 | 商用友好（MIT） | 可：核心为 numpy / pandas / sklearn / xgboost / lightgbm / torch；YOLO 提取只在可选 notebook | 语言无关 | 身体特征 → MSE"精神运动性活动" | B |
| AutoFidgetDetection（Lin 等 FG 2020 / TAFFC 2023） | 工具 + 论文 | 从全身视频自动检测自适应动作 / 坐立不安 | 9 star；推送 2020-08-28（停更风险） | 商用友好（MIT） | 否：依赖 OpenPose 旧栈 | 语言无关 | 身体（只借鉴定义） | C |
| facetorch（互引写手 1 条目） | 工具 | RetinaFace + OpenGraphAU Swin-B + 3D 对齐打包成 TorchScript，README 自述 CUDA 13.0 已验证、ARM 为实验性 | ~0.6k；推送 2026-09-10；PyPI 稳定 0.6.2（2026-04-17）/ 预发布 1.0.0rc3（2026-09-03） | 商用友好（Apache-2.0；内置 RetinaFace / 3D 对齐权重为 MIT） | 可行待验：`py3-none-any` 轮子、无 ONNX 依赖、torch ≥2.6 <2.14；README 写「Linux x86-64 为正式平台，ARM 为 experimental」 | 语言无关 | 面部 AU（写手 1）；本章借其 3D 对齐 / 头姿输出做"头部位移"辅助特征 | B |
| Qwen3.5 系列（原生视觉，如 Qwen3.5-35B-A3B） | 模型 | README 里的"Qwen3.5-VL"实为 Qwen3.5 原生多模态，支持图像 + 视频（默认 2 fps 抽帧） | Qwen3.8 仓库 ~4.1k（承载 3.5 / 3.6 / 3.8 说明） | 商用友好（Apache-2.0） | 可（第 4 章验证 vLLM / SGLang / llama.cpp） | 是 | 观察通道的"归纳器"而非"探测器"；言语内容 → MSE 条目 | B |
| Step 3.7 Flash | 模型 | 198B MoE（激活 ~11B），1.8B 视觉编码器，只收图像不收视频 | ~0.3k；README 有 DGX Spark llama.cpp 构建段 | 商用友好（Apache-2.0） | 可：GGUF Q4 约 102–112 GB，基本占满一台 | 是 | 大脑 / 报告；观察通道只能喂抽帧 | B |
| VL 零样本可靠性证据包（FaceXBench、GPT4Affectivity、ActFER、Zhang ACL 2026、Eyes on VLM、Licht 2026） | 论文 / 基准 | 回答"纯 VL 能否替代专用 AU / 目光 / 头姿工具"——结论是不能 | facexbench 19 star（MIT）；GPT4Affectivity 26 star（无许可） | — | — | — | 面部 + 目光 + 头姿路线决策 | C（只借鉴） |
| DISFA / DISFA+ | 数据集 | 27 人自发表情立体视频，逐帧 AU 强度 0–5，66 点 | 网页在线；协议表单 | 仅研究用途 | — | 多族裔，非中国面孔专集 | AU 工具"构建正确性"校验 | B |
| FEAFA+（国科大） | 数据集 | 154 段 / 230,184 帧，23 类 AU / AD 连续强度 0–1；其中 27 段为 DISFA 重标 | 网页在线；邮件 + 签协议 | 仅研究用途（明文禁商用） | — | 127 段摆拍为国科大自采（族裔未标注）；27 段自发为 DISFA（多族裔） | AU 工具在东亚面孔上的补充校验（仅摆拍部分成立） | B |
| CAS(ME)3（中科院心理所） | 数据集 | ~80 小时 RGB-D 自发表情视频，1,109 微表情 + 3,490 宏表情人工标注，样例标注含 AU | GitHub 镜像页在线；协议 PDF 已读 | 仅研究用途（协议明文「严禁任何商业用途」） | — | 中科院心理所采集（族裔页面未标注） | AU 工具在中国面孔上的校验 | B |
| BP4D / BP4D+ | 数据集 | 41 / 140 人自发表情，FACS 编码，2.6 TB / >10 TB | 网页在线；机构签字 | 仅研究用途（商用另与 TTO 谈） | — | 多族裔（BP4D 含 11 名亚裔） | AU 工具校验（体量过大） | C |
| Aff-Wild2 | 数据集 | 564 段野外视频 2.8M 帧 554 人，12 个 AU + 7 类表情 + VA | 网页在线；EULA 约 14 天 | 仅研究用途（企业可申请） | — | 混合 | AU 野外鲁棒性校验 | C |
| CK+ ／ AFEW / SFEW | 数据集 | CK+：摆拍 + FACS 码；AFEW / SFEW：电影片段 7 类情绪标签 | CK+ 门户在线；AFEW 页面停在 2013 | 仅研究用途（CK+ 明文禁商用；AFEW EULA） | — | — | CK+ 冒烟测试；AFEW 为情绪标签集与铁律冲突 | C ／ D |
| deface | 工具 | 视频人脸检测 + 模糊 / 马赛克 / 涂黑，默认丢音轨 | ~1.6k；推送 2024-10-13；PyPI 1.5.0（2023-10-15）——超 18 个月，停更风险 | 商用友好（MIT） | 可：CenterFace ONNX；GPU 需手动装 onnxruntime-gpu | 语言无关 | 隐私：演示素材与评测集脱敏 | B |
| face_anon_simple（WACV 2025） | 工具 | 扩散模型换脸式匿名化，保留表情 / 头姿 / 目光 | ~0.2k；推送 2026-05-07 | 需替换（AGPL-3.0） | 可行但重（PyTorch 扩散） | 语言无关 | 隐私：需保留表情的演示 | C |
| "只存特征"管线参照：OpenDBM（AiCure）+ Reading Between the Frames（ECIR 2024） | 工具 | 前者是视频 / 音频 → 数字生物标志物变量表；后者是 MediaPipe + MPIIGaze + InstBlink + EmoNet + PASE+ 的多模态特征管线 | OpenDBM 72 star，推送 2023-02-10（停更风险）；RBF 94 star，推送 2026-06-02 | OpenDBM 需替换（AGPL-3.0）；RBF 仅研究用途（CC BY-NC-ND 4.0） | OpenDBM 否（OpenFace 走 x86 Docker）；RBF 各组件多为纯 Python | 英文语音链路 | 只借鉴变量定义与"只存特征"布局 | C |

### 逐项说明

#### 1. MediaPipe Pose Landmarker（google-ai-edge/mediapipe）
- URL：https://github.com/google-ai-edge/mediapipe ；PyPI https://pypi.org/project/mediapipe/ ；文档 https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker （Python 指南 …/pose_landmarker/python）；模型卡 https://storage.googleapis.com/mediapipe-assets/Model%20Card%20BlazePose%20GHUM%203D.pdf
- 做什么：33 个身体关键点，lite / full / heavy 三档（检测器输入 224×224，关键点器 256×256，float16），IMAGE / VIDEO / LIVE_STREAM 三种模式。配置项 `num_poses`（"the maximum number of poses that can be detected"，默认 1，整数 >0）——**不是**只能单人：多人时可同时输出多组关键点，模型卡里的"单人"限制指底层模型本身。
- 怎么装：`pip install "mediapipe>=1.0.0"`。PyPI 1.0.1（2026-08-14）直接提供 `manylinux_2_28_aarch64` wheel（Python 3.9–3.12），是本次核实中最干净的 aarch64 证据。版本要钉：审查方核对 PyPI 历史，0.10.5–0.10.18 有 cp38–cp312 的 `manylinux2014_aarch64` 轮子，0.10.20–0.10.35 一个都没有，1.0.0（2026-07-27）起改为 `py3-none-manylinux_2_28_aarch64`。Python 文档未提 Linux 下 GPU delegate，按 CPU 推理规划。
- 输出：每点归一化 x / y / z + visibility + presence；另有以髋中点为原点、单位为米的 world landmarks。只输出坐标，不输出任何标签。
- 具体用法：身体通道唯一要做的"坐姿 / 坐立不安"一条。用 world landmarks 的肩、髋、腕、膝序列做滑窗统计（位移标准差、姿势切换次数、腕部速度峰计数），落成 MSE"行为 / 精神运动性活动"条目的观察句，例如"访谈 8 分钟内变换坐姿 6 次、双手小幅动作占比 35%（阈值待博士定）"。咨询师入镜时设 `num_poses=2`，按框位置（画面哪一侧、面积）选来访者那一组，比先裁剪画面省事。模型卡明文写"监控或身份识别不在范围内""不用于人命攸关决策"，与铁律一致，可在 SKILL.md 里引用。
- 风险：小幅度动作（约 <1.5 cm）在 2D 工具上信度很低（见第 5 条 Koul & Novembre 2025），阈值不能设得太细；Linux GPU 加速未确认（不影响结论）。
- 替代品：rtmlib（多人 / 含手指）、YOLO26-pose。

#### 2. rtmlib + RTMPose（Tau-J/rtmlib；open-mmlab/mmpose）
- URL：https://github.com/Tau-J/rtmlib ；PyPI https://pypi.org/project/rtmlib/ ；https://github.com/open-mmlab/mmpose/tree/main/projects/rtmpose ；onnxruntime-gpu https://pypi.org/project/onnxruntime-gpu/ ；ORT CUDA 版本表 https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html
- 做什么：不依赖 mmcv / mmpose 的 RTMPose、RTMO（一阶段多人）、DWPose、RTMW（133 点全身含手指，有 3D 变体）、ViTPose 的 ONNX 推理；后端 onnxruntime / opencv / openvino / tensorrt（可选）。RTMPose-m 官方数字：COCO 75.8 AP，i7-11700 CPU 上 90+ FPS。
- 怎么装：rtmlib 0.0.16 的 `requires_dist` 是 `numpy, onnxruntime, opencv-contrib-python, opencv-python, tqdm`——钉的是 **CPU 版 `onnxruntime`**，它与 `onnxruntime-gpu` 提供同名模块、共存会冲突。正确顺序：`pip install rtmlib --no-deps`，再 `pip install numpy opencv-python opencv-contrib-python tqdm onnxruntime-gpu`（或装完后 `pip uninstall onnxruntime`）。onnxruntime-gpu 1.30.0（2026-09-10）在 PyPI 提供 aarch64 wheel，官方文档写明 1.27 起 PyPI GPU 包默认按 CUDA 13.0 构建；Ultralytics 的 DGX Spark 指南也直接 `pip install onnxruntime-gpu`。rtmlib 会自动从 OpenMMLab 服务器下载 ONNX 模型，离线部署要在联网时先跑一次把模型缓存下来。
- 输出：关键点坐标 + 置信度（17 点 COCO / 26 点 Halpe26 含足 / 133 点含手与脸轮廓）。
- 具体用法：与 MediaPipe 二选一。优势是 RTMW 133 点带手指，能把"搓手、抠指甲、摸脸"这类自适应动作（self-adaptors，见第 5 条）量化成腕—面距离与手指速度；RTMO 可处理咨询师入镜的双人画面。Rode 等 2025（Sci Rep，11 个开源单目估计器 vs 光学动捕，25 名健康被试）原文："The measured 2D MPJPE ranged from 72 to 122 mm"，"RTMPose 'Performance' was the most accurate direct 2D pose estimator with a 2D MPJPE of 72 mm"，"The inference speed varied from 25 to 200 FPS"。
- 风险：mmpose 主仓库最近推送 2025-08-04，未过 18 个月线但节奏明显放慢；rtmlib 为单作者维护；TensorRT 后端在 CUDA 13 上需自行验证；依赖冲突见上。
- 替代品：MediaPipe（更省事）、YOLO26-pose（官方 Spark 文档）。

#### 3. Ultralytics YOLO26-pose
- URL：https://github.com/ultralytics/ultralytics ；DGX Spark 指南 https://docs.ultralytics.com/guides/nvidia-dgx-spark ；姿态任务 https://docs.ultralytics.com/tasks/pose/ ；许可 https://www.ultralytics.com/license
- 做什么：检测 + 17 点姿态一体，YOLO26n-pose mAP50-95 57.2 到 YOLO26x-pose 71.6。
- 怎么装：官方指南（创建于 2026-01-09）给出两条路——Docker `ultralytics/ultralytics:latest-nvidia-arm64`（内含 NVIDIA PyTorch 26.08、CUDA 13.4、TensorRT 11）；或原生 `pip install ultralytics` + `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130` + `pip install onnxruntime-gpu`。指南实测 YOLO11n 在 DGX Spark 上 PyTorch 2.67 ms / TensorRT FP16 1.01 ms。这是本次核实里唯一一份"厂商官方写给 DGX Spark 的姿态相关部署文档"。
- 输出：每人 box + 17 个 `[x, y, visible]`。
- 具体用法：开赛前一周（9/15–9/19）先用它跑通"摄像头 → 关键点 → 帧率"冒烟测试，确认 CUDA 13 + TensorRT 链路正常，再决定正式管线用 MediaPipe 还是 rtmlib；若最终就用它，特征层复用第 4 条 CODY 的描述子。
- 风险：AGPL-3.0，官方许可页原话"even if you use YOLO only internally or for R&D"，衍生整套应用须开源；黑客松作品本就开源可接受，但商业化必须换掉或购买企业许可——表里标"需替换"。
- 替代品：rtmlib（Apache-2.0）。

#### 4. CODY——门诊视频运动学描述子（Cif 等 2026）
- URL：https://github.com/xaviervasques/CODY ；论文 arXiv https://arxiv.org/abs/2602.00163 ，期刊版 *Annals of Clinical and Translational Neurology* 2026，DOI 10.1002/acn3.70474（"Deep Learning Pose Estimation for Phenotyping of Co-Occurring Hyperkinetic Movement Disorders"，T2）；数据 Zenodo concept DOI 10.5281/zenodo.22232609
- 做什么：用 `yolov8x-pose-p6` 从智能手机门诊视频（1920×1080，≥30 fps，含静坐、保持姿势等任务）取 COCO-17 点，每窗计算 22 类可解释特征 × 17 点 = 374 维：姿势偏置（均值位移）、幅度（极值 / 范围）、变异（SD / IQR）、节律（FFT 峰频与幅值）、方向性（导数变号次数）、不规则性（Higuchi 分形维、排列熵）。21 名患者 + 4 名对照 = 25 人，多标签 macro-AUPRC 0.717 ± 0.030。
- 怎么装：MIT。README 的 `requirements.txt` 只有 numpy / pandas / sklearn / xgboost / lightgbm / torch / openpyxl（全部纯 Python，aarch64 无障碍）；YOLOv8-Pose 提取只在可选 notebook，另用 `requirements-extraction.txt`（ultralytics，见第 3 条的 AGPL 提示）。核心管线输入是 Excel：`From` / `To` 窗口列 + 二元症状列 + 若干 `*_distance` 时间序列列。0 star、2026-09-04 刚推送，是论文配套代码而非成熟库。
- 输出：特征表（不是标签）。
- 具体用法：目前找到的最接近"坐着的人 + 门诊 + 可解释运动学"的开源实现。不必整体拿来，把六族特征定义抄成我们 `scripts/body_features.py` 的规格（每 10 秒窗：躯干偏置、腕部范围、腕部速度 SD、FFT 峰频 ≥2 Hz 记为节律性小动作），关键点来源换成第 1 / 2 条，输出给博士定阈值，落 MSE"精神运动性活动：正常 / 增多 / 减少"三档观察。
- 风险：面向运动障碍而非精神科；样本 25 人；未在坐立不安上验证。
- 替代品：自己写（约百行 numpy），配合第 5 条的证据定阈值。

#### 5. 精神运动性迟滞 / 激越的视频估计：论文证据（无可直接用的开源引擎）
- Ouyang 等 2024，*Child and Adolescent Psychiatry and Mental Health*，DOI 10.1186/s13034-024-00749-5，https://pmc.ncbi.nlm.nih.gov/articles/PMC11131256/ ：门诊室**坐姿**、1280×720、30 Hz、取前 4 分钟，OpenPose 提 11 项骨骼长度 / 角度并做滑窗方差；48 名 ADHD 儿童 vs 48 对照，单独"大腿角方差"AUC 94.0%，随机森林组合 AUC 95.2%。无代码、无数据。意义：证明"坐姿视频 + 关节角滑窗方差"这条最简单的路在临床场景有效，且提示摄像头必须框到膝盖（腿部抖动是最强信号）。
- Kacem, Hammal, Daoudi, Cohn，FG 2018，https://pmc.ncbi.nlm.nih.gov/articles/PMC6157749/ ：49 个面部点与头部 pitch / yaw / roll 的速度、加速度，49 人 126 次访谈，三档抑郁严重度 70.8%（头动单独 61.4%）。无代码。意义：头部运动动力学是 MSE"精神运动性"的合理观察量，可由面部通道的头姿输出（或第 6 条 facetorch 的 3D 对齐头）顺带计算。
- Koul & Novembre 2025，*Behavior Research Methods*，DOI 10.3758/s13428-024-02546-6，https://pmc.ncbi.nlm.nih.gov/articles/PMC11695451/ ：46 人自发动作对比 Vicon，OpenPose 相关系数在 <0.29 cm 时 0.12、1.51–10.15 cm 时 0.56、>10.15 cm 时 0.75；头部最好（中位 r 0.63），肩 0.34–0.36、肘 0.34–0.37 最差。意义：坐立不安里的"小幅度"动作 2D 工具基本测不准，阈值只能设在厘米级以上、以"次数 / 占比"而非"毫米"报告。
- Rode 等 2025，*Scientific Reports*，DOI 10.1038/s41598-025-22626-7，https://pmc.ncbi.nlm.nih.gov/articles/PMC12589393/ ：11 个开源单目估计器对比光学动捕（25 名健康被试）；直接 2D 估计器 MPJPE 72–122 mm、25–200 FPS，RTMPose 最准（72 mm）；原文对临床用途的提醒是"monocular methods are less accurate in depth and more sensitive to self-occlusions compared to multidirectional methods"——所以我们只用 2D 量、摆机位减少自遮挡。
- Lin, Orton 等：会议版 "Automatic Detection of Self-Adaptors for Psychological Distress"，FG 2020，DOI 10.1109/FG47880.2020.00032；期刊版 "Looking at the Body: Automatic Analysis of Body Gestures and Self-Adaptors in Psychological Distress"，*IEEE Transactions on Affective Computing* 14(2)，2023，DOI 10.1109/TAFFC.2021.3101698（预印本 arXiv 2007.15815；Crossref 核实）。定义 self-adaptors / fidgeting 与自报焦虑抑郁相关；代码 https://github.com/LinWeizheDragon/AutoFidgetDetection （MIT，9 star，推送 2020-08-28，依赖 OpenPose，aarch64 + CUDA 13 不可行）。只借鉴其"节律性手 / 腿动作 = fidgeting"的操作定义。
- Boutaleb 等 2026，arXiv 2601.19526：单目视频 3D 步态量化 MDD 精神运动性迟滞（PMR 检出 83.3%），无代码、步态场景与坐姿不符，仅作文献。
- 结论：没有"拿来即用"的精神运动性估计引擎；路线 = 关键点工具（第 1 / 2 条）+ CODY 特征族（第 4 条）+ 上述阈值证据 + 博士定档。

#### 6. facetorch（互引写手 1 条目；本章只用其 3D 对齐 / 头姿输出）
- URL：https://github.com/tomas-gajarsky/facetorch ；PyPI https://pypi.org/project/facetorch/
- 做什么：把 RetinaFace 检测（27.3M，MIT）、OpenGraphAU Swin-B 动作单元头（94M，Apache-2.0；OpenGraphAU 体系为 41 个 AU）、MobileNetV2 3D 人脸对齐（4.1M，MIT）以及 FER / VA / deepfake / 嵌入头打包成 Hydra 配置 + TorchScript 的一条龙推理；带 CPU / GPU Docker 镜像。
- 怎么装：两条线并存——PyPI 稳定版 0.6.2（2026-04-17）钉 `torch<2.4`，装不上 cu130 的新 torch；预发布 1.0.0rc3（2026-09-03）改为 `torch>=2.6,<2.14`、`torchvision>=0.21,<0.29`、Python ≥3.10 <3.12.x，轮子是 `py3-none-any`，requires_dist 无 ONNX、无平台标记。README 原话："Linux x86-64 is the official v1 candidate platform; Windows, macOS, ARM, and Apple MPS are experimental"，验证过的 CUDA 组合为 "CUDA 13.0 with PyTorch 2.6–2.13"。aarch64 上理论上只需 cu130 的 torch aarch64 轮子 + `pip install facetorch==1.0.0rc3`，但 ARM 官方标"实验性"，须在 9/15–9/19 实测。
- 输出：每张脸的 box、AU 多标签、3D 对齐关键点 / 姿态、以及（默认开启的）表情 / 效价唤醒 / 深伪分数。
- 具体用法：面部 AU 部分由写手 1 决策（作为 Day 3 替代接入路径，B）。本章用法是：从其 3D 对齐头拿头部位置 / 姿态序列，计算 Kacem 2018 式的头动速度 / 加速度与"头部位移"统计，与第 1 / 2 条身体关键点的头点互为校验，落 MSE"精神运动性"条目。**必须在 Hydra 配置里禁用 FER / VA / deepfake 头**——铁律不允许情绪标签进管线。
- 风险：ARM 实验性；1.0.0 尚在 rc；OpenGraphAU 训练集含 DISFA / BP4D 等（非商用来源，写手 1 已标）；只在标准人脸数据集上验证过。
- 替代品：面部通道自带的头姿工具（6DRepNet 等，写手 1）；MediaPipe Face Landmarker 的变换矩阵。

#### 7. Qwen3.5 系列（原生多模态；README 中的"Qwen3.5-VL"）
- URL：https://huggingface.co/Qwen/Qwen3.5-35B-A3B ；https://github.com/QwenLM/Qwen3.8 （承载 3.5 / 3.6 / 3.8 全系说明）；旧线 https://github.com/QwenLM/Qwen3-VL （最新动态停在 2025-11）
- 做什么：Qwen3.5-35B-A3B（2026-02-24）是"统一视觉—语言基座"，原生接收图像与视频（默认 2 fps 抽帧，可调），上下文 262K，Apache-2.0；同页列出 Qwen3.6-35B-A3B（2026-04-16）与 Qwen3.8-27B（2026-08-14），团队选型时应确认到底用哪一代。
- 怎么装：SGLang / vLLM / Transformers / llama.cpp（第 4 章负责 aarch64 验证）。
- 输出：自由文本；可用受限 JSON schema 约束成 MSE 条目。
- 具体用法：作为"归纳器"——输入 = 专用工具给出的结构化特征（AU 序列摘要、头姿统计、身体特征表、ASR 转写），输出 = MSE 各条目的观察句与不确定性；不让它直接看视频判 AU / 目光。允许它看抽帧做"外观"条目（衣着整洁度、是否有明显疲态）但必须标"模型描述、待人工确认"。
- 风险：见第 9 条证据包——头姿 / 目光 / 表情零样本不可靠；视频输入 token 成本高，与主 LLM 共存时显存要预算。
- 替代品：Step 3.7 Flash（只能看图）。

#### 8. Step 3.7 Flash（stepfun-ai）
- URL：https://github.com/stepfun-ai/Step-3.7-Flash ；https://huggingface.co/stepfun-ai/Step-3.7-Flash-GGUF
- 做什么：198B 稀疏 MoE、激活约 11B，196B 语言主干 + 1.8B 视觉编码器，256K 上下文，Apache-2.0。README 只写图像 + 文本输入，全文无 "video" 字样。
- 怎么装：vLLM / SGLang / Transformers / llama.cpp；README 有 "Build llama.cpp on DGX-Spark" 段（`-DGGML_CUDA=ON -DGGML_CUDA_GRAPHS=ON -DGGML_CUDA_FORCE_MMQ=ON`），最低 120 GB 统一内存、推荐 128 GB；GGUF Q4_K_S 111.5 GB、IQ4_XS 105 GB、Q3_K_L 102.5 GB，另加 3.97 GB mmproj。
- 输出：文本。
- 具体用法：留在 Spark-A 做问诊 / 报告归纳；观察通道若要它看画面只能抽帧送图。它一旦上机基本占满 Spark-A，感知模型必须全部落在 Spark-B——与 README 分工一致，但意味着"VL 归纳"要么走 Spark-A 的 Step（只看特征表，不看视频），要么 Spark-B 再常驻一个小 Qwen3.5。
- 风险：GitHub 仅 ~338 star，社区经验少；视觉基准偏 GUI / 图表（SimpleVQA 79.2、V* 95.3），无人脸 / 行为类评测。
- 替代品：Qwen3.5-35B-A3B（有视频输入，小得多）。

#### 9. VL 零样本可靠性证据包（决定"专用工具 + VL 归纳"还是"纯 VL"）
- FaceXBench，IEEE T-BIOM，arXiv 2501.10360（v3 2026-01），代码 https://github.com/Kartik-3004/facexbench （MIT，19 star）：5,000 道多选题、25 个数据集、14 项任务、26 个开源 + 2 个闭源模型。相关数字（Table III）：头姿估计 Qwen2-VL-72B 39.25%、InternVL2-76B 34.25%、GPT-4o 27.75%；表情识别 55.75% / 66.25% / 59.25%；作者结论"头姿、低分辨率识别、深伪检测等任务模型普遍吃力"。
- GPT4Affectivity，arXiv 2403.05916（2024-03，含山世光等 15 位作者），代码 https://github.com/EnVision-Research/GPT4Affectivity （26 star，无许可文件，2024-03 停更）：GPT-4V 在 AU 识别与微表情检测上"准确"，在一般表情识别上"很不准"；仓库含 DISFA / CASME II 样例图，可当 prompt 范例来源。
- ActFER，arXiv 2604.08990（v2 2026-08-14）：以 Qwen3-VL-4B 为底，agent 主动调用 InsightFace 检测对齐 + 局部放大工具再推理 AU；DISFA 8 个 AU 零样本平均 F1 58.2，裸 Qwen3-VL-4B 只有 38.1。无代码。意义：同一个小 VL，加上专用工具就从"不可用"到"勉强可用"，正是"专用 AU 工具 + VL 归纳"路线的直接证据。
- Zhang 等，ACL 2026，arXiv 2506.05412（v4 2026-05-30）"VLMs Mistake Head Orientation for Gaze Direction"：1,360 张受控头朝向照片；预实验 111 个 VLM 中 94 个不优于随机；主实验含 GPT-5.2、Qwen3-VL-30B-A3B、GLM-4.6V-Flash 等，均"头朝向主导"；2 / 3 / 4 目标任务人类 94 / 88 / 76%，专用模型 GazeLLE 78 / 67 / 47%，GPT-5.2 64 / 46 / 31%。
- Eyes on VLM，arXiv 2605.19859（2026-05，Idiap Odobez 组）：目光跟随与社交目光基准，"当前 VLM 缺乏精确的目光理解能力"。
- Licht 2026，arXiv 2512.10882（v4 2026-04）：多模态 LLM 打唤醒度分，实验室条件接近人类信度、议会实录只剩中等相关，且几乎所有模型存在系统性性别偏差。
- Teles 等 2025-11-06，*PLOS Mental Health*，DOI 10.1371/journal.pmen.0000488（综述）；谢瑜等 2026《大模型在抑郁症筛查与诊断中的应用》，心理科学进展 34(3): 424–440，DOI 10.3724/SP.J.1042.2026.0424（中文综述）：两篇都把幻觉、群体偏差、隐私列为多模态大模型进入精神卫生场景的主要限制。
- 结论落到设计：AU → 专用工具；头姿 → 专用工具（面部通道已含）；目光接触 → 专用 gaze 工具或降级为"面部朝向摄像头占比"并明示；VL 只做归纳与"外观"描述。任何 VL 直接输出的情绪判断按铁律不进预诊单。

#### 10. DISFA / DISFA+
- URL：https://mohammadmahoor.com/pages/databases/disfa/ （旧路径 `/disfa/` 已 404）；DISFA+ https://mohammadmahoor.com/pages/databases/disfa_plus/
- 内容：27 名成人（12 女 15 男，多族裔）观看情绪视频时的立体视频，1024×768，两位 FACS 编码员逐帧标 AU 强度 0–5，66 点地标；DISFA+ 另含摆拍。
- 获取：在线填协议表单，页面写"面向研究目的分发"，未写商用条款 → 仅研究用途。
- 用法：不是验证"我们场景效度"的数据（非中国面孔、非访谈），而是验证"aarch64 上编译 / 移植的 AU 工具没坏"：跑出的 F1 应接近该工具论文报的 DISFA 数字（ActFER 报的 58.2 是零样本 VL 的参照线）。多数 AU 工具训练集就含 DISFA，属样本内测试，只能查构建正确性。
- 风险：申请周期不可控；9 天内若拿不到，用第 11 / 12 条或自录数据替代。

#### 11. FEAFA+（国科大智能信息处理实验室）
- URL：https://www.iiplab.net/feafa+/ ；论文 SPIE 2022 DOI 10.1117/12.2643588，arXiv 2111.02751
- 内容：**154 段**序列 = 127 段摆拍（99,356 帧；FEAFA 自采，122 名参与者含儿童、青年与老人，真实环境录制，页面未标族裔）+ 27 段自发（130,828 帧；为 **DISFA 重标**，页面写参与者"mainly young adults of various races"）；合计 230,184 帧。标注体系 9 个对称 AU + 10 个单侧 AU + 2 个对称 AD + 2 个单侧 AD = **23 类**（arXiv 摘要写 "24 redefined AUs"，口径不一，以官网为准），每类连续强度 0–1（非 FACS 的 0–5 离散档）。
- 获取：邮件 luk@ucas.ac.cn 附签名协议；官网原话 "any commercial use of the dataset is prohibited"。
- 用法：国内团队申请周期可能比美国数据集短。注意"东亚面孔补充校验"只对 127 段摆拍（99,356 帧）成立，占 57% 的自发部分就是 DISFA；且摆拍段族裔未标注，申请到手后先抽看。它的 0–1 连续强度与 FACS 档位需做单调映射再比较。
- 风险：非标准 FACS 编码，不能与 DISFA 数字直接对表；族裔未核实；摆拍与访谈场景不同。

#### 12. CAS(ME)3（中科院心理所）
- URL：数据库原站 http://casme.psych.ac.cn/casme/e4 （2026-09-14 http / https 连接均被关闭）；GitHub 镜像说明 https://github.com/jingtingEmmaLi/CAS-ME-3 （写明"因服务器问题改由 https://melabipcas.github.io/melab/en/databases.html 申请"）；数据集页 https://melabipcas.github.io/melab/en/db/casme3.html ；协议 PDF https://melabipcas.github.io/melab/assets/pdf/CASME3_License_Agreement_Blank.pdf ；论文 Li 等，*IEEE TPAMI* 2022，DOI 10.1109/TPAMI.2022.3174895（Crossref 核实）；新闻稿 https://www.eurekalert.org/news-releases/952778
- 内容：约 80 小时视频、>8,000,000 帧；Part A 100 人（每人 13 段，已标注）、Part B 116 人（每人 13 段，未标注）、Part C 31 人（每人一段 8 分钟视频，已标注）；人工标注 1,109 个微表情 + 3,490 个宏表情，另有 1,508 段未标注视频（>4,000,000 帧）；RGB + 深度，同步皮电 / 脉搏 / 呼吸与语音。AU：新闻稿配图图注为 "Surprise with AU R1+R2"，说明表情样本带 AU 编码；AU 覆盖范围（是否每个样本、是否有强度）在本次打开的页面上未写明，获批后确认。
- 获取（协议原文已读）：第 1 条 "Usage of the CAS(ME)3 for any commercial purpose is strictly forbidden"，并列举"证明或测试商业系统"也算商用；第 2 条签署人须用单位邮箱，**学生 / 临时雇员须由导师签署**并列出学生信息；第 3 条禁止任何形式分发，数据只能放在受限访问的本机，Part A / B 大量编号被试与 Part C（除 27 号外）的图像不得发表；第 4 条须引用 TPAMI 论文。流程：填表 → 打印手签 → 扫描 PDF → 通过链接上传（GitHub 说明称现走 MELAB 站点的外部表单）。联系人 lijt@psych.ac.cn / wangsujing@psych.ac.cn。
- 用法：目前唯一核实到申请路径与协议全文的中国面孔 AU 数据；用途同 DISFA（AU 工具在 aarch64 上的构建正确性 + 中国面孔上的方向一致性），Part C 的 8 分钟长视频比微表情片段更接近访谈时长。协议里"测试商业系统"也算商用，团队作品若日后商业化，用它做过的评测数字不能再引用。
- 风险：需博士的导师或团队里有单位邮箱的正式成员签署（学生不能自签）；主打微表情，AU 标注粒度待确认；协议要求的图像不得发表条款意味着 BENCHMARK.md 不能放它的截图。
- 替代品：FEAFA+（第 11 条）；自录数据（空白区第 4 条）。

#### 13. BP4D-Spontaneous / BP4D+（Binghamton）
- URL：https://www.cs.binghamton.edu/~lijun/Research/3DFE/3DFE_Analysis.html
- 内容：BP4D 41 人（18–29 岁，含 11 名亚裔）2D + 3D 视频、FACS 手工编码、约 2.6 TB；BP4D+ 140 人（18–66 岁）3D / 2D / 热成像 / 生理同步，超过 10 TB。
- 获取：接收方与其机构科研管理负责人共同签署书面协议，学生不能作为接收方；仅限非营利用途，商用另联系 TTO（techtransfer@binghamton.edu）。
- 用法：AU 工具事实上的训练与评测标准，但体量与手续都不适合九天冲刺；只在 BENCHMARK.md 里引用工具论文报的 BP4D 数字即可。
- 风险：数 TB 传输；机构签字流程慢。

#### 14. Aff-Wild2（iBUG / ABAW）
- URL：https://ibug.doc.ic.ac.uk/resources/aff-wild2/
- 内容：564 段野外视频、约 2.8M 帧、554 人；12 个 AU（1, 2, 4, 6, 7, 10, 12, 15, 23, 24, 25, 26）、7 类基本表情、逐帧 VA。
- 获取：签 EULA；学术用机构邮箱，企业可说明研究或商用目的申请；约 14 天回复。
- 用法：若要看 AU 工具在低质量、偏头、遮挡下的鲁棒性，它比 DISFA 更贴近网络摄像头访谈；表情 / VA 标签按铁律不用。
- 风险：申请周期；带情绪标签，须只取 AU 子集。

#### 15. CK+ 与 AFEW / SFEW
- CK+：https://www.jeffcohn.net/Resources/ → 申请门户 https://ckplus.jeffcohn.net ；只接受 "faculty member or research scientist" 申请，"Commercial use is not permitted"。摆拍、老旧，只够做 AU 工具的最小冒烟测试。
- AFEW / SFEW：https://users.cecs.anu.edu.au/~few_group/AFEW.html ；邮件 dhallabhinav[at]gmail.com 主题 "AFEW/SFEW download" 附签名 EULA；电影片段 7 类情绪标签，页面统计停在 2011–2013。对本项目是纯情绪标签集，与铁律冲突，仅列名（D）。

#### 16. deface（ORB-HD）及表情保持型替代
- URL：https://github.com/ORB-HD/deface ；PyPI https://pypi.org/project/deface/
- 做什么：CenterFace 检测 + 模糊 / 涂黑 / 马赛克，默认丢弃音轨。
- 怎么装：`pip install deface`。PyPI 1.5.0（2023-10-15）基础依赖为 imageio、imageio-ffmpeg、numpy、tqdm、scikit-image、opencv-python，全部纯 Python；GPU 只在 extras 里（`cuda` extra 写的是 onnxruntime-cuda），实际要 GPU 就手动装第 2 条的 onnxruntime-gpu，CPU 跑演示素材也够。
- 输出：脱敏视频。
- 具体用法：不进实时管线（我们的管线只存特征不存视频），用于三处——评委演示视频、evals 里 20 个合成病例若配视频素材、BENCHMARK.md 截图。
- 风险：仓库最近推送 2024-10-13（23 个月）、PyPI 最后发布 2023-10-15（35 个月），已过 18 个月停更线——因此降为 B，开赛前要在 aarch64 上实跑一次确认 CenterFace ONNX 仍能加载；模糊会破坏表情，脱敏后的素材不能再拿去测 AU 工具。
- 替代品：face_anon_simple（https://github.com/hanweikung/face_anon_simple ，WACV 2025，AGPL-3.0，215 star，2026-05-07 仍在推送，保留表情 / 头姿 / 目光，但要跑扩散模型，标"需替换"）；DeepPrivacy2（https://github.com/hukkelas/deep_privacy2 ，Apache-2.0，383 star，2024-01 停更）；GANonymization（https://github.com/hcmlab/GANonymization ，MIT，22 star，ACM TOMM 2024，DOI 10.1145/3641107，2025-05 推送，表情保持型 GAN）。

#### 17. "只存特征不存视频"的管线参照：OpenDBM、Reading Between the Frames、C-MIND
- OpenDBM：https://github.com/AiCure/open_dbm ，文档 https://aicure.github.io/open_dbm/ 。AGPL-3.0（需替换），72 star，推送 2023-02-10（停更风险）；面部变量（OpenFace 的 AU 出现 / 强度、表达性、地标）、运动变量（头动 / 头姿、眨眼、面部震颤、身体运动）、声学（Parselmouth / Praat）、言语（DeepSpeech 转写 + VADER 情感词典）。OpenFace 走 `opendbmteam/dbm-openface` x86 Docker，aarch64 不可行。只借鉴它的变量清单与命名，作为我们 `references/observation_schema.md` 的起点。
- Reading Between the Frames：https://github.com/cosmaadrian/multimodal-depression-from-video ，ECIR 2024，arXiv 2401.02746，README 声明 CC BY-NC-ND 4.0（GitHub API 识别为 NOASSERTION；禁商用禁衍生），94 star，2026-06-02 仍在推送。模态拆分值得抄：MediaPipe（脸 / 身 / 手地标）、MPIIGaze（目光）、InstBlink（眨眼）、EmoNet（表情嵌入，按铁律不用）、PASE+（音频）。目标是抑郁二分类，我们只取"每模态一个确定性提取器 + 只保存特征文件"的布局。
- C-MIND（AAAI 2026，arXiv 2508.04531，清华 CoAI）：国内某大学附属医院精神科 169 人（86 MDD / 83 对照）、访谈 / 图片描述 / 词语流畅性三任务；视频特征用 OpenFace 2.2.0 的目光向量、头姿、AU 做统计汇总；GPT-4o 零样本 +7.01%，融合后至多 +10% Macro-F1。**尚未公开**，作者称未来走 IRB 审批的申请制。对我们的价值仅是"国内临床团队也用同一套 OpenFace 特征"这一佐证，以及"临床专家指导"提示可提升效果的思路（我们的 references/ 知识包就是这种指导）。

### 空白区

搜过但没有找到合适资源的方向，及建议路线：

1. **坐姿访谈场景的"精神运动性迟滞 / 激越"开源引擎**：没有可直接用的。最近的是 CODY（运动障碍）与 AutoFidgetDetection（停更、OpenPose）。建议自己写：关键点工具 → 10 秒窗 × CODY 六族特征 → 博士定三档阈值 → MSE 观察句；小于厘米级的动作按 Koul & Novembre 2025 的证据直接放弃，只报"次数 / 占比"。检索式：`psychomotor retardation agitation video pose estimation depression github code`、`fidgeting detection seated person pose keypoints video open source`、`"self-adaptors" body gestures psychological distress video automatic detection code github`、`fidgeting quantification pose estimation video ADHD hyperactivity restlessness deep learning 2024 2025`、`body movement kinematics depression clinical interview pose estimation OpenPose MediaPipe psychomotor 2024 2025 paper`、`leg shaking OR "leg bouncing" OR restlessness detection MediaPipe pose seated github`。
2. **用 VL 直接对访谈画面生成 MSE 风格观察的论文或 prompt 范例**：未找到专门研究；最近的是 GPT4Affectivity（AU 层面）、C-MIND（LLM 读 OpenFace 特征做推理）与两篇综述。建议：VL 只做特征表 → MSE 文本的归纳，prompt 范例由博士按 MSE 条目自写；"外观"条目允许 VL 看抽帧但强制加"待人工确认"。检索式：`large vision language model mental status examination video interview observation clinical arxiv`、`"mental status examination" video "vision-language" OR "multimodal large language model" appearance behavior psychomotor automated observation`、`vision language model zero-shot depression detection video DAIC-WOZ nonverbal behavior description Qwen2.5-VL 2025`、`video large language model behavioral description interview "describe" nonverbal behavior LLM-generated descriptions depression prompt study 2025`、`多模态大模型 视频 精神状况检查 非言语行为 观察 描述 抑郁 访谈 论文`。
3. **VL 零样本目光接触**：证据一致为负（ACL 2026、Eyes on VLM）。建议降级：目光接触交给面部通道的专用 gaze 工具；若来不及，用头姿（yaw / pitch 在阈值内）做"面部朝向对话方"的代理指标，并在预诊单上写明是代理量。检索式：`multimodal large language model eye contact gaze detection zero-shot benchmark evaluation head pose`。
4. **可在九天内拿到的中国面孔 AU 数据集**：本轮把 CAS(ME)3 的申请路径与协议核实到了（第 12 条），FEAFA+ 只有摆拍部分可能是东亚面孔（第 11 条），RAF-AU 站点仍打不开（见未核实）。两者都要签协议、CAS(ME)3 还要导师级签署，9 天内到手不保证。建议替代：团队成员在知情同意下自录 5–10 段 3 分钟"模拟来访"视频（不用任何合作医院数据），由博士按 MSE 条目盲标，作为 evals 的观察通道金标准；公开数据集只用于"构建正确性"校验，并且按各协议不得把截图放进 BENCHMARK.md。检索式：`DISFA dataset facial action unit license request access`、`BP4D+ BP4D dataset request license Binghamton`、`Aff-Wild2 dataset access license ABAW`、`CK+ extended Cohn-Kanade dataset access license 2025`、`EmotioNet database access AU annotations license Ohio State`、`CAS(ME)3 database access agreement Chinese Academy of Sciences micro-expression AU`、`CAS(ME)3 third generation facial spontaneous micro-expression database depth information IEEE TPAMI 2022 arXiv`、`RAF-AU database download access whdeng`、`"RAF-AU" database in-the-wild facial expressions subjective emotion judgement objective AU annotations Yan Deng ACCV 2020 arXiv`。
5. **aarch64 + CUDA 13 上的姿态 / 脱敏工具实测数据**：只有 Ultralytics 有官方 DGX Spark 文档；MediaPipe / rtmlib / facetorch / deface 只有 wheel 存在性或 README 声明，没有 Spark 实测帖。建议 9/15–9/19 验证清单：（a）`pip install "mediapipe>=1.0.0"`，跑 pose landmarker 1 分钟视频记 FPS，`num_poses=2` 试双人；（b）`pip install rtmlib --no-deps && pip install numpy opencv-python opencv-contrib-python tqdm onnxruntime-gpu`，`python -c "import onnxruntime as ort; print(ort.get_available_providers())"` 须含 `CUDAExecutionProvider`，再跑 RTMPose-m 与 RTMW；（c）拉 `ultralytics/ultralytics:latest-nvidia-arm64` 跑 `yolo26n-pose`；（d）在 cu130 torch 的 venv 里 `pip install facetorch==1.0.0rc3`，禁用 FER / VA / deepfake 头后跑一张图；（e）`pip install deface` 对同一段视频脱敏，确认 CenterFace ONNX 能加载。检索式：`site:github.com mediapipe pose landmarker aarch64 linux wheel`、`RTMPose mmpose 2026 latest release aarch64 onnxruntime`、`DGX Spark ultralytics YOLO pose arm64 GB10 install`、`ViTPose github license ViTAE-Transformer ViTPose++ huggingface transformers`。
6. **表情保持型脱敏在 aarch64 的可行性**：face_anon_simple / GANonymization 都是 PyTorch，理论可行但无人在 ARM 上跑过的记录；演示素材用 deface 模糊即可，不建议投入。检索式：`deface face anonymization video github ORB-HD`、`expression-preserving face anonymization open source github action unit preserved de-identification`。

### 未核实线索

- **EmotioNet**（Ohio State）：https://cbcsl.ece.ohio-state.edu/dbform_emotionet.html —— 2026-09-14 再次域名解析失败（`ENOTFOUND`），许可与申请条件未核实；搜索摘要称 95 万张野外图像、2.5 万张人工 AU 标注，联系人 feng.559@osu.edu。
- **RAF-AU**（北邮邓伟洪组 + 京东数科）：数据页 http://www.whdeng.cn/RAF/model3.html http / https 各两次连接均被关闭，**访问条件与许可未核实**；论文本身已核实——Yan, Li, Que, Pei, Deng, "RAF-AU Database: In-the-Wild Facial Expressions with Subjective Emotion Judgement and Objective AU Annotations", ACCV 2020（https://accv2020.github.io/miniconf/poster_414.html ，arXiv 2008.05196，Springer DOI 10.1007/978-3-030-69544-6_5），页面只写 "finely annotated by experienced coders"，搜索摘要称 26 种 AU、两位 FACS 编码员、邮件申请密码、仅研究用途。建议团队用国内网络打开核实。
- **CAS(ME)3 的 AU 标注覆盖范围**：本次打开的 GitHub 说明页、MELAB 数据集页与协议 PDF 都未写明 AU 编码是否覆盖全部表情样本、是否含强度；只有新闻稿图注的 "AU R1+R2" 一处证据。IEEE Xplore 页与 Semantic Scholar 页返回空内容，摘要未能读取。
- **Facial-R1**（arXiv 2511.10254）：含 GPT-4o / Qwen2.5-VL / InternVL 零样本 AU 识别对比表，但论文已于 2026-06-04 被作者以知识产权原因撤回，数字未采用。
- **Face-LLaVA**（WACV 2026，https://github.com/ihp-lab/Face-LLaVA ，19 star，2026-03 推送）：仓库无 SPDX 许可（NOASSERTION），模型 https://huggingface.co/chaubeyG/FaceLLaVA 与数据 FaceInstruct-1M 的许可未能在页面上确认；项目页未给零样本 AU 数字。按"仅研究用途"处理。
- **MediaPipe Python 在 Linux 的 GPU delegate**：任务文档与 Python 指南均未提及，只指向通用 Python setup 页，未能确认；按 CPU 规划不影响结论。
- **facetorch 在 aarch64 上的实际运行**：README 明写 ARM 为 experimental，未找到任何 ARM / Jetson / Spark 实测记录；1.0.0 仍在 rc3。
- **Ultralytics DGX Spark 指南的精确更新日期**：页面显示创建于 2026-01-09、"几天前更新"，未取得精确更新日；镜像内组件版本（PyTorch 26.08 / CUDA 13.4 / TensorRT 11）以 GitHub 原始 markdown 为准。
- **NVIDIA TAO / DeepStream 的 BodyPose 与 Redaction 参考应用（NGC arm64 镜像）**：未检索核实，作为 Spark 原生姿态 / 脱敏路线的备选线索留给部署章节。

### 第 2 版修订记录（供审查对照）

- FEAFA+：254 段 → 154 段（127 摆拍 + 27 段 DISFA 重标）；标注 23 类并注明 arXiv "24" 口径；"东亚面孔校验"限定到摆拍 99,356 帧。
- deface：A → B（推送 2024-10-13、PyPI 2023-10-15，超 18 个月线）；补 PyPI 依赖与 GPU extra 说明。
- MediaPipe：改写"单人"表述为 `num_poses`（默认 1、可 >1），咨询师入镜改为 `num_poses=2` 后按框位置选人；补 aarch64 轮子版本史与 `>=1.0.0` 钉版。
- 一览表许可列统一为「商用友好 / 需替换 / 仅研究用途」。
- Rode 2025：改为原文口径（11 估计器、25 人、2D MPJPE 72–122 mm、RTMPose 72 mm 最准、25–200 FPS、单目"深度较差且对自遮挡更敏感"原话），删去无法核到的 BlazePose / Detectron2 数字。
- rtmlib：补 PyPI 0.0.16 的 CPU `onnxruntime` 依赖冲突与 `--no-deps` 安装顺序（GitHub requirements.txt 与 PyPI JSON 一致）。
- 新增 facetorch 互引条目（PyPI 0.6.2 vs 1.0.0rc3 两条线、CUDA 13.0 / ARM experimental 原话、禁用情绪头），用于头部位移辅助特征。
- CODY：更正依赖布局（核心 requirements 无 ultralytics，YOLO 只在可选 notebook）、输入格式、期刊 DOI 10.1002/acn3.70474。
- Koul & Novembre 2025 区间改为原文精确值（1.51–10.15 cm；肩 0.34–0.36、肘 0.34–0.37）。
- OpenDBM 言语组件改为 DeepSpeech + VADER。
- "Looking at the Body"从未核实移入正文：期刊版 IEEE TAFFC 14(2) 2023，DOI 10.1109/TAFFC.2021.3101698；会议版 FG 2020 "Automatic Detection of Self-Adaptors for Psychological Distress"，DOI 10.1109/FG47880.2020.00032（Crossref 核实）。
- CAS(ME)3 从未核实移入正文（第 12 条）：GitHub 说明、MELAB 数据集页、协议 PDF 全文、Crossref 论文记录、EurekAlert 新闻稿均已打开；AU 覆盖范围仍列未核实。