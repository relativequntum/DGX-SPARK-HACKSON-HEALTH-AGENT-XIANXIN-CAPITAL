# 实时摄像头观察（最小可演示版）设计

- 日期：2026-09-29
- 状态：设计已确认，待实现
- 关联：Issue #8（集中交付期）；阶段二 `apps/multimodal/`、阶段三 `apps/emotion/face_body/`
- 期限：2026-09-30 演示

## 1. 目标

问诊时，患者可以自愿打开摄像头：

- 患者页有一个小窗，实时显示本人预览，并叠加面部打点和上身骨架；
- **患者页实时显示观察数值**，分两处：
  - 小窗下方的实时面板；
  - 每条患者回答结束后，对话气泡下方追加一行「本次回答的观察」；
  - 这两处的数值由浏览器端近似计算，仅作演示展示；
- 只有关键点**数值**离开浏览器，由 Spark 上的 face_body 做权威统计；
- 问诊结束后，医生工作台显示每条回答期间的**同期观察**（相对本人基线）：
  - 「对话记录」页签里，**每条患者回答**都带一行观察（对应选项 ①）；
  - 「重点」页签里，每条命中也带同样一行。

**成功标准**（明天实机演示）：

1. 经 SSH 隧道打开患者页，开启摄像头后，小窗能看到打点，实时面板的数值会跟着头部转动、眨眼变化；
2. 每说完一句话，患者页这句话下面出现一行本次回答的观察；
3. 完成一次问诊后，医生端「对话记录」里每条患者回答、「重点」里每条命中都带一行同期观察。数据不足时显示 `unknown`，未开摄像头时显示「未开启摄像头」；
4. 不开摄像头时，问诊流程与现在完全一致。

## 2. 已确认的决定

| 决定 | 选择 |
|---|---|
| 在哪里打点 | 浏览器端（MediaPipe Tasks Vision 网页版），画面不出患者电脑 |
| 与 judge 的关系 | 只做展示，**不进 judge**；judge 的 `channels` 保持为空 |
| 患者端可视化 | 小窗预览叠加打点，加实时观察面板，每条回答后追加观察行 |
| 医生端展示 | 「对话记录」每条患者回答都附观察（①），「重点」命中也附 |
| 默认状态 | 摄像头默认关闭，由患者主动开启，随时可以关闭 |
| 传输 | 走现有 SSH 隧道，不新增端口 |

## 3. 不做（留到赛后）

- 观察结果进 judge 的判断；
- 医生端实时观看画面或实时数值；
- 5 秒窗时间轴视图、「观察变化最明显的回答」排行（选项 ②④）；
- 面部动作 9 项与头姿细项的展开视图（选项 ③）；
- 用「基本信息问答」一段做基线（MVP 用开启摄像头后的前 5 秒）；
- 语音情感通道。

## 4. 架构与数据流

```text
患者浏览器 (127.0.0.1:8010/triage.html)
  camera-observe.js
    getUserMedia(video) → FaceLandmarker + PoseLandmarker（VIDEO 模式，约 5 fps）
    ├─ 小窗 canvas：预览 + 打点（只在本机）
    └─ 每 2 s 一批 → POST 127.0.0.1:8110/api/observe/<consultId>（只含数值）
                                   │
Spark  doctor_service (8110)       ▼
    校验 → 追加写 <OBS_DIR>/<sid>.frames.jsonl（服务器时间，权限 600）
                                   │
Spark  emotion-judge-watch（阶段三常驻服务）
    会话结束（有总结或 180 s 无新内容）且 frames 比 observe 新
    → face_body/live.py：还原逐帧记录 → 本人基线 → 按回答切段统计
    → <JUDGE_OUT>/<sid>.observe.json（与 judge.json 同目录）
    不调用大模型，也不等待模型空闲
                                   │
Spark  doctor_service /api/doctor/sessions/<sid>/highlights
    按 t 把同期观察附到每条命中上 → doctor.js「重点」页签多一行
```

会话编号：患者页的 `state.consultId`（`triage.js:50`，由 `/offer` 传给 LiveTalking 作为固定会话 ID）。它就是问诊记录的文件名，也是 judge 结果的会话编号，所以三处天然对齐。

## 5. 组件

### 5.1 患者页：`apps/multimodal/web/camera-observe.js`（新文件）

- **界面**：
  - `.mic-bar` 里加开关「摄像头观察」，默认关闭。开启前弹出一次说明：「画面只在本机处理，只把面部/姿态关键点数值发给系统；可随时关闭；不开也能正常问诊。」
  - 开启后，`.video-shell` 右下角出现 `160×120` 的小窗（该角目前空闲，见 `triage.css:193`），包含：
    - `<video>`，镜像显示；
    - 同尺寸的 `<canvas>`，画面部关键点的稀疏子集（约 70 点）和上身骨架（肩、肘、腕、髋）；
    - 小窗上方常驻角标「摄像头观察中 · 画面只在本机处理」。
- **加载**：动态 `import()` 同源的 `/vendor/mediapipe/vision_bundle.mjs`，wasm 目录为 `/vendor/mediapipe/wasm`，模型为 `/vendor/mediapipe/face_landmarker.task` 和 `/vendor/mediapipe/pose_landmarker_full.task`。
  - 加载失败时，开关变灰并提示「摄像头观察不可用」，不影响问诊。
- **打点**：
  - FaceLandmarker：`runningMode: "VIDEO"`、`numFaces: 1`、`outputFaceBlendshapes: true`、`outputFacialTransformationMatrixes: true`；
  - PoseLandmarker：`numPoses: 1`；
  - 用 `requestAnimationFrame` 节流到约 5 fps。
- **每帧只保留下列数值**（字段见第 6 节）：
  - face_body 用到的 blendshape 分数（`features.py:14-24,46-55`，共 26 个：`eyeLook{Out,In,Up,Down}{Left,Right}`、`eyeBlink{Left,Right}`、`browInnerUp`、`browOuterUp{Left,Right}`、`browDown{Left,Right}`、`cheekSquint{Left,Right}`、`eyeSquint{Left,Right}`、`mouthSmile{Left,Right}`、`mouthFrown{Left,Right}`、`mouthPress{Left,Right}`、`jawOpen`；`live.py` 里定义为常量 `CAM_BLENDSHAPES`，JS 端照抄一份，单元测试核对两边一致）；
  - 4×4 头姿矩阵；
  - 前 25 个姿态点的 `x, y, visibility`。
- **上传**：
  - 每 2 秒一批，`fetch` POST 到 `${location.protocol}//${location.hostname}:8110/api/observe/${consultId}`，与 `doctor.js:44-48` 的基址逻辑一致；
  - 失败时丢弃该批并在控制台记录，不重试、不阻塞；连续 5 批失败时提示一次「观察数据未能上传」。
- **患者端实时观察**（浏览器端近似计算，只用于展示，不上传计算结果；权威数值以医生端为准）：
  - 计算放在独立的纯函数模块 `camera-metrics.js`，不碰 DOM，可以用 node 跑测试。口径照搬 face_body：
    - 头部左右转头、低头抬头的角度：由头姿矩阵换算（与 `live.py` 使用同一行列序）；
    - 目光：`gaze_h`、`gaze_v` 取 blendshape 差值，公式同 `features.py:46-50`；取开启后前 5 秒的中位数作为本人基线；平滑后偏离超过 0.25 记为「偏离」，与 `windows.py` 的阈值一致；
    - 眨眼：`eyeBlinkLeft/Right` 的均值，按滞回判定，闭眼阈值 0.5、睁眼阈值 0.3，与 `windows.py` 一致；
    - 手触脸：手腕与鼻子的距离小于 0.18，且可见度大于 0.5；
    - 小动作：同一关节相邻帧位移的均值 ×1000。
  - **实时面板**（小窗下方，约每 0.5 秒刷新一次）：
    - 内容：`左右转头 +12° · 低头 −5° · 本次回答 眨眼 3 次 · 目光偏离 20% · 手触脸 否`；
    - 基线未就绪（开启不足 5 秒）时显示「正在建立本人基线…」；
    - 检出不足时，对应项显示 `—`。
  - **每条回答的观察行**：
    - 以患者这句话进入对话流为分界点，挂在 `triage.js` 的 `onUserText`（`:698`）；
    - 统计区间为「上一次助手回复结束」到「这一刻」，统计后清零，开始累计下一段；
    - 在该条患者气泡下方追加一行小字：`本次回答观察：目光偏离 20% · 眨眼 18 次/分 · 手触脸 0% · 小动作 0.6`；
    - 帧数不足（少于 6 帧）时显示「观察数据不足」。
  - 面板和观察行都附一个小的说明图标，悬停显示「这些是摄像头观察到的动作数值，不代表情绪或健康状况」。
  - 面板可以单独收起；关闭摄像头时一并隐藏。
- **生命周期**（挂到 `triage.js` 现有函数）：
  - 在 `enableSessionUI`（`:1049`）之后允许开启；
  - `hideAvatarToStart`（`:784`）、`closeAvatar`（`:805`）、`beforeunload`（`:1212`）时停止采集并释放摄像头；
  - `consultId` 为空时不上传；
  - `?demo=1` 时可以开启小窗打点，但不上传。
- **不做**：录像、截图、缓存画面。

### 5.2 静态资源：`15_setup_camera_assets.sh`（新脚本，放在 `apps/multimodal/deploy/livetalking/`）

- 在 Spark 上把 MediaPipe Tasks Vision 网页版（`@mediapipe/tasks-vision`，pin 一个 0.10.x 或更新的版本，实现时在 npm 确认最新稳定版并写进 env.sh 的 `CAM_TASKS_VISION_VERSION`）放到 `$APP_DIR/web/vendor/mediapipe/`：
  - 运行文件：`vision_bundle.mjs`、`wasm/*`；
  - 获取方式：`npm pack`，读取 `PROXY`（来自 `env.local.sh`）；也可以用 `CAM_ASSETS_TGZ=<本地 tgz>` 离线安装。
- 两个 `.task` 模型从 `$HOME/emotion-models/mediapipe/` 复制过来，按 `apps/emotion/face_body/models.py` 里的 sha256 校验。
- 幂等。结束前自检：用 `curl -sI` 检查 `vision_bundle.mjs`、一个 `.wasm`、两个 `.task` 返回 200，并打印 `.wasm` 的 Content-Type。
- 这些文件**不进仓库**（体积大、第三方二进制）。`.gitignore` 加上 `apps/multimodal/web/vendor/`。
- `13_deploy_web.sh` 的 `FILES` 加入 `camera-observe.js`、`camera-metrics.js`。

### 5.3 接收接口：`doctor_service.py`

- 新增 `POST /api/observe/{sid}`：
  - `sid` 与现有路由使用同一正则和防穿越检查（`:233`、`:265`）；
  - 请求体 ≤ 64 KB，`frames` ≤ 50 条，每条字段按白名单逐项校验：
    - 数值必须有限；
    - `bs` 的键必须在 `CAM_BLENDSHAPES` 内（doctor_service 与阶段三不同 venv、不能 import，复制一份常量，单元测试核对三处——live.py、doctor_service、camera-observe.js——一致）；
    - `m` 长度为 16；
    - `p` 为 25×3；
  - 不合格的整批丢弃，返回 400；
  - 时钟换算：`t = recv_time - (sent_ct - ct)/1000`（服务器秒），写入每条记录；
  - 追加写 `<OBS_DIR>/<sid>.frames.jsonl`（目录 700、文件 600），单文件上限 20 MB，超过后返回 413；
  - 返回 `{"ok": true, "accepted": n}`。
- 配置：
  - `DOCTOR_OBS_DIR` 默认 `$HOME/livetalking-logs/observations`；
  - `DOCTOR_OBSERVE=1` 默认开启，设为 `0` 时返回 404。
- CORS：`allow_methods` 从 `["GET"]` 改为 `["GET", "POST"]`，`allow_headers` 包含 `Content-Type`。其余接口仍然只读。
- `/health` 增加 `obs_dir`、`obs_dir_exists`、`observe_enabled`。
- 只依赖标准库和 fastapi，不引入 numpy（`doctor-venv` 没有 numpy）。

### 5.4 统计：`apps/emotion/face_body/live.py`（新文件）+ `judge/watch.py` 集成

- `load_frames(path) -> list[dict]`：读取 frames.jsonl，按服务器时间 `t` 排序。
- `to_frame_record(frame, t0)`：用现有纯 numpy 函数还原 `analyze.frame_record` 同形的记录：
  - 头姿用 `features.euler_from_matrix`；
  - 目光、眨眼、AU 用 blendshape 相关函数；
  - 姿态点用 `SimpleNamespace` 包装后调 `features.pose_features`；
  - `t` 改为相对 `t0`（第一帧）的秒数。
  - **矩阵行列序**必须在实现时核实：MediaPipe JS 的 `Matrix.data` 可能是列主序，与 Python 的 numpy 4×4 不一致。浏览器按原样发送，由 `live.py` 统一转换。
- `build_observation(frames, record_events)`：
  - 基线：`windows.individual_baseline`，取第一帧后 5 秒内；
  - 切段：对每个患者回答事件（问诊记录 `kind == "user"`，时间 `t_u`），区间为「此前最近一条 assistant 事件的 `t`，`t_u`」，最长截取 60 秒；
  - 统计：用 `windows.aggregate`，传入会话基线，窗长为区间长度，`min_frames=6`，`min_ratio=0.5`；
  - 每段输出：`t`（等于 `t_u`）、`interval`、`frames`、`face_status`、`body_status`，以及 `gaze_away_ratio`、`blink_per_min`、`head_motion_deg_per_frame`、`hand_face_ratio`、`body_motion_x1000`（通道 unknown 时对应字段为 null）；
  - 另给出会话层：`camera_frames`、`face_detect_ratio`、`pose_detect_ratio`、各指标的会话中位数（供医生端标 ↑）。
- 输出 `<JUDGE_OUT>/<sid>.observe.json`，`schema_version: "face_body-live-0.1"`，写入方式为临时文件加 rename。
- `watch.py`：每轮扫描时，对「已结束」的会话（判断标准与 judge 相同：有总结，或 180 秒无新内容），如果存在 `<OBS_DIR>/<sid>.frames.jsonl` 且比 observe.json 新，就调用 `live.py` 生成。这一步不走 `PoliteBackend`，也不占模型；出错时只记异常类名，不影响 judge。
- 配置：`spark.env` 增加 `EMOTION_OBS_DIR`，默认 `$HOME/livetalking-logs/observations`。

### 5.5 医生端展示

- `doctor_service` `/highlights`：
  - 读取 `<JUDGE_DIR>/<sid>.observe.json`；
  - 对每条命中，按 `abs(hit.t - seg.t) < 0.5` 找到对应段，附上白名单字段 `observe`；
  - 顶层加 `camera`（有没有 frames）和 `observe_ready`；
  - 顶层再加 `observe_segments`：全部回答段，白名单字段加 `t`，供「对话记录」使用。这样就不用新开接口，doctor.js 已经在轮询 `/highlights`。
  - judge 结果还没出来时（`ready=false`），`/highlights` 也要照常返回 `observe_segments`，这样观察比 judge 先出来时，对话记录也能先显示。
- `doctor.js`「对话记录」页签（①）：新增 `markObserve(segments)`，参照 `markHits`（`:404`）的写法：
  - 按 `data-t`（`:435-447` 的匹配方式）找到每条患者消息 `li.msg`，在气泡下方追加一行 `.msg-obs`，格式与下面「重点」页签那一行相同；
  - 找不到对应段的患者消息不追加；
  - 没有开摄像头时，整段对话只在最前面显示一次「本场未开启摄像头」，不在每条下面重复。
- `doctor.js` `hitHTML`（`:356-372`）：在 `.hl-ev` 之后插入一行 `.hl-obs`，格式如下：
  - 通道正常：`同期观察（相对本人基线）：目光偏离 30% · 眨眼 18 次/分 · 手触脸 10% · 小动作 0.8`，某项超过会话中位数 1.5 倍时加 `↑`；
  - 通道 unknown：`同期观察：检出不足（unknown）`；
  - 没有 frames：`未开启摄像头`。
  - `loadHighlights` 的签名（`:424`）要把 observe 算进去，否则数据更新后不会重画。
- 离线演示 `buildDemo()`（`:208-226`）：给示例命中加 `observe`，同时给出 `observe_segments`，至少覆盖一条正常、一条 unknown。患者页的 `renderDemo()`（`triage.js:1227`）也给示例回答加上观察行。

### 5.6 文档

- `README.md`：在「它能做什么」和架构图中加入实时摄像头观察；关键数据表写明「浏览器端约 5 fps」。
- `docs/safety-and-privacy.md`：说明实时问诊可选摄像头观察、默认关闭、画面不出浏览器、Spark 只存数值及其位置、如何关闭（页面开关 / `DOCTOR_OBSERVE=0`）。
- `apps/emotion/face_body/README.md`：新增「实时通道（浏览器打点）」一节。
- `docs/实机测试操作手册.md`：增加开启摄像头的步骤和预期效果，以及常见问题（摄像头权限、小窗黑屏、观察显示 unknown）。
- `THIRD_PARTY_NOTICES.md`：加入 `@mediapipe/tasks-vision`（Apache-2.0，部署时下载，不随仓库分发）。
- `apps/multimodal/deploy/livetalking/README.md`：部署表加入 15 号脚本。

## 6. 数据格式

**上传批**（`POST /api/observe/<sid>`）：

```json
{
  "v": "cam-0.1",
  "sent_ct": 1790670000123,
  "frames": [
    {
      "ct": 1790670000001,
      "f": {"bs": {"eyeBlinkLeft": 0.02, "eyeLookOutLeft": 0.1}, "m": [16 个数]},
      "p": [[0.51, 0.32, 0.99], "…共 25 组"]
    },
    {"ct": 1790670000201, "f": null, "p": null}
  ]
}
```

- `f` 为 null 表示这一帧没有检出人脸；`p` 为 null 表示没有检出姿态。
- **frames.jsonl** 每行：`{"t": 服务器秒, "f": …, "p": …}`，不保存 `ct`。
- **observe.json** 结构：

```json
{
  "schema_version": "face_body-live-0.1",
  "notice": "…",
  "session_id": "…",
  "camera_frames": 0,
  "face_detect_ratio": 0.0,
  "pose_detect_ratio": 0.0,
  "baseline": {},
  "medians": {},
  "segments": []
}
```

## 7. 错误处理与降级

| 情况 | 行为 |
|---|---|
| 浏览器不支持、没有摄像头、用户拒绝授权 | 开关恢复为关闭，toast 提示，问诊照常 |
| vendor 资源加载失败 | 开关变灰「摄像头观察不可用」 |
| 上传失败 | 丢弃该批；连续 5 次失败提示一次 |
| 8110 未转发 | 同上（上传失败） |
| live.py 出错 | watch 日志只记异常类名，不生成 observe.json；医生端显示「观察结果暂不可用」 |
| 会话中途关闭摄像头 | 之后的回答段帧数不足，显示 unknown |

## 8. 隐私与合规

- 摄像头单独授权、默认关闭、常驻可见提示、随时可关（决策记录第 23 条）。
- 画面只在浏览器内存中处理，不录像、不截图、不上传（`apps/emotion/README.md:13`）。
- Spark 只存数值（blendshape 分数、头姿矩阵、25 个姿态点坐标），不存图像，也不做身份识别。
- 医生端只展示相对本人基线的观察数值，**不出情绪标签**，数据不足标 `unknown`（决策记录第 11、12、22 条）。
- 仅用于演示和虚构测试；正式试用前需补充保留期限和删除流程（写进隐私文档的待办）。

## 9. 测试

- **单元测试**（`apps/emotion/face_body/tests/test_live.py`，纯 numpy）：
  - 帧还原与字段；
  - 矩阵转换（已知 yaw 的合成矩阵）；
  - 基线；
  - 按回答切段（包括无帧、帧数不足、只有姿态、只有人脸的情况）；
  - 会话中位数；
  - 输出 schema。
- **接口测试**（`doctor_service` 用 FastAPI TestClient）：
  - 合法批写入；
  - 非法字段 / 超限 / 非法 sid 返回 400 或 413；
  - `DOCTOR_OBSERVE=0` 返回 404；
  - CORS 预检允许 POST；
  - `/highlights` 附 observe；
  - 原有接口不变。
- **watch 集成测试**：有 frames 且会话结束时生成 observe.json；frames 未更新不重复生成；live.py 出错不影响 judge。
- **浏览器端指标**（`camera-metrics.js`，用 node 跑）：
  - 准备一组合成帧，分别交给 `camera-metrics.js` 和 `live.py`/`windows.py` 计算；
  - 核对：眨眼次数、目光偏离比例（同一基线）、手触脸比例一致，头部角度相差 < 0.5°；
  - 核对：`CAM_BLENDSHAPES` 在 `camera-metrics.js`、`live.py`、`doctor_service.py` 三处一致。
- **前端**：
  - `node --check camera-observe.js camera-metrics.js`；
  - 本机无头 Chrome（`--use-fake-device-for-media-stream --use-fake-ui-for-media-stream`）加本地静态服务器和本地 doctor_service，把「开关 → 加载 → 打点 → 上传 → 写 frames.jsonl」整条链路跑通（假摄像头里没有人脸，预期 `f` 为 null）。
- **矩阵行列序核实**：选一张有人脸的测试图片，分别用 Python mediapipe 和浏览器端计算欧拉角，结果应一致（差 < 2°）。
- **实机**：由负责人按操作手册手测。

## 10. 部署（Spark）

1. 合并后运行 `15_setup_camera_assets.sh`，自检通过；
2. 运行 `13_deploy_web.sh`，同步 `camera-observe.js` 和修改后的 `triage.*`；
3. 运行 `14_setup_doctor_console.sh`，重启 doctor_service，带上新接口；
4. 运行阶段三 `deploy_spark.sh`，更新 face_body 和 watch，并重启 `emotion-judge-watch`；
5. LiveTalking **不需要重启**。

## 11. 风险

| 风险 | 缓解 |
|---|---|
| JS 与 Python 的矩阵行列序不一致，头姿全错 | 第 9 节的核实步骤；`live.py` 统一转换 |
| `.wasm` 的 MIME 不对，无法流式编译 | 15 号脚本自检 Content-Type；不对时改用 `wasmBinaryPath` 的非流式加载，或给静态路由补 MIME |
| Spark 下载 npm 包失败 | `CAM_ASSETS_TGZ` 离线安装：在开发机下载，由部署时拷过去 |
| 低配笔记本上打点卡顿 | 帧率降到 3 fps；打点只画稀疏子集 |
| 患者端到服务器的时钟偏差 | 按批校准；切段用服务器时间 |
| 问诊记录的 `t` 是「识别完成」时刻，不是开口时刻 | 区间取「上一句提问 → 本句识别完成」，能覆盖听题和作答；文档里说明 |
| 患者看到观察数值后产生误解或焦虑 | 措辞只写动作数值，不做评价；加说明图标；面板可以收起；正式试用前重新评估是否对患者展示 |
| 患者端近似值和医生端权威值不一致 | 口径照搬 face_body，并用合成帧做一致性测试；患者端文案注明「近似」 |
