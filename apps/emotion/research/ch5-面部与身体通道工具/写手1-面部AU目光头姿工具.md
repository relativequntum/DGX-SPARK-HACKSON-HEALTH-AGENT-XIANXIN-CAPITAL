## 第5章 情绪采集 · 面部与身体通道工具 · 面部：动作单元、目光、头姿工具

核实基准日 2026-09-14（第 2 版，按第 1 轮审查修订）。仓库数据取自 GitHub API（`gh api`）与仓库页；PyPI 轮子与依赖钉取自 PyPI JSON API；论文取自 arXiv / Europe PMC 全文 XML / PMC / ClinicalTrials.gov API v2；模型卡 PDF 抽取。未打开核实的条目一律放在末尾「未核实线索」。

**本版相对第 1 版的改动**：① LibreFace 的 aarch64 判断改为「CPU-only 可装、无 CUDA 13 加速、需 3.10/3.11 venv」（第 1 版「装不上」有误）；② Blueskeye TrueBlue 由 T1 降为 T3，移入竞品名单；③ 新增 facetorch（B）、yakhyo/gaze-estimation（C）、Gaze-LLE（C），BlinkFormer 写入空白区作「找到但不可用」证据；④ Skiendziel 2019 的 AU 数字改为按 Table 2 / Table 4 原表逐项引用；⑤ LibreFace 速度改引摘要与 2.0 项目页的口径；⑥ OpenFace 2.2 的 aarch64 issue 状态、6DRepNet 期刊版与 6DRepNet360、Zhao 2026 的族裔构成、MediaPipe / torchcodec / xgboost 的 aarch64 轮子史全部补核。

**先说结论（供 9/15–9/19 验证周排期）**

1. 最省事、能一天接通的路线仍是 **MediaPipe Face Landmarker（纯 CPU，pip 装 aarch64 轮子，零 CUDA 依赖）**：一次前向同时给 478 点网格（含 10 个虹膜点）、52 个 blendshape（AU 近似）、4×4 头姿矩阵，眨眼用 blendshape 或 EAR 规则。四个信号（AU 近似、头姿、目光近似、眨眼）都能从这一个模型落成 MSE 观察条目。
2. 第二层精度升级走 **纯 PyTorch cu130 aarch64**（PyTorch 维护者已确认 ARM 二进制自 CUDA ≥ 12.8 起即支持 DGX Spark）：头姿用 6DRepNet，目光用 ptgaze（ETH-XGaze 模式），AU 用 OpenGraphAU（41 AU，Apache-2.0）——接入 OpenGraphAU 有两条路：裸仓库（需自备裁剪对齐）或 **facetorch 1.0.0rc3**（已把 RetinaFace + OpenGraphAU Swin-B + 3D 对齐打包，README 自述 CUDA 13.0 已验证、ARM 为实验性）。ONNX Runtime GPU 1.30.0 已有官方 aarch64 + CUDA 13 轮子，但主路线不需要走 ONNX。
3. 避开：OpenFace 2.2（C++/dlib/OpenBLAS，aarch64 无正式支持 + 非商用许可）、PyAFAR（只发可执行文件）、TAO GazeNet（EULA + 需自建 TensorRT 引擎）。LibreFace 的 pip 包**能装但只能 CPU 跑**（硬钉 torch==2.0.0 / mediapipe==0.10.5，两者在 PyPI 上都有 aarch64 CPU 轮子，但仅到 cp311，且 torch 2.0.0 无 CUDA 13 构建），只作对照实现。
4. 铁律核对：所有七分类表情库（DeepFace emotion、fer、EmotiEffLib）只列为 D（作输出）/ C（作特征）；OpenFace 3.0、py-feat v2、LibreFace、facetorch 自带情绪 / 效价头，接入时必须禁用该输出。

### 一览表

推荐等级：A 直接用 / B 改造用 / C 只借鉴思路 / D 不建议

| 名称 | 类型 | 一句话 | Stars 与活跃度 | 许可 | aarch64 + CUDA 13 | 中文 | 对应通道或组件 | 推荐等级 |
|---|---|---|---|---|---|---|---|---|
| MediaPipe Face Landmarker | 工具 + 模型 | 478 点 3D 网格 + 52 blendshape + 4×4 头姿矩阵，pip 装、CPU 跑 | ~37k；2026-09-11 有提交；PyPI 1.0.1（2026-08-14） | 商用友好（代码 Apache-2.0；FaceMesh-V2 与 Blendshape-V2 模型卡均写 Apache-2.0） | 可行：PyPI 1.0.0 起有 `py3-none-manylinux_2_28_aarch64` 轮子，Python 3.9–3.12，纯 CPU | 语言无关 | 面部（AU 近似 / 头姿 / 目光近似 / 眨眼）→ 预诊单 MSE、看板 | A |
| EAR 眨眼规则（Soukupová & Čech 2016） | 方法 | 6 个眼部关键点算眼睛纵横比，阈值 + 连续帧计眨眼 | 论文（CVWW 2016），无仓库依赖 | 商用友好（公开方法） | 可行：纯 numpy | 语言无关 | 面部（眨眼率）→ MSE 精神运动 | A |
| 6DRepNet（附 6DRepNet360） | 模型 | 单张人脸直接回归 yaw/pitch/roll（6D 旋转表示；ICIP 2022，期刊版 IEEE TIP 2024） | ~680；最后 push 2024-07-02（停更风险）；PyPI sixdrepnet 0.1.6（2023-03）；6DRepNet360 ~190、2024-06 | 商用友好（MIT）；权重训自 300W-LP 研究数据集 | 可行线索：纯 PyTorch，cu130 aarch64 轮子可用 | 语言无关 | 面部（头姿 / 头动量 / 低头时长） | B |
| ptgaze（hysts/pytorch_mpiigaze_demo） | 工具 + 模型 | `pip install ptgaze` 一条命令的注视方向估计，三套权重（MPIIGaze / MPIIFaceGaze / ETH-XGaze），内置 MediaPipe 检测 + 头姿 | ~370；最后 push 2026-07-25；PyPI 0.3.0（2026-07-05） | 需替换（代码 MIT；权重训自非商用数据集） | 可行线索：torch ≥ 2.7 有 cu130 aarch64 轮子；`mediapipe>=0.10.30` 在 aarch64 上只会解析到 1.0.x（0.10.20–0.10.35 无 aarch64 轮子）；Linux 需 `libgles2` | 语言无关 | 面部（目光方向 → 目光接触比例） | B |
| facetorch（新增） | 工具 | 把 RetinaFace + OpenGraphAU Swin-B（41 AU）+ 3D 对齐（MobileNetV2）等打包成 `torch.export` `.pt2`，一行配置跑全脸分析；README 自述 CUDA 13.0 已验证 | ~610；最后 push 2026-09-10；PyPI 稳定版 0.6.2（2026-04-17），预发布 1.0.0rc3（2026-09-03） | 商用友好（Apache-2.0；所含 AU 模型 Apache-2.0、对齐模型 MIT，权重训练数据为研究数据集） | 可行线索：纯 PyTorch，torch 2.6–2.13，Python ≥3.10 <3.13；README 明写「Linux x86-64 为正式平台，ARM 为实验性」；Docker 镜像为 x86 | 语言无关 | 面部（AU / 头姿辅助） | B |
| OpenFace 3.0（CMU MultiComp） | 工具 + 模型 | 29.4M 参数多任务模型：关键点 + AU 强度（DISFA 12 / BP4D 27）+ 注视角 + 情绪（弃用），CPU 38 ms/帧 | ~190；最后 push 2025-06-10；PyPI openface-test 0.1.26（2025-06-11） | 仅研究（CMU 学术非商用许可） | 可行线索：纯 PyTorch/timm；依赖版本硬钉，建议独立 venv | 语言无关 | 面部（AU / 目光） | B |
| py-feat | 工具 | v1 模块化（RetinaFace + MobileFaceNet + XGBoost 20 AU + L2CS 注视）；v2 单网络 ConvNeXt-V2-Tiny 同时出 20 AU + 6DoF 头姿 + 478 点 + 52 blendshape + 情绪/效价 | ~390；最后 push 2026-09-13；PyPI 2.1.3（2026-09-07） | 代码 MIT；v1 默认组件多为 MIT，ArcFace 权重与 img2pose 非商用；**v2 模型仅研究** | 可行：torch ≥ 2.5、Python ≥ 3.11；torchcodec 0.16.0 与 xgboost 3.4.1 均有 aarch64 轮子（本轮核实） | 语言无关 | 面部（AU / 头姿 / 目光） | B |
| OpenGraphAU / ME-GraphAU | 模型 | 图关系 AU 检测（IJCAI 2022）；OpenGraphAU 版输出 41 个 AU（含左右不对称），>50 FPS @ RTX 3090 | ~60 / ~200；最后 push 2025-08-21 | 商用友好（Apache-2.0 / MIT）；权重训自 BP4D、DISFA 等研究数据集 | 可行线索：torch ≥ 1.4 纯 PyTorch；需自备人脸裁剪对齐（或经 facetorch 接入）；权重在 Google Drive | 语言无关 | 面部（AU） | B |
| SynergyNet（备选 3DDFA_V3） | 模型 | 3DMM + 3D 关键点联合回归，直接给 yaw/pitch/roll（3DV 2021） | ~420；最后 push 2026-02-24（3DDFA_V3 ~400；2024-11-10，停更风险） | 商用友好（MIT） | 需自编译 Cython（Sim3DR、FaceBoxes），未见 aarch64 报告；3DDFA_V3 的 nvdiffrast 可不装 | 语言无关 | 面部（头姿） | C |
| LibreFace（USC） | 工具 + 模型 | AU 强度（DISFA 12，PCC 0.63，摘要称比 OpenFace 2.0 高 7%、快 2 倍）+ AU 检测 + 表情 + 2.0 新增注视；2.0 项目页称 L40S 118.9 FPS、EPYC 9554 CPU 28.6 FPS | ~250；最后 push 2026-06-19；PyPI 0.2.0（2026-05-21） | 仅研究（USC research license；商用需联系 USC Stevens） | **CPU-only 可装**：硬钉 dlib==19.24.6、torch==2.0.0、torchvision==0.15.1、mediapipe==0.10.5，后三者在 PyPI 均有 cp38–cp311 manylinux2014_aarch64 CPU 轮子；无 CUDA 13 构建；需 3.10/3.11 venv（DGX OS 默认 3.12 不行）；dlib 源码编译 | 语言无关 | 面部（AU） | C |
| L2CS-Net（附 ETH-XGaze / Gaze360） | 模型 | 分角度回归注视（ICIP 2022；MPIIGaze 3.92°，Gaze360 10.41°） | ~530；最后 push 2024-02-02（停更风险） | 需替换（代码 MIT；权重训自 Gaze360、MPIIGaze，均非商用） | 可行线索：纯 PyTorch | 语言无关 | 面部（目光） | C |
| yakhyo/gaze-estimation（新增） | 模型 | ResNet / MobileNetV2 / MobileOne 注视回归，只在 Gaze360 上训练，带 ONNX 导出与推理脚本，RetinaFace（uniface）检测 | ~210；最后 push 2026-02-14 | 需替换（代码 MIT；权重仅训自 Gaze360，非商用数据集） | 可行线索：ONNX 权重 + onnxruntime-gpu 1.30.0 aarch64 CUDA 13 轮子，或 CPU onnxruntime | 语言无关 | 面部（目光；ptgaze 替补） | C |
| eye-contact-cnn（Chong et al. 2020） | 模型 | 每帧直接输出「目光接触分数」[0,1]，与人类专家一致（Nat Commun） | ~110；最后 push 2024-08-08（停更风险） | 仅研究（Georgia Tech 非商用） | 风险：PyTorch 0.4 时代代码需移植；dlib 可用 `--face` 绕开 | 语言无关 | 面部（目光接触） | C |
| Gaze-LLE（fkryan/gazelle，新增） | 模型 | 冻结 DINOv2 + 轻量解码器做第三人称「注视目标」估计：输出图内注视热图 + 「注视目标在 / 不在画面内」分数（CVPR 2025 Highlight） | ~860；最后 push 2026-03-18 | 商用友好（MIT）；训练集 GazeFollow / VideoAttentionTarget（数据集许可未核） | 可行线索：纯 PyTorch，DINOv2 骨干经 PyTorch Hub 下载 | 语言无关 | 面部（目光；仅当咨询师同框时有用） | C |
| RT-GENE / RT-BENE | 工具 + 模型 | 注视（ECCV 2018）+ 眨眼（ICCVW 2019）实时估计 | ~450；最后 push 2026-07-14 | 仅研究（CC BY-NC-SA 4.0） | 可行线索：`rt_gene_core` 纯 Python/PyTorch；官方环境只列 linux-64 / osx-arm64 / win-64 | 语言无关 | 面部（目光 / 眨眼） | C |
| OpenFace 2.2（TadasBaltrusaitis） | 工具 | 经典 C++ 工具：68 点 + AU 出现/强度 + 注视 + 头姿 | ~7.8k；最后 push 2024-06-01（停更风险） | 仅研究（CMU 非商用） | 高风险：dlib/OpenBLAS 原生编译；aarch64 无正式支持，#1054（arm64 Mac 链接失败，2023-08）仍开放 | 语言无关 | 面部（文献对照基线） | C（对照）/ D（部署） |
| NVIDIA TAO GazeNet + FPENet（NGC） | 模型 | NVIDIA 官方注视向量 + 68/80/104 点关键点，TensorRT/DeepStream 部署 | NGC 模型卡 2025-03-17 / 2024-11-27 更新 | 需法务核对（NVIDIA Model EULA） | 可行线索：Jetson arm64 有 FPS 数据；DGX Spark + CUDA 13 上需自建 TensorRT 引擎，未验证 | 语言无关 | 面部（目光 / 关键点） | C |
| FaceXFormer | 模型 | ICCV 2025 统一 Transformer：关键点、头姿、属性、表情等 9 任务，33 FPS | ~340；最后 push 2025-09-06 | 商用友好（MIT） | 可行线索：纯 PyTorch；环境文件钉 cu117 需改成 cu130 | 语言无关 | 面部（头姿备选） | C |
| 反例：DeepFace emotion / fer / EmotiEffLib（原 HSEmotion） | 库 | 七分类表情标签 | ~23k 活跃 / ~430 活跃 / ~1.1k 活跃 | 商用友好（MIT / MIT / Apache-2.0） | 可行 | 语言无关 | 不作为输出；至多作盲评对照特征 | D（作输出）/ C（作特征） |
| PyAFAR | 工具 | 成人 12 AU + 婴儿 9 AU，可执行程序 | ~30；最后 push 2024-12-27（停更风险）；仓库只有网页 | 仅研究（非商用；商用联系作者） | 不可行线索：只发 Win/Ubuntu/Mac 可执行文件，无源码，架构未标 | 语言无关 | 面部（AU） | D |

### 逐项说明

#### 1. MediaPipe Face Landmarker — A

- URL：https://github.com/google-ai-edge/mediapipe ；文档 https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker ；PyPI https://pypi.org/project/mediapipe/ ；模型卡 FaceMesh-V2 https://storage.googleapis.com/mediapipe-assets/Model%20Card%20MediaPipe%20Face%20Mesh%20V2.pdf ，Blendshape-V2 https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Blendshape%20V2.pdf
- 做什么：一个 `.task` 模型包串起 BlazeFace 检测（192×192）→ FaceMesh-V2（256×256）→ Blendshape-V2（MLP-Mixer，输入 146 个关键点）。FaceMesh-V2 模型卡明确写「478 个 3D 关键点」且「相比前一版新增 10 个虹膜关键点」；Blendshape 模型卡列出全部 52 个系数，值域 [0,1]，含 browDownLeft/Right、browInnerUp、browOuterUpLeft/Right、eyeBlinkLeft/Right、eyeLookIn/Out/Up/Down（左右各一）、eyeSquint、eyeWide、cheekSquint、noseSneer、mouthSmile、mouthFrown、mouthPress、mouthStretch、mouthDimple、mouthPucker、jawOpen 等。Python API `FaceLandmarkerOptions(output_face_blendshapes=True, output_facial_transformation_matrixes=True, running_mode=VIDEO/LIVE_STREAM)`，结果字段 `face_landmarks / face_blendshapes / facial_transformation_matrixes`。
- 怎么装：`pip install mediapipe==1.0.1`。aarch64 轮子史（本轮 PyPI JSON 核实）：0.10.5（2023-09-15）有 cp38–cp311 `manylinux2014_aarch64`；0.10.18（2024-11-01）有 cp39–cp312；**0.10.20、0.10.30、0.10.35 均无 aarch64 轮子**；1.0.0（2026-07-27）起改为 `py3-none-manylinux_2_28_aarch64`，1.0.1（2026-08-14）同（35.8 MB），Python 3.9–3.12。DGX OS 7 基于 Ubuntu 24.04（glibc 2.39、系统 Python 3.12），满足 manylinux_2_28。纯 CPU 推理，与 CUDA 13 / sm_121 无关；Grace 20 核 ARM CPU 跑一路 720p 视频足够。`.task` 模型包首次需联网下载一次，之后完全离线。
- 输出：478×3 关键点、52 个 blendshape 系数、4×4 头姿变换矩阵（分解即得 yaw/pitch/roll）。
- 具体用法（面部通道 → MSE 观察条目）：
  - 表情活动量：以 mouthSmile、mouthFrown、browDown、browInnerUp、mouthPress、jawOpen 等 blendshape 的活动能量与方差相对会话前 60 秒基线的比值，落成「表情活动量：受限 / 适度 / 增高」——只写活动量，不写情绪词。
  - 目光接触（来访者面对屏幕的场景）：虹膜中心在眼裂内的相对位置 + eyeLookIn/Out/Up/Down + 头姿 yaw/pitch，会话开始时做 10 秒「请看屏幕中心」标定，落成「目光朝向屏幕比例 x%、最长回避 y 秒、回避次数 n」。
  - 精神运动：头姿矩阵逐帧差分得头动幅度与角速度；eyeBlinkLeft/Right 过阈值计眨眼率（每分钟）；pitch 低于阈值持续时长即「低头时长」。
- 风险：模型卡自述「面向 AR 娱乐、自拍模式，偏离相机 >80° 或人脸 <50% 可见时不适用」「不用于人命攸关决策」——与我们「只采集不诊断」一致，但要写进 SKILL.md 的限制条款。blendshape 与 FACS AU 只是「松散对应」（HF 移植版模型卡原话 loosely correspond），预诊单上标「AU 近似（blendshape）」而不是宣称 FACS AU。官方页无 FPS 数据；社区教程称 CPU 30 FPS，属 T3。Python GPU delegate 在 Linux 上多起 issue 报无加速，不要指望 GPU。Blendshape 模型卡有 Monk 肤色 1–10 与性别公平性评估，最大偏差在一个标准差内，可作为「跨人群」的最低保证。
- 替代品：py-feat v2 内置同一套 478 点 + 52 blendshape 的 PyTorch 移植（HF `py-feat/mp_blendshapes`，本轮核实：Apache-2.0，输入 146 或 473 点、输出 52 blendshape，MLP-Mixer），若已装 py-feat 可不另装 mediapipe。

#### 2. EAR 眨眼规则（Soukupová & Čech 2016） — A

- URL：原文 PDF https://cmp.felk.cvut.cz/ftp/articles/cech/Soukupova-CVWW-2016.pdf （21st Computer Vision Winter Workshop, Rimske Toplice, 2016-02-03/05）
- 做什么：每帧取 6 个眼部关键点 p1…p6，EAR = (‖p2−p6‖ + ‖p3−p5‖) / (2‖p1−p4‖)；睁眼时近似常数，闭眼趋近 0；论文示例用阈值 t = 0.2，再用短时窗 SVM 判眨眼。
- 怎么装：不用装，numpy 十几行；眼部关键点取自 MediaPipe 478 点中的眼裂点。
- 输出：逐帧 EAR 标量 → 眨眼事件 → 眨眼率（次/分）与长闭眼时长。
- 具体用法：面部通道「精神运动 / 警觉」条目：眨眼率、闭眼 >1 s 事件计数。与 MediaPipe 的 eyeBlinkLeft/Right 互为校验，两者不一致时标「眨眼计数不可靠」。
- 风险：戴眼镜反光、低头角度大时 EAR 失真；论文阈值是在其数据集上定的，需在验证周用 3–5 个团队成员的视频重新定阈值。
- 替代品：RT-BENE（深度眨眼，非商用）；MediaPipe eyeBlink blendshape。

#### 3. 6DRepNet（附 6DRepNet360） — B

- URL：https://github.com/thohemp/6DRepNet ；论文 https://arxiv.org/abs/2202.12555 （ICIP 2022）；期刊版 IEEE Transactions on Image Processing 2024，DOI 10.1109/TIP.2024.3378180（README 核实）；PyPI https://pypi.org/project/sixdrepnet/ ；全角度版 https://github.com/thohemp/6DRepNet360
- 做什么：RepVGG 骨干直接回归 6D 旋转表示，经 Gram-Schmidt 得旋转矩阵，输出 yaw/pitch/roll（度）；README 表：AFLW2000 MAE 3.97°，BIWI（70/30 划分）2.66°。6DRepNet360（~190★，MIT，最后 push 2024-06-10）覆盖全旋转范围，权重放 cloud.ovgu.de，README 写用法「Coming soon」。
- 怎么装：`pip3 install sixdrepnet`（0.1.6，2023-03-29；依赖 torch ≥ 1.10.1、torchvision、opencv-python、scipy 等，全是有 aarch64 轮子的纯 Python 包），人脸检测用 `git+https://github.com/elliottzheng/face-detection`（纯 PyTorch RetinaFace）。PyTorch 走 `--index-url https://download.pytorch.org/whl/cu130`。
- 输出：每帧三个欧拉角。
- 具体用法：面部通道「精神运动」：头动幅度（角度标准差）、角速度均值、静止占比、低头（pitch）持续时长；作为 MediaPipe 头姿矩阵的第二路校验（两路差 >10° 时标不可靠）。
- 风险：最后 push 2024-07（停更风险）；PyPI 包 2023 年后未更新；权重训自 300W-LP（研究数据集，商用前法务核对）；仓库页未给 FPS；**权重在 Google Drive（README 核实），国内不可达，要提前搬运**。
- 替代品：MediaPipe 头姿矩阵（零成本）；facetorch 的 3D 对齐头；SynergyNet；FaceXFormer。

#### 4. ptgaze（hysts/pytorch_mpiigaze_demo） — B

- URL：https://github.com/hysts/pytorch_mpiigaze_demo ；PyPI https://pypi.org/project/ptgaze/ ；数据集页 https://www.perceptualui.org/research/datasets/MPIIGaze/
- 做什么：`ptgaze --mode eth-xgaze` 即可对图像/视频/摄像头做注视估计，三种模式：MPIIGaze（眼区）、MPIIFaceGaze（全脸）、ETH-XGaze（大头姿）；同时输出头姿与关键点，默认用 MediaPipe 做人脸检测（可换 dlib / face_alignment）。
- 怎么装：`pip install ptgaze`（0.3.0，2026-07-05；Python ≥ 3.10；依赖 torch ≥ 2.7、torchvision ≥ 0.22、mediapipe ≥ 0.10.30、face-alignment、timm、huggingface-hub、safetensors）；因 0.10.20–0.10.35 无 aarch64 轮子，`mediapipe>=0.10.30` 在 aarch64 上会解析到 1.0.x（正好是我们要的版本）；权重在 HF Hub 首次联网拉取；Linux 需 `libgles2`。
- 输出：注视向量（pitch/yaw）、头姿、归一化人脸。
- 具体用法：面部通道「目光接触」：注视角落在屏幕/相机方向 ±θ 内的帧占比（θ 在标定时定，建议 10–15°），回避片段计数与最长时长。相比 MediaPipe 虹膜近似，ETH-XGaze 模型在大头姿下更稳。
- 风险：三套权重分别训自 MPIIGaze（页面写明「仅限非商用科研」）、ETH-XGaze（仓库 README 写 CC BY-NC-SA 4.0）——代码 MIT 但权重非商用，商用需自训或换权重；PyPI 对每个包都硬约束了较新版本，与 NGC 容器内置 torch 可能冲突，用独立 venv。
- 替代品：yakhyo/gaze-estimation（ONNX，更轻）；L2CS-Net（py-feat v1 已封装）；eye-contact-cnn（直接给接触分数）。

#### 5. facetorch — B（新增）

- URL：https://github.com/tomas-gajarsky/facetorch ；PyPI https://pypi.org/project/facetorch/ ；README https://raw.githubusercontent.com/tomas-gajarsky/facetorch/main/README.md
- 做什么：单作者维护的人脸分析封装库（~610★，Apache-2.0，最后 push 2026-09-10）。README 模型表：检测 RetinaFace（27.3M，MIT）；**AU：OpenGraphAU Swin Base，41 AU，94M，Apache-2.0，来源 lingjivoo**；**3D 对齐：MobileNetV2（4.1M，MIT，来源 SynergyNet）**；另有 FER（EfficientNet）、效价/唤醒、深伪检测、身份嵌入 / 验证头（本项目全部禁用）。1.0 版把所有模型改为 `torch.export` 的 `.pt2` 产物（不再依赖 TorchScript 与模型源码），权重「首次使用时经 Hugging Face Hub 下载到版本化用户缓存」。用 Hydra 配置禁用单个头：`analyzer/predictor/fer=null` 或 `include_predictors=[...]`。
- 怎么装：PyPI 稳定线 0.6.2（2026-04-17；torch ≥1.9 <2.4，Python ≥3.8）已过时；要用预发布 `pip install "facetorch==1.0.0rc3"`（2026-09-03；Python ≥3.10 <3.13；torch 2.6.x–2.13.x 及对应 torchvision；README 自述「GPU 执行按 CUDA 13.0 验证」）。Docker 镜像 `tomasgajarsky/facetorch` / `facetorch-gpu`（tag 1.0.0-rc.3）为 x86。README 原话：「Linux x86-64 is the official v1 candidate platform; Windows, macOS, ARM, and Apple MPS are experimental」——aarch64 上要自己 pip 装 cu130 torch 后再装它。
- 输出：每张脸 41 个 AU 的 logits/概率、3D 对齐参数（含头姿；README 注明需 `include_tensors=True` 才把该头的预测放进 `Prediction.logits`）、人脸框。API 只接受单张图像（图内多张脸可批处理，`face_batch_size` ≤64），无视频接口，需自己按帧循环。
- 具体用法：**Day 3 接 OpenGraphAU 的替代路径**——省掉裸仓库「自备裁剪对齐 + 从 Google Drive 搬权重」两个痛点；41 AU 落成 AU12/AU15/AU14/AU1/AU4 出现频率与持续时长（MSE「表情活动量」条目）；3D 对齐头顺带给第三路头姿校验。**不改变主选型**：MediaPipe 一天路线不变。
- 风险：ARM 仅「实验性」，无 aarch64 公开实测；`.pt2` 产物在 x86 上导出，理论可移植但未在 aarch64 验证；Swin-B 94M 比裸仓库的 ResNet-50 变体重；rc 版 API 可能再变；权重走 HF Hub（国内需镜像或提前缓存）；FER / 效价 / 深伪 / 身份验证头与铁律（不做情绪标签、不做人脸识别）冲突，必须在配置层禁用并在 SKILL.md 写明。
- 替代品：OpenGraphAU 裸仓库；OpenFace 3.0。

#### 6. OpenFace 3.0 — B

- URL：https://github.com/CMU-MultiComp-Lab/OpenFace-3.0 ；论文 https://arxiv.org/abs/2506.02891 （自述 FG 2025，README 写 proceedings 尚未上线）；PyPI https://pypi.org/project/openface-test/
- 做什么：RetinaFace 检测 + STAR 关键点 + 一个多任务模型同时输出 AU 强度、注视 yaw/pitch、8 类情绪、人脸框；论文给出 29.4M 参数（OpenFace 2.0 44.8M、py-feat 49.3M），CPU-only 38 ms/帧（Threadripper 1920X）；AU 在 DISFA 12 个、BP4D 27 个上评测；注视训自 MPIIGaze + Gaze360。
- 怎么装：`pip install openface-test`（0.1.26，2025-06-11；torch/torchvision 未钉版本，timm==1.0.15、numpy==1.26.4、opencv_contrib_python==4.11 等硬钉）+ `openface download`（权重走 HF 或 Google Drive）。纯 PyTorch，理论上 cu130 aarch64 可跑，无人报告过。
- 输出：TSV，每帧时间戳、框、关键点、情绪标签、注视角、AU 强度。
- 具体用法：面部通道「AU 强度」与「目光」的第二来源；接入时**必须丢弃情绪列**（铁律）。AU 强度可直接落成「AU12/AU15/AU14 活动统计」，与 Girard 2014 的抑郁相关 AU 对齐。
- 风险：许可为 CMU 学术非商用（LICENSE 明写「only for noncommercial research purposes」，不得再分发）——赛后商用需替换；最后 push 2025-06（15 个月，接近停更线）；PyPI 包名是 `openface-test`，无描述无许可元数据，成熟度低；论文自述非正脸时性能下降。
- 替代品：OpenGraphAU / facetorch（Apache-2.0，AU 出现概率）；LibreFace（AU 强度，也是仅研究）。

#### 7. py-feat — B

- URL：https://github.com/cosanlab/py-feat ；文档 https://py-feat.org/ 与 https://py-feat.org/pages/models/ ；PyPI https://pypi.org/project/py-feat/
- 做什么：一个 `Detector` 对象跑完整流水线，输出 `Fex` 数据框。v1 模块化：检测 retinaface（MIT，默认）或 img2pose（CC BY-NC 4.0，附带 6DoF 头姿）；关键点 mobilefacenet/mobilenet/pfld（MIT）；AU 用 xgb（概率，MIT，默认）或 svm（二值）；注视 l2cs（MIT）；身份 arcface（权重非商用）或 facenet（MIT）；情绪 resmasknet（丢弃）。v2：单个 ConvNeXt-V2-Tiny 多任务网络一次出 20 AU、7 类情绪、效价/唤醒、注视、478 点、6DoF 头姿、52 blendshape，文档标「Non-commercial research only」。
- 怎么装：`pip install py-feat`（2.1.3，2026-09-07；Python ≥ 3.11；torch ≥ 2.5、torchvision ≥ 0.20、timm、xgboost ≥ 1.6、torchcodec ≥ 0.11、huggingface_hub、safetensors）；支持 `device='cuda'/'mps'/'cpu'`；权重从 HF Hub 自动下载。本轮核实：torchcodec 0.16.0 有 cp310–cp314 `manylinux_2_28_aarch64` 轮子，xgboost 3.4.1 有 `py3-none-manylinux_2_28_aarch64` 轮子——**aarch64 安装可行性成立**。
- 输出：逐帧 AU 概率（xgb）或二值（svm）、注视角、头姿、关键点、（情绪列丢弃）。
- 具体用法：面部通道一站式方案的候选：v1 组合 retinaface + mobilefacenet + xgb + l2cs 全 MIT，可商用；头姿在 v1 里要么用 img2pose（非商用）要么自己用关键点 PnP。v2 一次给齐 AU + 头姿 + 目光 + blendshape，黑客松（非商用）可直接用，商用需换。
- 风险：v2 多任务权重非商用；ArcFace 权重继承 InsightFace 非商用（身份识别本项目也不需要，直接禁用）；依赖多、版本新；无人报告过 DGX Spark 实测。
- 替代品：MediaPipe（更轻）；OpenFace 3.0；facetorch。

#### 8. OpenGraphAU / ME-GraphAU — B

- URL：https://github.com/lingjivoo/OpenGraphAU ；https://github.com/CVI-SZU/ME-GraphAU （IJCAI-ECAI 2022）
- 做什么：AU 关系图模型；ME-GraphAU 在 BP4D 出 12 AU、DISFA 出 8 AU；OpenGraphAU 用 BP4D、DISFA、RAF-AU、Aff-Wild2、CK+、CASME II 约 200 万张混合训练，输出 41 类（AU1–AU39 加左右不对称 AUL/AUR），ResNet-18/50、Swin-T/B 权重可选；作者称 RTX 3090 上 >50 FPS。
- 怎么装：clone + `pip install -r requirements.txt`（torch ≥ 1.4、torchvision、timm、easydict、pyyaml==5.4.1）——纯 PyTorch，aarch64 cu130 应可直接跑；`python demo.py --stage 2 --arch resnet50 --resume xxx.pth`。需要自己先做人脸检测与对齐裁剪（可用 MediaPipe 的框和关键点），或改走 facetorch（条目 5）。
- 输出：每帧 41 个 AU 的出现概率。
- 具体用法：面部通道「AU」正式来源（比 blendshape 近似更接近 FACS）；落成 AU12/AU15/AU14/AU1/AU4 的出现频率与持续时长统计，供预诊单「表情活动量」条目引用；不做情绪推断。
- 风险：权重放 Google Drive（国内不可达，提前搬运）；训练数据均为研究许可数据集，代码 Apache-2.0 但权重的商用地位需法务判断；最后 push 2025-08（13 个月）；Stars 少（~60）；pyyaml==5.4.1 在 Python 3.12 下可能装不上，放宽即可；无 aarch64 实测。
- 替代品：facetorch（同一权重的打包版）；OpenFace 3.0；LibreFace。

#### 9. SynergyNet（备选 3DDFA_V3） — C

- URL：https://github.com/choyingw/SynergyNet （3DV 2021）；https://github.com/wang-zidu/3DDFA-V3 （CVPR 2024 Highlight）
- 做什么：SynergyNet 联合 3DMM 参数与 3D 关键点，输出 68 个 3D 点、头姿欧拉角 + 平移、53k 点网格，作者称模型本体 RTX 2080 上 3000 FPS；3DDFA_V3 输出 3D 网格、68/106/134 点、头姿、8 区分割。
- 怎么装：SynergyNet 需编译 Cython 的 Sim3DR 与 FaceBoxes NMS，PyTorch ≥ 1.9；3DDFA_V3 官方装法钉 torch 1.12.1+cu102 并推荐 nvdiffrast（CUDA 扩展，sm_121 编译风险），但只取头姿可用 Cython 渲染器替代或干脆不装渲染。
- 输出：头姿角、3D 关键点、网格。
- 具体用法：只在需要「3D 关键点做更稳的 PnP 头姿」时借鉴；本项目不需要网格。facetorch 已把 SynergyNet 的 MobileNetV2 对齐头打包（免编译），需要时走那条路。
- 风险：Cython 编译在 aarch64 上无公开报告；3DDFA_V3 最后 push 2024-11（停更风险）；两者都是研究代码，无 pip 包。
- 替代品：6DRepNet；MediaPipe 头姿矩阵。

#### 10. LibreFace — C

- URL：https://github.com/ihp-lab/LibreFace （WACV 2024，2.0 版 FG 2026）；论文 https://arxiv.org/abs/2308.10713 ；项目页 https://libreface.github.io/ ；PyPI https://pypi.org/project/libreface/
- 做什么：轻量模型 + 特征级知识蒸馏；论文摘要：DISFA AU 强度 PCC 0.63，比 OpenFace 2.0 高 7%，推理快 2 倍；AU 检测、表情分类；2.0 新增注视角（`estimate_gaze()` / `estimate_gaze_video()`），项目页称 Gaze360 平均 MAE 9.40°、**GPU（NVIDIA L40S）118.9 FPS、CPU（AMD EPYC 9554）28.6 FPS**（不含前后处理）。2.0 用 SD3.5 生成身份 + LivePortrait 重定向真实 AU 动作，合成 240,000+ 帧 / 708 个身份混入训练以改善公平性（README 核实）。另有 .NET/ONNX NuGet 包与 OpenSense 组件（Windows）。
- 怎么装：`pip install libreface`（0.2.0，2026-05-21，requires_python ≥ 3.9）。PyPI 元数据硬钉 dlib==19.24.6、cmake==3.30.3、torch==2.0.0、torchvision==0.15.1、torchaudio==2.0.1、mediapipe==0.10.5、opencv-python==4.10.0.84、timm==1.0.9 等。本轮核实：torch 2.0.0 / torchvision 0.15.1 / torchaudio 2.0.1 在 PyPI 都有 cp38–cp311 `manylinux2014_aarch64` 轮子（CPU 版）；mediapipe 0.10.5 有 cp38–cp311 `manylinux2014_aarch64` 轮子。**结论：在 Python 3.10 或 3.11 的独立 venv 里能 CPU-only 装上**（dlib 需源码编译，cmake 由 pip 带入），但 torch 2.0.0 没有 CUDA 13 构建，**无法用 GB10 加速**；DGX OS 默认 Python 3.12 无对应轮子。
- 输出：逐帧 AU 强度 / AU 出现 / 表情标签（丢弃）/ 注视角。
- 具体用法：只作 AU 强度的对照实现；其「AU 强度 PCC vs OpenFace 2.0」的评测口径与「公平性（RAF-AU / AffWild2 跨性别、种族的 F1 标准差）」口径可借用到 BENCHMARK.md。
- 风险：USC research license（README 原话「Our code is distributed under the USC research license」；商用需联系 USC Stevens Center）；依赖硬钉、无 GPU；表情头是情绪标签。
- 替代品：OpenFace 3.0；OpenGraphAU / facetorch。

#### 11. L2CS-Net（附 ETH-XGaze、Gaze360 数据集） — C

- URL：https://github.com/Ahmednull/L2CS-Net ；论文 https://arxiv.org/abs/2203.03339 （ICIP 2022）；https://github.com/xucong-zhang/ETH-XGaze （ECCV 2020）；https://github.com/erkil1452/gaze360 （ICCV 2019）
- 做什么：对 pitch/yaw 分别做分类 + 回归双损失；MPIIGaze 3.92°、Gaze360 10.41°；`pip install git+https://github.com/edavalosanaya/L2CS-Net.git@main` 后有摄像头 demo 与 Pipeline 接口。ETH-XGaze 仓库是数据集基线（Python 3.5 / PyTorch 1.1 时代，测试用 dlib），README 明写 CC BY-NC-SA 4.0；Gaze360 仓库 2026-09-11 已归档，数据与代码为 Research License「仅限非商用研究」。
- 怎么装：纯 PyTorch，aarch64 可行；权重 Google Drive。
- 输出：pitch/yaw。
- 具体用法：py-feat v1 的默认注视模块就是它，直接用 py-feat 即可，不单独接。
- 风险：最后 push 2024-02（停更风险）；权重训自非商用数据集。
- 替代品：ptgaze；yakhyo/gaze-estimation。

#### 12. yakhyo/gaze-estimation — C（新增，ptgaze 替补）

- URL：https://github.com/yakhyo/gaze-estimation
- 做什么：注视方向回归的训练 + 推理仓库（~210★，MIT，最后 push 2026-02-14）；README 明写「All models are trained only on Gaze360 dataset」；权重：ResNet-18（43 MB）/ ResNet-34（81.6 MB）/ ResNet-50（91.3 MB）/ MobileNetV2（9.59 MB）/ MobileOne S0（4.8 MB），Gaze360 MAE 分别 12.84° / 11.33° / 11.34° / 13.07° / 12.58°；提供 `onnx_export.py` 与 `onnx_inference.py`；人脸检测用 uniface（RetinaFace）；权重放 GitHub Releases（国内一般可达）。
- 怎么装：`pip install -r requirements.txt` + onnxruntime（CPU）或 `onnxruntime-gpu` 1.30.0（PyPI 有 cp311–cp314 `manylinux_2_34_aarch64` 轮子，默认 CUDA 13 构建）；比 ptgaze 少 mediapipe / face-alignment / timm 一串依赖。
- 输出：pitch/yaw。
- 具体用法：ptgaze 依赖解析失败或速度不够时的替补，接同一套「注视角 ±θ + 开场标定」规则得目光接触比例。
- 风险：只在 Gaze360（户外、大角度）上训练，正对摄像头访谈场景的精度未知，MAE 11–13° 本身就大于我们 θ=10–15° 的判定阈值，**必须先用团队成员的标定视频验证再决定是否启用**；权重训自 Gaze360（非商用）→ 需替换；无 FPS、无 MPIIFaceGaze 权重（标「soon」）。
- 替代品：ptgaze；L2CS-Net。

#### 13. eye-contact-cnn（Chong et al. 2020） — C

- URL：https://github.com/rehg-lab/eye-contact-cnn ；论文 Chong E. et al., "Detection of eye contact with deep neural networks is as accurate as human experts", Nature Communications 11:6386 (2020), https://doi.org/10.1038/s41467-020-19712-x ，PMC7736573
- 做什么：在 4,339,879 张标注帧（103 人，57 人有 ASD 诊断）上训练的 CNN，输入第一人称（egocentric）视角的人脸框，输出每帧目光接触分数 [0,1]（>0.9 视为可信）；验证集 precision 0.936、recall 0.943，与受训人类编码者相当。
- 怎么装：`python demo.py`，默认 dlib 检测，可用 `--face` 传入外部人脸框绕开 dlib；依赖 PyTorch 0.4.0 时代 API，需移植到 torch 2.x；README 未给权重链接，需在仓库内确认。
- 输出：逐帧目光接触分数。
- 具体用法：借鉴其「目光接触 = 二分类 + 与人类编码者一致性」的验证设计，用于我们目光接触比例的盲评方案；若移植成功可作 MediaPipe 目光近似的对照。它假设相机在对话者眼睛附近（第一人称），我们的相机在屏幕上方，几何上接近但非完全一致。
- 风险：Georgia Tech Research Corporation 许可仅限非商用研究；最后 push 2024-08（停更风险）；训练人群为美国儿童/青少年互动场景。
- 替代品：ptgaze + 阈值规则。

#### 14. Gaze-LLE（fkryan/gazelle） — C（新增）

- URL：https://github.com/fkryan/gazelle ；论文 arXiv 2412.09586（CVPR 2025 Highlight）
- 做什么：冻结的 DINOv2 ViT-B / ViT-L 之上训练一个轻量注视解码器，做**第三人称「注视目标」估计（gaze following）**：输入整幅图（可选头部框；单人场景不给框也能用），输出图内注视热图（0–1）和「注视目标在 / 不在画面内」分数（VideoAttentionTarget 微调版）；六个检查点（vitb14 / vitl14，各有 GazeFollow、+inout、+inout_childplay 版本），只含解码器权重，DINOv2 骨干经 PyTorch Hub 自动下载；~860★，MIT，最后 push 2026-03-18。
- 怎么装：conda `environment.yml`，PyTorch + 可选 xformers；纯 PyTorch，aarch64 应可跑，无报告。
- 输出：热图 + in/out 分数。
- 具体用法：它回答的是「这个人在看画面里的什么」，不是「这个人是否在看摄像头/屏幕」；只有当咨询师与来访者同框、要量「看向咨询师的比例」时才有用。本项目是来访者对机器的场景，不接；作为「若日后做双人访谈录像的回顾分析」的线索保留。
- 风险：无 FPS 数据；DINOv2 骨干需联网下载；训练集 GazeFollow / VideoAttentionTarget / ChildPlay 的许可未核；输出与我们的 MSE 条目不直接对应。
- 替代品：ptgaze + 规则。

#### 15. RT-GENE / RT-BENE — C

- URL：https://github.com/Tobias-Fischer/rt_gene （RT-GENE ECCV 2018；RT-BENE ICCVW 2019）
- 做什么：自然环境下的实时注视估计与眨眼估计；`rt_gene_core` 为无 ROS 依赖的纯 Python 运行时，权重首次运行自动下载到 `~/.cache/rt_gene/model_nets`。
- 怎么装：PyTorch + OpenCV；官方 conda 环境只列 linux-64 / osx-arm64 / win-64，linux-aarch64 需自行 pip。
- 输出：注视角、眨眼概率。
- 具体用法：只借鉴 RT-BENE 的「眼块 → 眨眼概率」思路作为 EAR 的深度替代；本轮不接。
- 风险：CC BY-NC-SA 4.0，明写不允许商用。
- 替代品：EAR + MediaPipe eyeBlink。

#### 16. OpenFace 2.2 — C（文献对照）/ D（部署）

- URL：https://github.com/TadasBaltrusaitis/OpenFace ；许可 https://raw.githubusercontent.com/TadasBaltrusaitis/OpenFace/master/OpenFace-license.txt
- 做什么：C++ 工具，68 点 CLNF 关键点、头姿、17/18 个 AU 出现与强度、注视、HOG；是抑郁与情绪计算文献中最常见的特征基线。
- 怎么装：CMake 编译，依赖 dlib、OpenBLAS、OpenCV、Boost，C++17。aarch64 公开记录（本轮 gh api 核实状态）：#479 Jetson TX1 因 `-msse` 等 x86 编译选项失败（2018-06，次日关闭，7 条评论）；#805 Jetson Nano 能编译运行但头姿世界坐标有「巨大且恒定的偏差」（2019-11，已关闭）；#781 rpi4 构建失败（2019-10，已关闭）；**#1054 arm64 Mac 链接 libopenblas 失败（2023-08-17）仍开放、0 条评论**。三个已关闭的 issue 都不构成 aarch64 正式支持。
- 输出：CSV，每帧 AU_r（强度 0–5）、AU_c（出现）、gaze 角、pose。
- 具体用法：只做「文献口径对照」——评测报告里说明我们的 AU/注视/头姿指标与 OpenFace 2.2 的定义关系；不部署。
- 风险：CMU 非商用许可（「noncommercial internal research purposes」，不得分发/再许可）；最后 push 2024-06（停更风险）；aarch64 构建风险高。
- 替代品：OpenFace 3.0（同实验室、纯 Python）。

#### 17. NVIDIA TAO GazeNet + FPENet（NGC） — C

- URL：https://catalog.ngc.nvidia.com/orgs/nvidia/tao/models/gazenet ；https://catalog.ngc.nvidia.com/orgs/nvidia/tao/models/fpenet ；文档 https://docs.nvidia.com/tao/archive/5.3.0/text/model_zoo/cv_models/gazenet.html
- 做什么：GazeNet 输入人脸、左右眼 224×224 灰度块 + 25×25 facegrid，输出注视点 (X,Y,Z) 与注视向量 (theta, phi)，AlexNet 类多分支；FPENet 输入 80×80 灰度脸，输出 68/80/104 点 + 置信度。模型卡给 Jetson Nano FP16：GazeNet 87 FPS、FPENet 115 FPS；T4 分别 1698 / 2489 FPS。
- 怎么装：TAO 格式（模型加载密钥 `nvidia_tlt`），通过 TensorRT/DeepStream 6.0 部署；在 DGX Spark 上需用 CUDA 13 的 TensorRT 自建引擎，无公开验证。
- 输出：注视向量 / 关键点。
- 具体用法：只在「评委看重 NVIDIA 原生栈」时作为加分项考虑；其 Jetson arm64 数据说明 NVIDIA 路线在 ARM 上可行。
- 风险：NVIDIA Model EULA（NVIDIA AI Enterprise EULA 链接），商用条款需法务核对；模型老（AlexNet 骨干）；需要相机标定才能给出注视点；GazeNet 卡最后更新 2025-03，FPENet 2024-11。
- 替代品：ptgaze；MediaPipe。

#### 18. FaceXFormer — C

- URL：https://github.com/Kartik-3004/facexformer （ICCV 2025）
- 做什么：统一 Transformer 同时做人脸解析、关键点、头姿、属性、年龄/性别/种族、表情、可见性等 9 任务，宣称 33.21 FPS；权重在 HF `kartiknarayan/facexformer`。
- 怎么装：conda 环境文件钉 PyTorch 2.0.1 / cu117，需改成 cu130 aarch64；模型本体纯 PyTorch。
- 输出：头姿角、关键点等（不输出 AU）。
- 具体用法：只作头姿备选；其年龄/性别/种族/表情头与铁律冲突，全部禁用。
- 风险：许多头与项目伦理边界冲突；最后 push 2025-09。
- 替代品：6DRepNet。

#### 19. 反例：DeepFace emotion / fer / EmotiEffLib（HSEmotion） — D（作输出）/ C（作特征）

- URL：https://github.com/serengil/deepface （~23k，MIT，2026-09 活跃）；https://github.com/justinshenk/fer （~430，MIT，2026-06）；https://github.com/sb-ai-lab/EmotiEffLib （~1.1k，Apache-2.0，2026-06；前身 https://github.com/av-savchenko/hsemotion ~60）
- 做什么：七分类表情（愤怒/厌恶/恐惧/高兴/悲伤/惊讶/中性）标签与概率。
- 具体用法：铁律禁止作为输出。若心理学博士的盲评需要一个「传统情绪标签」对照组来证明 MSE 条目更有用，可在 BENCHMARK.md 里用其中一个作对照特征，但不进预诊单。
- 风险：标签直接就是「悲伤 72%」这类输出；训练数据多为摆拍表情数据集。

#### 20. PyAFAR — D

- URL：https://github.com/AffectAnalysisGroup/PyAFAR ；https://pyafar.org/ ；论文 ACII 2023 workshop https://ieeexplore.ieee.org/document/10388108/
- 做什么：成人 12 AU 出现 + 强度、婴儿 9 AU 出现，MediaPipe 检测 + PnP 头姿，输出 CSV/JSON。
- 怎么装：只提供 Windows / Ubuntu / Mac 可执行文件，GPU 仅 Linux/WSL2；GitHub 仓库经 API 核实只有 index.html、css、fonts、images、LICENSE、README、CNAME、resources，无 Python 源码。
- 风险：非商用许可（商用联系 Jeffrey Cohn）；最后 push 2024-12（停更风险）；可执行文件架构未标，aarch64 几乎不可能。
- 替代品：OpenFace 3.0 / OpenGraphAU / facetorch。

### 平台底座核实（决定「哪条路最省事」的硬事实）

- 操作系统：DGX OS 7 基于 Ubuntu 24.04，DGX Spark 最低 DGX OS 7.2.3（https://docs.nvidia.com/dgx/dgx-os-7-user-guide/index.html ）；Ubuntu 24.04 → glibc 2.39、系统 Python 3.12，满足 manylinux_2_28 / 2_34 轮子要求；但凡是只发到 cp311 的老轮子（LibreFace 那套钉版）要另开 3.10/3.11 venv（`uv venv -p 3.11` 或 deadsnakes）。
- PyTorch：官方 cu130 索引有 aarch64 轮子；PyTorch 论坛线程 https://discuss.pytorch.org/t/dgx-spark-gb10-cuda-13-0-python-3-12-sm-121/223744 中维护者 ptrblck 明确「all of our binaries for ARM built with CUDA >= 12.8 support DGXSpark already」，sm_121 与 sm_120 二进制兼容；启动时「cuda capability 12.1 … supported (8.0)-(12.0)」的警告可忽略（https://github.com/natolambert/dgx-spark-setup ）。jethac 的记录显示 torch 2.11.0+cu130 aarch64 在 GB10 上运行正常但 `get_arch_list()` 不含显式 sm_121（https://github.com/jethac/dgx-spark-hijinks/blob/main/docs/PYTORCH_SM121_SUPPORT.md ）。已知好用的容器：NVIDIA 官方 playbook 用 `nvcr.io/nvidia/pytorch:25.11-py3`（https://github.com/NVIDIA/dgx-spark-playbooks/tree/main/nvidia/pytorch-fine-tune ）。PyPI 上老版本 torch（如 2.0.0）的 aarch64 轮子全是 CPU 版，GPU 必须走 cu130 索引 + 新版 torch。
- ONNX Runtime GPU：PyPI 1.30.0（2026-09-10）文件列表含 `onnxruntime_gpu-1.30.0-cp311/312/313/314-manylinux_2_34_aarch64.whl`；官方 CUDA EP 文档写明自 1.27 起 PyPI GPU 包默认按 CUDA 13.0 构建，需 cuDNN 9；发布说明提到针对 SM121 的 GEMV 调优。社区更早的自建记录（NVIDIA 论坛 366157，2026-04；HF Jay0515 与 GitHub Albatross1382）提示：INT8 量化模型缺 sm_121 kernel，用 FP32/FP16；驱动建议 ≥ 580.173.02。结论：ONNX 路线已可行（yakhyo/gaze-estimation 可直接受益），但主路线不需要。
- MediaPipe aarch64 轮子史（本轮核实）：0.10.5（2023-09-15）cp38–cp311、0.10.18（2024-11-01）cp39–cp312 为 `manylinux2014_aarch64`；0.10.20（2024-12-13）、0.10.30、0.10.35（2026-04-27）无 aarch64 轮子；1.0.0（2026-07-27）起改为 `py3-none-manylinux_2_28_aarch64`。任何 `mediapipe>=0.10.20,<1.0` 的钉版在 aarch64 上都装不上，`>=0.10.30` 会自动跳到 1.0.x。
- 其他 aarch64 轮子（本轮核实）：torchcodec 0.16.0 cp310–cp314 `manylinux_2_28_aarch64`；xgboost 3.4.1 `py3-none-manylinux_2_28_aarch64`（2.1.0 起同时发 manylinux_2_28）；torch 2.0.0 / torchvision 0.15.1 / torchaudio 2.0.1 cp38–cp311 `manylinux2014_aarch64`（CPU）。
- dlib：所有依赖 dlib 的项目（LibreFace、ETH-XGaze 测试、eye-contact-cnn 默认检测）在 aarch64 上都要源码编译，能编但慢且 CUDA 支持不明；一律用 MediaPipe/RetinaFace 替换人脸检测。

### 证据档：这些信号在临床场景「做到了」什么（T1/T2）

| 条目 | 档 | 与本项目的关系 |
|---|---|---|
| Girard J.M., Cohn J.F. 等，"Nonverbal social withdrawal in depression: Evidence from manual and automatic analyses", Image and Vision Computing 32(10):641–647, 2014, DOI 10.1016/j.imavis.2013.12.007, PMC4217695 | T2 | 症状重时 AU12、AU15 减少、AU14 增多，头动幅度与速度减小；且手工 FACS 与自动分析结论一致——这是把「AU12/15/14 统计 + 头动统计」写进预诊单 MSE 条目的直接依据 |
| Alghowinem S. 等，"Head Pose and Movement Analysis as an Indicator of Depression", ACII 2013, pp. 283–288, DOI 10.1109/ACII.2013.53 | T2 | 头姿与头动特征可区分抑郁组，支持「头动量 / 低头」条目 |
| Chong E. 等，Nature Communications 11:6386, 2020, DOI 10.1038/s41467-020-19712-x（PMC7736573） | T2 | 自动目光接触检测可达人类专家水平（4,339,879 帧、103 人、57 人 ASD；precision 0.936 / recall 0.943），支持「目光接触比例」条目的可测性；模型本身非商用 |
| Turrisi R. 等，"Blendshape features meet action units: a clinical mapping for enhancing facial expression analysis", Computers in Human Behavior Reports, 2026-05, DOI 10.1016/j.chbr.2026.101125 | T2 | 10 位持证临床心理师对 MediaPipe 52 个 blendshape → AU 的映射做了独立标注与共识（88% 全体一致、98% 多数一致）；这是把 MediaPipe 路线的「AU 近似」写成可引用口径的依据（全文被 ScienceDirect 拦截，映射表需团队下载） |
| Skiendziel T., Rösch A.G., Schultheiss O.C., "Assessing the convergent validity between the automated emotion recognition software Noldus FaceReader 7 and Facial Action Coding System Scoring", PLOS ONE 2019, DOI 10.1371/journal.pone.0223905（PMC6797095，本轮全文 XML 核实） | T2 | 摘要：20 个 AU 的效度「中等」，最高效度为 AU1、5、9、17、27；Table 4：20 个 AU 的 F1 均值 0.63。Table 2（与手工 FACS 的 Spearman 相关，按表情条件）：AU2 最高 .60（惊讶）、AU20 最高 .56（悲伤）；**抑郁相关的 AU12 最高只有 .40（愤怒；高兴条件下 .08 ns，作者归因于天花板效应）、AU14 最高 .42、AU15 最高 .44、AU26 最高 .35**，AU15 的 F1 仅 0.48、AU20 的 F1 0.40——提醒我们 AU 统计必须标不确定度、只作观察不作判断；其「与手工 FACS 相关 + F1」的双口径验证设计可复用到盲评 |
| Zhao Y. 等（北京航空航天大学），"A Topology Standardized 3D Facial Dataset with Emotion and Action Unit Diversity for East Asians"（AST-Face），Scientific Data 2026-03-24，DOI 10.1038/s41597-026-07098-2（PMC13179375，本轮核实）；数据 https://osf.io/xk4f6/ | T2（数据集） | 98 名东亚青年（45 男 53 女，18–30 岁；披露族裔者中 39 名汉族 + 12 名少数民族：朝鲜族、蒙古族、土家族、回族、京族），每人 16 个网格（1 中性 + 6 基本表情 + 9 个 AU：AU01/04/06/09/12/18/20/27/43），52 人有同步三视角 RGB；CC BY-NC-ND 4.0；原始扫描、带纹理网格与 RGB 图像需签 DUA，标准化网格、形变场、关键点与 AU 标签免 DUA 公开——目前唯一找到的可用于「东亚面孔上 AU 工具是否靠谱」的小规模自检资源（含 AU12 与 AU20，正好覆盖 Girard 2014 的关键 AU 之一） |

**竞品名单（T3，只列名不算「做到了」）**

- Blueskeye AI TrueBlue（英国，围产期抑郁）：公司公告 2026-07-27 称已被 MHRA 接受为「registered Class I medical device」，自述「symptom checker, not a diagnostic tool」，交通灯式输出，模型基于 >2,000 名女性数据、「93% precision」为公司自述（https://www.blueskeye.com/news/blueskeyes-trueblue-becomes-an-mhra-registered-medical-device-for-perinatal-depression ）。ClinicalTrials.gov NCT06364488（本轮 API v2 核实）：Sponsor BlueSkeye AI，Interventional，Recruiting，start 2024-10-01，预计 n=125，主要终点为 12 周内器械相关不良事件率——尚无疗效 / 准确性发表。MHRA 公开注册库 PARD（pard.mhra.gov.uk）为 JS 应用，本轮无法抓取，**Class I 注册未能在监管数据库确认，故只能标 T3**；团队若手动在 PARD 搜到「Blueskeye」条目再升 T1。对本项目的用处：只借鉴「与 PHQ-9 等金标准量表对齐 + 先做安全性终点」的验证路径，不借鉴其分类输出。

### MSE 条目落地映射（面部通道只出「观察到什么」）

| MSE 观察条目 | 原始信号 | 一天路线（MediaPipe） | 升级路线 |
|---|---|---|---|
| 目光接触：良好 / 减少 / 回避（附比例、最长回避秒数、回避次数） | 注视角 + 头姿 yaw/pitch，会话开始 10 秒标定屏幕中心 | 虹膜点相对眼裂位置 + eyeLook* blendshape + 头姿矩阵 | ptgaze（ETH-XGaze）或 py-feat v1 L2CS；替补 yakhyo/gaze-estimation（ONNX） |
| 精神运动：迟滞 / 激越 / 正常（附头动幅度、角速度、静止占比） | 头姿角逐帧差分 | 头姿矩阵分解 | 6DRepNet 双路校验（或 facetorch 3D 对齐头） |
| 表情活动量：受限 / 适度 / 增高（附 AU 近似统计，不写情绪词） | AU 出现/强度或 blendshape 能量相对基线 | mouthSmile/mouthFrown/browDown/browInnerUp/mouthPress/jawOpen 等（标「blendshape 近似」） | OpenGraphAU 41 AU（裸仓库或 facetorch）或 OpenFace 3.0 AU 强度（AU12/AU15/AU14 对齐 Girard 2014；注意 Skiendziel 2019 显示这三个 AU 恰是自动编码效度最弱的一组） |
| 眨眼率、长闭眼 | EAR / eyeBlink | EAR 规则 + eyeBlinkL/R 互校 | RT-BENE（非商用，不接） |
| 低头时长 | pitch 低于阈值持续 | 头姿矩阵 | 6DRepNet |

所有阈值（θ、低头 pitch、活动量分档）由心理学博士在 20 个合成病例上定，脚本只输出数值与分档，不输出诊断词。

### 验证周（9/15–9/19）最小清单

1. Day 1（Spark-B）：`pip install mediapipe==1.0.1`，跑 FaceLandmarker（VIDEO 模式，开 blendshape + 矩阵），60 秒 720p 摄像头样本，记录 Grace CPU 上的 FPS 与四个信号的 CSV；`.task` 包提前下载并放进 references/。
2. Day 2：`pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130` 或直接用 `nvcr.io/nvidia/pytorch:25.11-py3`；装 sixdrepnet 与 ptgaze，各跑同一段视频，与 Day 1 结果对比偏差；确认权重下载源（6DRepNet 与 OpenGraphAU 的 Google Drive 权重先搬运到内网；ptgaze / facetorch / py-feat 走 HF Hub，准备镜像或提前缓存）。
3. Day 3（可选，二选一）：(a) `pip install "facetorch==1.0.0rc3"`（需 Python 3.10–3.12、torch 2.6–2.13 cu130），配置里禁用 fer / va / deepfake / embed / verify 头，只留 detector + au + align，看 41 AU 输出与 blendshape 近似的一致性；(b) 裸 OpenGraphAU ResNet-50 权重 + MediaPipe 裁剪。任一条装不顺，AU 就停在 blendshape 近似，不再投入。
4. 全程不碰 OpenFace 2.2、LibreFace pip（只在 x86 笔记本上跑对照）、PyAFAR、TAO。

### 空白区

搜过但没有找到合适资源的方向：

1. **在中国 / 东亚人群上验证过的开源 AU 检测器**：没有。BP4D、DISFA 为美国采集；MediaPipe blendshape 卡只有肤色公平性数据；LibreFace 2.0 的公平性只报到 RAF-AU / AffWild2 的性别、种族分组。只找到 AST-Face（Zhao 2026）可作小规模自检（9 个 AU，含 AU12/AU20）。建议：预诊单上把 AU 相关条目标「未在本地人群验证」，由博士盲评 20 例决定是否保留。
2. **面向「访谈中目光接触比例」的现成开源工具**：没有直接给「看屏幕比例」的工具；eye-contact-cnn 是第一人称视角且非商用；Gaze-LLE 是第三人称「看画面里什么」。建议：注视角 + 头姿 + 开场标定的确定性规则，自己写（≤100 行）。
3. **aarch64 + CUDA 13 上任何 AU / 注视 / 头姿工具的公开实测**：零条。facetorch 是唯一自述「CUDA 13.0 已验证」的相关库，但同一句把 ARM 归为实验性。DGX Spark 相关公开记录全是 LLM/微调/ONNX 通用构建，没有人跑过 OpenFace、py-feat、LibreFace。建议：验证周产出的 FPS 表本身就是 BENCHMARK.md 的一部分。
4. **商用友好且有权重的深度眨眼模型**：RT-BENE 非商用；BlinkFormer（BMVC 2023，https://github.com/desti-nation/BlinkFormer ）本轮核实为「找到但不可用」：6★、最后 push 2023-09-07、仓库根目录无 LICENSE 文件（README 挂 Apache-2.0 徽章但链接指向另一仓库 ziplab/SN-Net 的 LICENSE），不提供预训练权重，只有模型代码与 SynBlink 合成数据生成代码（5 万段 13 帧短片，百度网盘）。建议：EAR 规则 + eyeBlink blendshape 双路，放弃深度眨眼。
5. **「低头时长」「头动量」的临床阈值**：文献只给组间差异（Girard 2014、Alghowinem 2013），没有可用的切点。建议：只报相对会话基线的比值与原始统计，分档阈值交博士定。
6. **OpenFace 2.2 的 aarch64 Docker 镜像**：未找到。建议放弃。
7. **MediaPipe Python 在 Linux aarch64 上的 GPU delegate**：公开 issue（#5568、#6041、#6216）只有「无加速」或「不支持」的反馈。建议 CPU 路线，不折腾。
8. **NMPA 批准的面部行为类精神科辅助器械**：属市场章范围，本子方向未检索。

用过的检索式（WebSearch）：`PyAFAR Python Automated Facial Action Recognition github`；`mediapipe pypi aarch64 manylinux wheel linux arm64`；`DGX Spark PyTorch CUDA 13 aarch64 wheel sm_121 install`；`onnxruntime-gpu aarch64 CUDA 13 wheel SBSA DGX Spark`；`HSEmotion github Savchenko facial emotion recognition license`；`"Real-Time Eye Blink Detection using Facial Landmarks" Soukupová Čech 2016 EAR`；`MediaPipe Face Landmarker blendshapes 52 ARKit action units head pose transformation matrix python`；`"OpenFace 3.0" lightweight multitask facial behavior analysis arXiv 2025`；`Girard Cohn 2014 "Nonverbal social withdrawal in depression" …`；`NVIDIA TAO GazeNet FPENet HeadPoseNet NGC model card deprecated`；`OpenFace 2.2 build Jetson aarch64 ARM64 compile dlib OpenBLAS`；`MediaPipe Face Landmarker python GPU delegate linux supported CPU fps benchmark`；`PyTorch release notes sm_121 "DGX Spark" official support 2026 cu130 aarch64`；`build.nvidia.com spark playbook PyTorch NGC container …`；`"Blendshape features meet action units" clinical mapping …`；`Alghowinem 2013 "Head pose and movement analysis as an indicator of depression" ACII`；`Chong 2020 "Detection of eye contact with deep neural networks is as accurate as human experts"`；`Blueskeye AI facial behaviour mental health assessment clinical validation CE marked medical device`；`Blueskeye "TrueBlue" MHRA Class I registered medical device perinatal`；`Noldus FaceReader action unit validation peer-reviewed Skiendziel 2019 PLOS ONE FACS`；`DGX Spark "DGX OS" Ubuntu 24.04 Python 3.12 glibc version default`；`AVEC 2019 DAIC-WOZ baseline OpenFace gaze head pose action unit features depression severity`；本轮新增：`"LibreFace" WACV 2024 open-source toolkit facial expression analysis FPS "GTX 1080" OR "i9-13900K"`。本轮结构化核实用的接口：PyPI JSON（`/pypi/<pkg>/<ver>/json`）、`gh api repos/…`、Europe PMC REST（search + fullTextXML）、ClinicalTrials.gov API v2。

### 未核实线索

- **MHRA PARD 中 Blueskeye 的 Class I 条目**：pard.mhra.gov.uk 为 JS 应用，本轮无法抓取；只有公司公告。团队手动查到后可把上表竞品条目升 T1。
- **LibreFace 原论文（WACV 2024）的具体 FPS 数字**（审稿人从 PDF 抽取为 CPU i9-13900K 26.88 FPS、GPU GTX 1080 164.82 FPS）：CVF open access PDF 返回 403、arXiv 摘要页不含该数字，本轮只核实到摘要「比 OpenFace 2.0 快 2 倍」与 2.0 项目页的 L40S / EPYC 数字；原论文数字暂不进正文。
- **6DRepNet 的 BIWI 数字口径**：README 表给 70/30 划分 2.66°；审稿人提到 3.47°（可能是「300W-LP 训练、BIWI 测试」跨数据集口径），未逐表核对。
- Gaze-LLE 训练集 GazeFollow / VideoAttentionTarget / ChildPlay 的许可条款：未打开数据集页。
- AVEC 2016/2017/2019（DAIC-WOZ / E-DAIC）基线使用 OpenFace 的 AU、注视、头姿特征：只见搜索摘要；打开的 AVEC 2016 arXiv 摘要页（https://arxiv.org/abs/1605.01600 ）未写特征细节，故不进正文。
- NVIDIA Maxine AR SDK 的 Face Expression Estimation（blendshape 类输出）：未打开官网，印象中仅 x86 Linux/Windows，不适用。
- PyAFAR 可执行文件的 CPU 架构：wiki 未打开。
- SynergyNet、3DDFA_V3、FaceXFormer、ME-GraphAU、RT-GENE、ETH-XGaze、Gaze360 的论文页面：只核实了仓库自述的会议名，未打开 arXiv/会议页。
- OpenGraphAU 是否有独立论文：未核实。
- Noldus FaceReader 当前版本、许可与是否仍输出 AU：官网未打开，只核实了 2019 年第三方验证论文。
- "Digital assessment of nonverbal behaviors forecasts first onset of depression"（PubMed 39363541）：未打开，可能是更新的头动/表情前瞻证据。
- ONNX Runtime v1.30.0 GitHub 发布说明的日期在摘要中被误报为 2024 年；正文采用 PyPI 页面日期 2026-09-10。NVIDIA dgx-spark-playbooks 页面摘要给出的「2025-01-15 更新」与硬件发布时间矛盾，未采信。