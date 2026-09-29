# MediaPipe 网页版头姿矩阵的行列序与资源加载（核实记录）

- 日期：2026-09-29
- 关联：`docs/superpowers/specs/2026-09-29-live-camera-observation-design.md` §5.1、§5.4、§9「矩阵行列序核实」、§11 风险表
- 结论：**`MATRIX_LAYOUT = "col"`**。网页版 `facialTransformationMatrixes[0].data` 是列主序；
  `apps/emotion/face_body/live.py` 与 `apps/multimodal/web/camera-metrics.js` 先按平移所在位置自动判断，判断不了时按 `col`。

## 1. 版本

| 项 | 值 |
|---|---|
| npm 包 | `@mediapipe/tasks-vision@1.0.1`（2026-09-29 的 `latest`；`nightly` 为 1.1.0-rc，不用） |
| tgz 校验 | `sha512-rvRE2FmAZ6ZxKSw7wq+e+jQDpN3t1B/tD2mJz9SmAzb1msoDkd4dMoE4wAh8Z30Um0PQwLiHr9QtomhmXk3aUQ==`（npm 官方源与 `registry.npmmirror.com` 一致） |
| 许可 | Apache-2.0（包内 `package.json`） |
| 阶段三 Python 版 | `mediapipe==1.0.1`（Spark 的 `~/emotion-venv`），同一套 `.task` 模型 |

包内文件：`vision_bundle.js`（IIFE，定义全局 `Vision`）、`vision_bundle.mjs`（ES 模块）、`vision_bundle.cjs`、
`wasm/vision_wasm_internal.{js,wasm}`、`wasm/vision_wasm_nosimd_internal.{js,wasm}`、`wasm/vision_wasm_module_internal.{js,wasm}`（约 11 MB/个）。

## 2. 行列序

**源码依据**：网页版把 `MatrixData` 的 `packed_data`（proto 字段 3）原样拷进 `Matrix.data`，不看 `layout`（字段 4）：

```text
facialTransformationMatrixes.push({rows: …, columns: …, data: lr(t,3,…).slice() ?? []})
```

`MatrixData.layout` 默认 `COLUMN_MAJOR`；Python 版 `face_landmarker.py` 读同一个 proto 后 `reshape((rows, cols))`，
列主序时再转置，所以 Python 拿到的是真矩阵 M（`features.euler_from_matrix` 用的就是它），网页版拿到的是 M 的列主序摊平。

**实测**（开发机 Windows，Chrome 无头模式，`FaceLandmarker` IMAGE 模式，CPU；图片为 MediaPipe 官方测试图
`https://storage.googleapis.com/mediapipe-assets/portrait.jpg`，只放在临时目录、不进仓库）：

| 图片 | `data[12..14]` | `data[3]`、`data[7]`、`data[11]` | 按列主序还原的 (yaw, pitch, roll) | 按行主序直接读（错误）|
|---|---|---|---|---|
| 正面原图 | (-0.41, 22.46, -65.45) | 0, 0, 0 | (1.8°, 3.9°, 0.9°) | (-1.8°, -3.9°, -0.8°) |
| 图片逆时针转 20° | (-8.41, 21.98, -81.53) | 0, 0, 0 | (1.9°, 6.1°, **21.4°**) | (-3.9°, -5.0°, -21.1°) |

- 平移（人脸离镜头约 65–80 cm，`tz` 为负）出现在 `data[12..14]`，`data[3/7/11]` 为 0：**列主序**无疑；
- 图片转 20° 时，列主序还原得到 roll ≈ 21°，与转角一致；按行主序读会把所有角度取反；
- blendshape 共 52 个，`CAM_BLENDSHAPES` 要的 26 个全部在。

**自动判断规则**（两处实现一致，有测试）：把 16 个数按行排成 4×4；真矩阵最后一行是 `[0, 0, 0, 1]`、平移在最后一列。
若最后一行前三个数的绝对值和大于最后一列前三个数的绝对值和，说明发来的是列主序，转置回来；反之按行主序；
两者都为 0（只有旋转的合成数据）时按 `MATRIX_LAYOUT`。真实人脸的平移不会是 0，所以规则总能判断。

**与 Python 版逐帧对比**（可选，需要能登录 Spark）：在 Spark 上用 `~/emotion-venv` 对同一张图跑
`FaceLandmarker`（IMAGE 模式），`features.euler_from_matrix(result.facial_transformation_matrixes[0])` 应与上表「按列主序还原」一列相差 < 2°。
不做这一步不影响结论：源码与实测两条证据一致。

## 3. 资源加载与 MIME

- **患者页用经典脚本 `vision_bundle.js`**（`<script>` 动态插入，得到全局 `Vision`），不用 `import()` 加载 `.mjs`：
  模块脚本要求服务器给出 JavaScript 的 MIME 类型，而 Windows 上的 Python `mimetypes` 把 `.mjs` 判成 `text/plain`
  （本机 `python -m http.server` 实测），Spark 上 aiohttp 的判断取决于系统 `mime.types`。`.js` 在两边都是 JavaScript 类型。
- `.wasm`：本机 Python 3.10 `mimetypes` 给 `application/wasm`。Emscripten 加载器在流式编译失败（MIME 不对）时会退回
  `ArrayBuffer` 编译，只是首次加载慢一点；`15_setup_camera_assets.sh` 的自检会打印 Spark 上的实际 Content-Type。
- `.task` 模型按 `application/octet-stream` 下发即可（`fetch` 后读成字节）。
- 无头 Chrome（`--use-fake-device-for-media-stream --use-fake-ui-for-media-stream`，可加
  `--use-file-for-fake-video-capture=<人脸.y4m>`）里，`FaceLandmarker` + `PoseLandmarker`（VIDEO 模式，CPU）约 5 fps，
  上传链路、拒绝授权、vendor 缺失、上传失败都能在本机复现（`apps/multimodal/web/tests/smoke-camera.mjs`）。

## 4. 复现

```bash
# 仓库根目录，Git Bash。临时目录放在仓库外（例如系统临时目录），不要提交
tmp="$(mktemp -d)"; cd "$tmp"
npm pack @mediapipe/tasks-vision@1.0.1 && tar -xzf mediapipe-tasks-vision-1.0.1.tgz
mkdir -p vendor/mediapipe/wasm && cp package/vision_bundle.js vendor/mediapipe/ && cp package/wasm/* vendor/mediapipe/wasm/
cp <模型目录>/face_landmarker.task vendor/mediapipe/    # python -m apps.emotion.face_body fetch-models --models <模型目录>
curl -sSo portrait.jpg https://storage.googleapis.com/mediapipe-assets/portrait.jpg
python -c "from PIL import Image; Image.open('portrait.jpg').rotate(20, expand=True, fillcolor=(128,128,128)).save('portrait_roll.jpg')"
```

`index.html`（同目录）：

```html
<!DOCTYPE html><meta charset="utf-8"><title>matrix spike</title>
<img id="a" src="portrait.jpg"><img id="b" src="portrait_roll.jpg">
<script src="vendor/mediapipe/vision_bundle.js"></script>
<script>
(async function () {
  try {
    const fs = await Vision.FilesetResolver.forVisionTasks('vendor/mediapipe/wasm');
    const lm = await Vision.FaceLandmarker.createFromOptions(fs, {
      baseOptions: { modelAssetPath: 'vendor/mediapipe/face_landmarker.task', delegate: 'CPU' },
      runningMode: 'IMAGE', numFaces: 1, outputFaceBlendshapes: true, outputFacialTransformationMatrixes: true });
    await Promise.all([...document.images].map((i) => i.decode()));
    const out = {};
    for (const id of ['a', 'b']) {
      const r = lm.detect(document.getElementById(id));
      out[id] = { data: Array.from(r.facialTransformationMatrixes[0].data), n: r.faceBlendshapes[0].categories.length };
    }
    window.result = out;
  } catch (e) { window.result = { error: String(e) }; }
})();
</script>
```

用 `python -m http.server 18999 --bind 127.0.0.1` 起静态服务，再用 `apps/multimodal/web/tests/headless.mjs` 打开
`http://127.0.0.1:18999/index.html`，等 `window.result` 出现后读出 `data`，按上文规则算角度。
