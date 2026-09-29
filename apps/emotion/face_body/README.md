# face_body · 面部与身体观察通道（阶段三）

把一段视频变成**按时间窗的可观察量**：头姿、目光偏离、眨眼、面部动作单元（AU）的 blendshape 近似、坐姿与小动作。
来自 2026-09-22 本机 spike（`spike-语音/face_body.py`、`annotate.py`），入库时整理成模块并补了测试。

**不做什么**：不做人脸识别（不认人、不比对身份），不做表情或情绪分类，不给「悲伤 72%」这类标签
（`apps/emotion/research/决策记录.md` 第 11、12 条）。数值只和**本人基线**比，待医务人员结合问诊判断。

## 怎么跑

```bash
# 仓库根目录。依赖：mediapipe==1.0.1（会带上 opencv-contrib-python）、numpy、pillow；演示视频转 H.264 另需 ffmpeg 或 imageio-ffmpeg
python -m apps.emotion.face_body fetch-models                 # 下载 2 个 MediaPipe 模型（共 13MB）并校验 sha256
python -m apps.emotion.face_body analyze 视频.mp4             # → outputs/face_body/视频.face_body.json + 终端摘要
python -m apps.emotion.face_body annotate 视频.mp4            # → 叠加打点的演示视频 + 关键帧（含人脸，只在本机看）
python -m apps.emotion.face_body record --check               # 开发机：看哪些摄像头能开
python -m apps.emotion.face_body record --sec 40 --out outputs/face_body/recordings/me.mp4   # 录自己，带逐帧时间戳

# 测试（纯 numpy，不需要 mediapipe 和模型）
python -m pytest apps/emotion/face_body/tests -q
```

- 模型目录：`--models` > 环境变量 `FACE_BODY_MODEL_DIR` > 本包下的 `models/`（`.gitignore` 已挡住，权重不入库）。
  Spark 上直连 Google storage 慢，可 `fetch-models --proxy http://<局域网代理>`。
- `analyze` / `annotate` 加载模型前先校验 sha256，对不上（文件被换过或下载不完整）直接报错，重跑 `fetch-models` 即可。
- 视频旁边如果有 `视频.mp4.stamps.json`（`record` 录的逐帧毫秒时间戳），按它对齐时间；没有就按标称帧率推算。
- Windows 上 OpenCV 打不开含中文的视频路径：视频和输出目录请放在纯英文路径下。模型已改成读进内存再加载，不受此限。

## 输出（`*.face_body.json`，`schema_version: face_body-0.1`）

顶层：视频名、时长、帧数、处理速度、人脸 / 姿态检出率、`min_ratio` / `min_frames`（给数的门槛）、本人基线、
模型文件 sha256、mediapipe 版本、`notice`（不做什么）。
`windows[]` 每个时间窗（默认 5 秒）。末窗不足半个窗长时并入前一窗（所以最后一窗最长 1.5 个窗长，`t1` 是视频末尾）；
整段视频不足半个窗长时只有一个窗，记 `unknown`，短片段请把 `--window` 调小：

| 字段 | 含义 |
|---|---|
| `face_status` / `body_status` | 该窗检出率 ≥ 0.5 且检出帧 ≥ 10 为 `ok`，否则 `unknown`，**unknown 时不给该通道的数**。身体通道只算**双肩都可见**（visibility > 0.5）的姿态帧：任一肩不可见时肩倾、肩宽、前倾没有依据，这帧不算检出 |
| `head.yaw / pitch / roll` | 头姿角度（度）的均值、标准差、帧数；`motion_deg_per_frame` 头动量 |
| `gaze.away_ratio` | 相对本人基线偏离的帧比例：目光偏移 > 0.25 或 yaw 偏 > 20° 或 pitch 偏 > 15°（9 帧中位数平滑后） |
| `blink.count / per_min` | 眨眼次数与每分钟次数（滞回：> 0.5 判闭、< 0.3 判开）；跨窗的一次眨眼只算在开始闭眼的那个窗 |
| `au_proxy` | AU1、2、4、6、7、12、15、24、26 的 blendshape 均值（0–1），是近似，不是 FACS 编码 |
| `body` | 肩倾角、肩宽、躯干前倾（髋也可见的帧才有）、手触脸帧比例、小动作量（同一关节前后帧位移 × 1000） |

本人基线 = 前 5 秒有人脸帧的中位数（决策记录第 22 条）；前 5 秒没有人脸就用全部人脸帧，`baseline.source` 会写明。

## 隐私与边界

- `analyze` 只在内存里处理帧，输出只有数值，不存任何图像。
- `annotate` 的输出**含人脸**，只用于本机演示：不入库、不上传、演示完删掉；不要拿真实患者的视频来画。
- `record` 录的是你自己：只留本机。`outputs/` 已被 `.gitignore` 挡住。
- 摄像头观察需要独立授权和屏幕可见提示，来访者可随时切到「只做问卷、不做观察」（决策记录第 23 条）。
  本模块只是离线分析工具，实时接入数字人问诊时由集成方负责这些提示。

## Spark 实测（2026-09-26）

部署见 `apps/emotion/deploy/README.md`（`setup_spark.sh` 六步，第 6 步装常驻的自动判断服务 `emotion-judge-watch`）。用数字人自带的形象源视频（5 秒 125 帧）跑：人脸与姿态检出率都是 1.0，5 秒窗 `face_status` / `body_status` 都是 `ok`；`annotate` 经 imageio-ffmpeg 转成 H.264，面板字体用 Noto Sans CJK。
这组数是 #13 改口径（双肩可见才算姿态检出、短末窗并窗、检出帧下限）之前测的。

## 已知限制

- 目光只用 blendshape 的 eyeLook* 近似，没有视线估计模型；阈值 0.25 / 20° / 15° 来自一次本机校准，需要更多录制再定。
- AU 是 MediaPipe blendshape 的近似映射，不是 OpenFace / Py-Feat 的 AU 强度；真 AU 模型未接。
- 单人：画面里多个人时只取检出的第一个。
- 小动作量比的是相邻两个身体检出帧；中间隔着没检出（或肩不可见）的帧时，位移按两帧之间的总位移算，会偏大。
- 处理速度（面部 + 姿态两个模型一起，CPU）：DGX Spark 约 9 帧/秒（数字人形象视频 512×512），开发机约 22 帧/秒（640×480）。离线处理够用；将来实时接入要降帧（`--stride 3`）。
- 实时通道（患者浏览器摄像头 → Spark）未接，现在是离线处理视频文件。

## 目录

```text
features.py   逐帧：矩阵→头姿、blendshape→目光/眨眼/AU 近似、姿态点→坐姿与关节坐标（纯 numpy）
windows.py    时间窗聚合、本人基线、unknown 判定、报告（纯 numpy）
models.py     模型登记（官方地址 + sha256）、下载与校验
analyze.py    视频 → 报告（mediapipe + opencv，延迟导入）
annotate.py   演示视频 + 关键帧
record.py     开发机录像
__main__.py   命令行
tests/        纯 numpy 的单元测试
```
