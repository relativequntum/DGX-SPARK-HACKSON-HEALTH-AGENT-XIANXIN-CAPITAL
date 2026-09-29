# 实时摄像头观察（最小可演示版）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 问诊时患者可自愿打开摄像头：患者页本机打点并实时显示近似观察值，只把关键点数值传到 Spark；问诊结束后阶段三按每条患者回答统计「同期观察」，医生工作台的「对话记录」与「重点」逐条显示。

**Architecture:** 患者浏览器用 MediaPipe Tasks Vision 网页版（部署到 LiveTalking 静态目录的 `vendor/mediapipe/`，以经典脚本 `vision_bundle.js` 加载）约 5 fps 打点；`camera-metrics.js`（纯函数）算患者端近似值，`camera-observe.js` 每 2 秒把数值批量 POST 到 doctor_service 的 `:8110/api/observe/<consultId>`，服务端整批校验、换成服务器时间后追加写 `<OBS_DIR>/<会话>.frames.jsonl`。常驻的 `emotion-judge-watch` 在会话结束后调用新的 `face_body/live.py`（纯 numpy，复用 `features.py`、`windows.py`）生成与 `judge.json` 同目录的 `<会话>.observe.json`，不走大模型；doctor_service 的 `/highlights` 附带同期观察，`doctor.js` 渲染。

**Tech Stack:** Python 3.10（开发机）/ 3.12（Spark）、numpy、FastAPI + uvicorn（`doctor-venv` 没有 numpy）、pytest、原生 JS（ES5 风格、无构建）、node 22（`node --test`、零依赖 CDP 无头 Chrome 脚本）、`@mediapipe/tasks-vision` 1.0.1、bash。

**Spec:** `docs/superpowers/specs/2026-09-29-live-camera-observation-design.md`（执行前完整读一遍；本计划与它不一致的地方见下文「与 spec 的差异」，以本计划为准）。

## Global Constraints

- 注释、文档、界面文案一律中文；提交格式 `类型(模块): 中文摘要 (#8)`，每个提交末尾加一行 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。
- 仓库会镜像成公开仓库：不提交密钥、患者数据、模型权重、第三方二进制（`apps/multimodal/web/vendor/` 由 `.gitignore` 挡住）；文件里不写真实主机、IP、用户名、本机绝对路径。
- 摄像头**默认关闭**；开启前弹一次说明「画面只在本机处理，只把面部/姿态关键点数值发给系统；可随时关闭；不开也能正常问诊。」；开启期间常驻角标「摄像头观察中 · 画面只在本机处理」；随时可关；**不开摄像头时问诊流程与现在完全一致**。
- 画面不出浏览器：只上传 26 个 blendshape 分数、4×4 头姿矩阵（16 个数）、前 25 个姿态点的 `x, y, visibility`；不录像、不截图、不缓存画面。
- 只做展示，**不进 judge**（judge 的 `channels` 保持为空）；不出情绪标签；数据不足标 `unknown`；说明文字「这些是摄像头观察到的动作数值，不代表情绪或健康状况」。
- 传输走现有 SSH 隧道（8110），不新增端口；上传失败丢弃该批、不重试、不阻塞，连续 5 批失败提示一次「观察数据未能上传」。
- `doctor_service.py` 只依赖标准库和 fastapi（`doctor-venv` 没有 numpy）；`live.py` 纯 numpy；watch 生成 observe 不经过 `PoliteBackend`、不占模型，出错只记异常类名。
- 口径与 face_body 一致：目光偏移 > 0.25、yaw 偏 > 20°、pitch 偏 > 15°；眨眼 > 0.5 判闭、< 0.3 判开；9 帧滑动中位数；本人基线 = 开启后前 5 秒；每段 `min_frames = 6`、`min_ratio = 0.5`、最长 60 秒；手触脸：手腕可见度 > 0.5 且到鼻尖 < 0.18；小动作 = 同一关节相邻帧位移均值 × 1000。
- 上传接口限制：请求体 ≤ 64 KB（超过 413）、`frames` ≤ 50、单文件 ≤ 20 MB（超过 413）、字段白名单与有限数校验（不合格整批 400）、目录 700 / 文件 600、`DOCTOR_OBSERVE=0` 返回 404；时钟换算 `t = recv_time - (sent_ct - ct)/1000`（服务器秒），frames.jsonl 不保存 `ct`。
- 版本：`@mediapipe/tasks-vision@1.0.1`，tgz 校验 `sha512-rvRE2FmAZ6ZxKSw7wq+e+jQDpN3t1B/tD2mJz9SmAzb1msoDkd4dMoE4wAh8Z30Um0PQwLiHr9QtomhmXk3aUQ==`；两个模型 sha256 与 `apps/emotion/face_body/models.py` 登记一致；`schema_version: "face_body-live-0.1"`；上传批 `"v": "cam-0.1"`。
- 本机测试**绝不碰 8010 / 8110**（开发机上这两个端口可能正转发着 Spark）：本机服务用 18010–18012 / 18110，doctor_service 的 `DOCTOR_LT_ADMIN_URL` 指向不可达端口；测试里 `_lt_sessions` 一律打桩。
- 远程操作（SSH 到 Spark、部署、`git push`、`gh` 写操作、合并）都要用户当场批准；不要打开 `localfile/`；公开仓库只在用户明说后同步。
- 开发机是 Windows（Git Bash + PowerShell，`python` 为 3.10、node 22、Chrome 在默认位置）；Spark 是 Linux aarch64（`~/emotion-venv` 有 numpy / mediapipe 1.0.1 / pytest，`~/doctor-venv` 只有 fastapi / uvicorn）。
- 行尾：`apps/multimodal/deploy/livetalking/` 没有 `.gitattributes`，Windows 工作区里的 `.sh` 是 CRLF；**同步到 Spark 一律用 `git -c core.autocrlf=false archive` 取已提交的内容**，不要直接拷工作区文件。

## Review Focus

1. **8110 没转发（演示时最常见）**：上传全部失败 → 每批丢弃、连续 5 批后只提示一次「观察数据未能上传（不影响问诊）」，采集和问诊照常 —— Task 6 冒烟第 4 段。
2. **患者从头到尾没开摄像头**：医生端「对话记录」只在最前面显示一次「本场未开启摄像头」，不逐条重复；`/highlights` 返回 `camera: false` —— Task 4 `test_session_without_camera_says_so_once_in_the_payload`、Task 7 冒烟。
3. **第一句回答之前没有助手事件**（开场白是 echo，不进问诊记录）：第一段仍要给数，起点取 `t_u - 60` 与开启摄像头时刻中较晚的 —— Task 2 `test_first_answer_before_any_reply_is_measured_from_camera_start`。
4. **问诊结束后才到的帧**（最后一批在 summary 之后送达）：observe.json 必须重算，而没有新数据时不重复算 —— Task 3 `test_observe_is_not_rebuilt_until_frames_or_record_change`。
5. **会话中途摄像头断开 / 撤销授权 / 拒绝授权**：停止采集、开关回到「关」、提示一次，问诊照常；中途关掉后的回答段显示 unknown —— Task 6 冒烟第 2、5 段，Task 2 `test_camera_switched_off_mid_answer_makes_that_segment_unknown`。

（另外已由测试覆盖、不在上面五条里的：浏览器时钟与 Spark 差一小时 —— Task 4 `test_browser_clock_far_off_does_not_shift_server_time`；超大 / 恶意批 —— Task 4 的 400/413 系列；断线重连沿用同一 consultId、frames 接着追加 —— Task 4 `test_valid_batch_is_appended...`。）

---

## 执行前须知

**工作区**：git worktree，分支 `feat/live-camera-observation`（基于尚未合并的 `docs/test-manual`，所以 PR 会带上实机测试手册与 README 团队两个提交）。所有命令都在**仓库根目录**运行；bash 命令用 Git Bash，Python 用 `python`（开发机 3.10）。先 `git status` 确认干净、`git log --oneline -3` 能看到本计划的提交。

**本计划的代码已经验证过**：2026-09-29 在一份临时副本上逐字执行过下面所有代码块——`face_body` 62 passed、`judge` 88 passed、doctor_service 32 passed + 1 skipped（Windows 跳过权限位那条）、`camera-metrics.test.js` 7 pass、`smoke-camera.mjs`（有人脸 / 无人脸两种）全部通过、`smoke-doctor.mjs` 全部通过、`smoke-e2e.mjs` 全部通过、`15_setup_camera_assets.sh` 本机演练通过（npm 镜像下载、离线 tgz、校验失败三种）。照抄即可；**如果某一步的输出和「Expected」不一致，先停下排查，不要改测试去迁就**。

**「查找 → 替换」步骤**：用编辑工具把「查找」块原样替换成「替换为」块（查找串在文件里只出现一次）。行号只是帮助定位（基于 `12745d8` 之后的分支内容，执行时以查找串为准）。

**与 spec 的差异（以本计划为准）**：

| spec 原文 | 代码里的实际情况 | 本计划的处理 |
|---|---|---|
| §5.1 动态 `import()` 同源的 `vision_bundle.mjs` | npm 包里另有 `vision_bundle.js`（IIFE，定义全局 `Vision`）；Windows 的 Python `mimetypes` 把 `.mjs` 判成 `text/plain`，模块脚本会被浏览器拒绝 | 用 `<script>` 动态加载 `vision_bundle.js`；15 号脚本仍一并放 `.mjs`（见 `notes/2026-09-29-mediapipe-js-matrix.md`） |
| §5.3 「sid 与现有路由使用同一正则」（`:233`、`:265`） | 现有路由没有正则，只挡 `/`、`\`、开头的 `.` | 写接口用 `consult_recorder._safe_sid` 的 `[A-Za-z0-9_-]{8,64}`（与 `triage.js` 的 `newConsultId` 一致），保证 frames 文件名与问诊记录文件名相同 |
| §5.4 区间「此前最近一条 assistant 事件的 t，t_u」 | ① 开场白是 echo、不进记录，第一句回答前没有 assistant；② 患者连说两句（打断、连续打字）会让两段重叠；③ `windows.aggregate` 的窗从 t=0 切，直接传会切成多窗；④ 摄像头晚开会让第一段永远覆盖不足 | 起点 = max(上一条 assistant、上一条 user、t_u − 60)，且计算时不早于第一帧；段内时间改为相对段内第一帧、窗长 = 区间长度，`aggregate` 只出一个窗 |
| §5.4 每段字段 | 患者端面板要显示「眨眼 N 次」，一致性测试也要精确比次数 | 每段多一个 `blink_count` |
| §5.5 「超过会话中位数 1.5 倍加 ↑」 | `/highlights` 只列了 `observe_segments`，医生端拿不到中位数 | `/highlights` 顶层多给 `observe_medians`；中位数为 0 时只要有值就标 ↑ |
| §5.5 `markObserve(segments)` 参照 `markHits` | `renderMessages` 每 5 秒轮询都会整体重画对话 DOM | `markObserve()` 读 `state.highlights`，挂在 `markHits()` 末尾（`markHits` 已在三处被调用），先删旧行再加，避免重复 |
| §5.4 watch：frames 比 observe 新才重算 | 问诊记录后来又变了（idle 判结束后患者回来继续说）也该重算 | observe.json 比 frames **或**问诊记录旧都重算；生成期间数据又变了就把 observe 的 mtime 拨回（与 judge 同一手法） |
| §9 「选一张有人脸的测试图片，分别用 Python mediapipe 和浏览器端计算」 | 开发机没有 Python mediapipe | 已用源码 + 实测（平移位置、图片转 20° 的 roll 符号）核实为列主序；`live.py` / `camera-metrics.js` 另按平移位置自动判断；Spark 上的 Python 对比列为可选（核实记录 §2） |
| （spec 未提）本机冒烟会不会打到 8110 隧道 | 上传地址写死 `:8110` | 加 `?obs_port=<端口>` 只改端口、不改主机，本机冒烟用 18110 |

**文件地图**（新建 / 修改，一个文件一个职责）：

```text
新建
  apps/emotion/face_body/live.py                       逐帧数值 + 问诊记录 → observe.json（纯 numpy）
  apps/emotion/face_body/tests/test_live.py
  apps/multimodal/deploy/livetalking/tests/conftest.py  doctor_service 接口测试的夹具（不连 Spark）
  apps/multimodal/deploy/livetalking/tests/test_doctor_observe.py
  apps/multimodal/deploy/livetalking/15_setup_camera_assets.sh   vendor 资源安装与自检
  apps/multimodal/web/camera-metrics.js                逐帧换算与统计（纯函数，浏览器 + node）
  apps/multimodal/web/camera-observe.js                开关、小窗、打点、上传、面板、观察行
  apps/multimodal/web/tests/headless.mjs               零依赖无头 Chrome（CDP）工具
  apps/multimodal/web/tests/make_parity_fixture.py     用 live.py 生成一致性测试数据
  apps/multimodal/web/tests/fixtures/camera-parity.json  （生成物，提交）
  apps/multimodal/web/tests/camera-metrics.test.js     node 单元测试 + 一致性测试
  apps/multimodal/web/tests/make_face_y4m.py           人脸假摄像头视频（只写临时目录）
  apps/multimodal/web/tests/smoke-camera.mjs           患者页冒烟
  apps/multimodal/web/tests/smoke-doctor.mjs           医生端 ?demo=1 冒烟
  apps/multimodal/web/tests/smoke-e2e.mjs              本机端到端彩排
修改
  .gitignore                                           挡住 apps/multimodal/web/vendor/
  apps/emotion/judge/watch.py、tests/test_watch.py     结束的会话生成 observe.json
  apps/emotion/deploy/spark.env                        EMOTION_OBS_DIR
  apps/multimodal/deploy/livetalking/doctor_service.py POST /api/observe、/highlights 附观察、/health
  apps/multimodal/deploy/livetalking/env.sh            DOCTOR_OBS_DIR、DOCTOR_OBSERVE、CAM_*
  apps/multimodal/deploy/livetalking/13_deploy_web.sh  FILES 加 camera-*.js，自检 vendor
  apps/multimodal/deploy/livetalking/14_setup_doctor_console.sh  观察目录 700、导出新变量
  apps/multimodal/web/triage.html / triage.css / triage.js       开关、小窗、钩子、演示行
  apps/multimodal/web/doctor.js / doctor.css                     同期观察行、演示数据
  README.md、docs/safety-and-privacy.md、docs/实机测试操作手册.md、THIRD_PARTY_NOTICES.md、
  apps/emotion/face_body/README.md、apps/multimodal/README.md、
  apps/multimodal/deploy/livetalking/README.md、apps/emotion/deploy/README.md
已随本计划提交
  docs/superpowers/plans/notes/2026-09-29-mediapipe-js-matrix.md  行列序与资源加载核实记录
```

**任务依赖**：1 → 2 → 3；2 → 4（CAM_BLENDSHAPES 对照）→ 5 → 6 → 7；4 → 8；全部 → 9 → 10 → 11。按编号顺序做即可。

### Task 1: 本机打点资源、无头 Chrome 工具与行列序复核

**Files:**
- Modify: `.gitignore:39-40`（文件末尾 `coverage.xml` / `htmlcov/` 之后追加）
- Create: `apps/multimodal/web/tests/headless.mjs`
- 本机生成、**不提交**：`apps/multimodal/web/vendor/mediapipe/`
- 已随计划提交、只需复核：`docs/superpowers/plans/notes/2026-09-29-mediapipe-js-matrix.md`

**Interfaces:**
- Produces（`headless.mjs`，Task 6、7、9 的冒烟脚本都用）：`findChrome(): string`（环境变量 `CHROME` 优先）；`sleep(ms): Promise<void>`；`launchChrome(extraArgs?: string[]): Promise<{ open(url): Promise<Page>, close(): Promise<void> }>`，默认带 `--headless=new --use-fake-device-for-media-stream --use-fake-ui-for-media-stream --no-proxy-server`；`Page = { eval(expr): Promise<any>, waitFor(expr, timeoutMs = 20000, stepMs = 250): Promise<true>, logs: string[], close(): void }`，页面里的 `confirm()` 自动点「确定」。
- Produces（本机目录，Task 6、7、9 依赖）：`apps/multimodal/web/vendor/mediapipe/` 下有 `vision_bundle.js`、`vision_bundle.mjs`、`package.json`、`VERSION`（内容 `1.0.1`）、`wasm/` 六个文件、`face_landmarker.task`、`pose_landmarker_full.task`——与 Task 8 的 `15_setup_camera_assets.sh` 在 Spark 上装出来的布局相同。
- Produces（决定）：`MATRIX_LAYOUT = "col"`，Task 2 `live.py` 与 Task 5 `camera-metrics.js` 使用。

- [ ] **Step 1: `.gitignore` 挡住 vendor 目录**

`.gitignore`

查找：

````text
coverage.xml
htmlcov/
````

替换为：

````text
coverage.xml
htmlcov/

# 第三方前端资源（MediaPipe 网页版与模型）：部署时由 15_setup_camera_assets.sh 放进 LiveTalking 静态目录，不进仓库
apps/multimodal/web/vendor/
````

- [ ] **Step 2: 确认规则生效**

Run: `mkdir -p apps/multimodal/web/vendor/mediapipe && touch apps/multimodal/web/vendor/mediapipe/probe && git check-ignore -v apps/multimodal/web/vendor/mediapipe/probe && rm apps/multimodal/web/vendor/mediapipe/probe`
Expected: `.gitignore:43:apps/multimodal/web/vendor/	apps/multimodal/web/vendor/mediapipe/probe`

- [ ] **Step 3: 写无头 Chrome 工具**

Create `apps/multimodal/web/tests/headless.mjs`：
````javascript
// 无依赖的无头 Chrome 小工具（Chrome DevTools Protocol + node 22 自带的 WebSocket / fetch），给冒烟脚本用。
//   import { launchChrome } from './headless.mjs';
//   const chrome = await launchChrome();              // 带假摄像头、自动允许授权
//   const page = await chrome.open('http://127.0.0.1:18010/triage.html');
//   await page.waitFor('document.readyState === "complete"');
//   console.log(await page.eval('document.title'));
//   await chrome.close();
// Chrome 路径：环境变量 CHROME，否则按 Windows / Linux / macOS 的常见位置找。
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const CANDIDATES = [
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
];

export function findChrome() {
    if (process.env.CHROME) { return process.env.CHROME; }
    const hit = CANDIDATES.find((p) => fs.existsSync(p));
    if (!hit) { throw new Error('找不到 Chrome：用环境变量 CHROME 指定可执行文件'); }
    return hit;
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function launchChrome(extraArgs = []) {
    const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'cam-smoke-'));
    const proc = spawn(findChrome(), [
        '--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`,
        '--no-first-run', '--no-default-browser-check', '--no-proxy-server',
        '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
        '--autoplay-policy=no-user-gesture-required', ...extraArgs, 'about:blank',
    ], { stdio: 'ignore' });
    // Chrome 把实际端口写进 DevToolsActivePort；文件可能先建出来、内容后写，所以读到数字为止
    const portFile = path.join(profile, 'DevToolsActivePort');
    let port = '';
    for (let i = 0; i < 150 && !/^\d+$/.test(port); i += 1) {
        await sleep(100);
        try { port = fs.readFileSync(portFile, 'utf8').split('\n')[0].trim(); } catch (e) { port = ''; }
    }
    if (!/^\d+$/.test(port)) { proc.kill(); throw new Error('Chrome 没有启动（15 秒内没有调试端口）'); }
    const base = `http://127.0.0.1:${port}`;

    async function open(url) {
        // 先开空白页再 Page.navigate：URL 里的 #会话编号 不能放进 /json/new 的查询串
        const target = await (await fetch(`${base}/json/new?about:blank`, { method: 'PUT' })).json();
        const ws = new WebSocket(target.webSocketDebuggerUrl);
        await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
        let seq = 0;
        const pending = new Map();
        const logs = [];
        ws.onmessage = (ev) => {
            const msg = JSON.parse(ev.data);
            if (msg.id && pending.has(msg.id)) {
                const { resolve, reject } = pending.get(msg.id);
                pending.delete(msg.id);
                if (msg.error) { reject(new Error(msg.error.message)); } else { resolve(msg.result); }
            } else if (msg.method === 'Runtime.consoleAPICalled') {
                logs.push(`${msg.params.type}: ${msg.params.args.map((a) => a.value ?? a.description ?? '').join(' ')}`);
            } else if (msg.method === 'Runtime.exceptionThrown') {
                logs.push(`exception: ${msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text}`);
            } else if (msg.method === 'Page.javascriptDialogOpening') {
                send('Page.handleJavaScriptDialog', { accept: true });   // confirm() 一律点「确定」
            }
        };
        function send(method, params = {}) {
            seq += 1;
            ws.send(JSON.stringify({ id: seq, method, params }));
            return new Promise((resolve, reject) => pending.set(seq, { resolve, reject }));
        }
        await send('Runtime.enable');
        await send('Page.enable');
        await send('Page.navigate', { url });
        async function evaluate(expr) {
            const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
            if (r.exceptionDetails) {
                throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
            }
            return r.result.value;
        }
        async function waitFor(expr, timeoutMs = 20000, stepMs = 250) {
            const until = Date.now() + timeoutMs;
            for (;;) {
                try { if (await evaluate(expr)) { return true; } } catch (e) { /* 页面还在加载 */ }
                if (Date.now() > until) { throw new Error(`等待超时（${timeoutMs}ms）：${expr}`); }
                await sleep(stepMs);
            }
        }
        return { eval: evaluate, waitFor, logs, close: () => ws.close() };
    }

    async function close() {
        proc.kill();
        await sleep(300);
        try { fs.rmSync(profile, { recursive: true, force: true }); } catch (e) { /* Windows 上文件可能还被占着 */ }
    }

    return { open, close };
}
````

- [ ] **Step 4: 工具自检**

Run（Git Bash，仓库根目录）：
```bash
node --input-type=module -e "import { launchChrome } from './apps/multimodal/web/tests/headless.mjs'; const c = await launchChrome(); const p = await c.open('data:text/html,<title>hi</title>'); await p.waitFor('document.title === \"hi\"'); console.log('headless OK:', await p.eval('document.title')); p.close(); await c.close();"
```
Expected: `headless OK: hi`（找不到 Chrome 时设 `CHROME=<chrome.exe 路径>` 再跑）。

- [ ] **Step 5: 在本机放好 MediaPipe 网页版与模型（不提交）**

Run（Git Bash，仓库根目录；`mktemp -d` 是 Git Bash 自己的临时目录）：
```bash
tmp="$(mktemp -d)"
(cd "$tmp" && npm pack @mediapipe/tasks-vision@1.0.1 --registry https://registry.npmmirror.com >/dev/null)
echo "sha512-$(openssl dgst -sha512 -binary "$tmp"/mediapipe-tasks-vision-1.0.1.tgz | base64 | tr -d '\n')"
tar -xzf "$tmp"/mediapipe-tasks-vision-1.0.1.tgz -C "$tmp"
V=apps/multimodal/web/vendor/mediapipe
mkdir -p "$V/wasm"
cp "$tmp"/package/vision_bundle.js "$tmp"/package/vision_bundle.mjs "$tmp"/package/package.json "$V/"
cp "$tmp"/package/wasm/* "$V/wasm/"
echo 1.0.1 > "$V/VERSION"
python -m apps.emotion.face_body fetch-models --models "$tmp/models"
cp "$tmp"/models/face_landmarker.task "$tmp"/models/pose_landmarker_full.task "$V/"
ls "$V" "$V/wasm"
git status --short
```
Expected:
- 校验行是 `sha512-rvRE2FmAZ6ZxKSw7wq+e+jQDpN3t1B/tD2mJz9SmAzb1msoDkd4dMoE4wAh8Z30Um0PQwLiHr9QtomhmXk3aUQ==`（镜像不通时去掉 `--registry ...` 走官方源，校验值相同）；
- `fetch-models` 打印 `[face_body] face: …face_landmarker.task` 与 `[face_body] pose: …pose_landmarker_full.task`；
- `ls` 列出 `VERSION face_landmarker.task package.json pose_landmarker_full.task vision_bundle.js vision_bundle.mjs wasm` 与 `wasm/` 下 6 个 `vision_wasm_*` 文件；
- `git status --short` 里**没有** `vendor/`（只会看到 Step 1、3 的改动）。

- [ ] **Step 6: 复核行列序（可选，5 分钟内做完就做；做不了不阻塞，结论已由源码与实测给出）**

按核实记录 §4 在 `$tmp` 里放好 `portrait.jpg`、`portrait_roll.jpg`、`index.html` 和 `vendor/mediapipe/`（`vision_bundle.js`、`wasm/`、`face_landmarker.task`），然后把下面存成 `$tmp/run-spike.mjs`，在仓库根目录运行 `node "$tmp/run-spike.mjs" "$tmp"`：
```javascript
import path from 'node:path';
import { spawn } from 'node:child_process';
import { pathToFileURL } from 'node:url';
const dir = process.argv[2];
const { launchChrome, sleep } = await import(pathToFileURL(path.resolve('apps/multimodal/web/tests/headless.mjs')).href);
const srv = spawn('python', ['-m', 'http.server', '18999', '--bind', '127.0.0.1', '--directory', dir], { stdio: 'ignore' });
await sleep(1500);
const chrome = await launchChrome();
try {
    const page = await chrome.open('http://127.0.0.1:18999/index.html');
    await page.waitFor('window.result !== undefined', 60000);
    const r = await page.eval('window.result');
    if (r.error) { throw new Error(r.error); }
    for (const id of ['a', 'b']) {
        const d = r[id].data;
        console.log(id, 'blendshapes', r[id].n, '| data[12..14]', d.slice(12, 15).map((x) => x.toFixed(2)).join(', '),
            '| data[3,7,11]', [d[3], d[7], d[11]].join(', '));
    }
} finally { await chrome.close(); srv.kill(); }
```
Expected: 两行都是 `blendshapes 52`，`data[12..14]` 三个数不为 0（第三个约 -65 到 -82），`data[3,7,11]` 为 `0, 0, 0` —— 列主序，与核实记录一致。若相反（`data[3,7,11]` 非零），在核实记录里补一行实测结果，并把 Task 2、Task 5 里的 `MATRIX_LAYOUT` 改成 `"row"`（自动判断规则不用改）。

- [ ] **Step 7: Commit**

```bash
git add .gitignore apps/multimodal/web/tests/headless.mjs
git commit -m "chore(web): 挡住 vendor 目录并加入无头 Chrome 冒烟工具 (#8)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `face_body/live.py`：逐帧数值 + 问诊记录 → 每条回答的同期观察

**Files:**
- Create: `apps/emotion/face_body/live.py`
- Test: `apps/emotion/face_body/tests/test_live.py`

**Interfaces:**
- Consumes：`features.au_proxy(bs) -> dict`、`features.blink_score(bs) -> float`、`features.euler_from_matrix(m) -> (yaw, pitch, roll)`、`features.gaze_from_blendshapes(bs) -> (h, v)`、`features.pose_features(landmarks) -> dict`（带 `shoulders`、`hand_face`、`kp` 等）；`windows.NOTICE`、`windows.individual_baseline(frames, seconds) -> dict | None`、`windows.aggregate(frames, window, min_ratio, baseline, min_frames) -> list[dict]`（窗从 t=0 切；每窗有 `face_status`/`body_status`，ok 时有 `gaze.away_ratio`、`blink.count`、`blink.per_min`、`head.motion_deg_per_frame`、`body.hand_face_ratio`、`body.motion_x1000`）。
- Produces（Task 3、4、5 用）：
  - 常量 `CAM_BLENDSHAPES: tuple[str, ...]`（26 个，顺序固定，三处一致）、`SCHEMA_VERSION = "face_body-live-0.1"`、`MATRIX_LAYOUT = "col"`、`BASELINE_S = 5.0`、`MAX_SEGMENT_S = 60.0`、`MIN_FRAMES = 6`、`MIN_RATIO = 0.5`、`SEGMENT_KEYS = ("gaze_away_ratio", "blink_per_min", "head_motion_deg_per_frame", "hand_face_ratio", "body_motion_x1000")`；
  - `matrix_from_flat(values, layout=MATRIX_LAYOUT) -> np.ndarray(4, 4)`；`to_frame_record(frame: dict, t0: float) -> dict`；`load_frames(path) -> list[dict]`；`load_events(path) -> list[{"t", "kind"}]`；`answer_intervals(events) -> list[(start, t_u)]`；`summarize_segment(recs, a: float, b: float, baseline) -> dict`（键：`frames`、`face_status`、`body_status`、`blink_count` + `SEGMENT_KEYS`）；`build_observation(frames, events, session_id="") -> dict`；`write_observation(obs, out_dir) -> Path`（`<out_dir>/<session_id>.observe.json`，临时文件 + `os.replace`）；`observe_session(consult_path, frames_path, out_dir) -> Path`；`main(argv=None) -> int`（`python -m apps.emotion.face_body.live --consult … --frames … --out-dir …`）。
  - `observe.json`：`schema_version`、`notice`、`session_id`、`generated_at`、`camera_frames`、`face_detect_ratio`、`pose_detect_ratio`、`min_frames`、`min_ratio`、`max_segment_s`、`baseline`、`medians`（`SEGMENT_KEYS` 各自的会话中位数，unknown 段不参与）、`segments[]`（`t` = 问诊记录里那条患者事件的 `t` **原值**、`interval: [起点, t_u]`、`frames`、`face_status`、`body_status`、`blink_count` + `SEGMENT_KEYS`；unknown 通道对应字段为 `null`）。

- [ ] **Step 1: Write the failing test**

Create `apps/emotion/face_body/tests/test_live.py`：
````python
# -*- coding: utf-8 -*-
import json
import math

import numpy as np
import pytest

from apps.emotion.face_body import live
from apps.emotion.face_body.features import AU_MAP
from apps.emotion.face_body.live import (CAM_BLENDSHAPES, SCHEMA_VERSION, answer_intervals, build_observation,
                                         load_events, load_frames, matrix_from_flat, observe_session,
                                         to_frame_record, write_observation)

T0 = 1_790_000_000.0  # 服务器时间（秒），与问诊记录的 t 同一口径


def _mat(yaw=0.0, layout="col", tz=-45.0):
    """已知 yaw 的 4x4 姿态矩阵，按浏览器的排法摊成 16 个数（col = 列主序）。"""
    t = math.radians(yaw)
    c, s = math.cos(t), math.sin(t)
    m = np.array([[c, 0, s, 1.5], [0, 1, 0, -2.0], [-s, 0, c, tz], [0, 0, 0, 1.0]])
    return [float(v) for v in (m.T if layout == "col" else m).reshape(-1)]


def _bs(**kw):
    d = {k: 0.0 for k in CAM_BLENDSHAPES}
    d.update(kw)
    return d


def _pose(hand=False, shift=0.0, shoulders=True):
    p = [[0.5, 0.5, 0.0] for _ in range(25)]
    for i, (x, y) in {0: (0.50, 0.30), 11: (0.62, 0.55), 12: (0.38, 0.55), 15: (0.70, 0.90),
                      16: (0.30, 0.90), 23: (0.58, 0.95), 24: (0.42, 0.95)}.items():
        p[i] = [x + shift, y, 1.0]
    if hand:
        p[15] = [0.52 + shift, 0.32, 1.0]
    if not shoulders:
        p[12][2] = 0.1
    return p


def _frame(t, face=True, pose=True, yaw=0.0, gaze=0.0, blink=0.0, hand=False, shift=0.0):
    f = {"bs": _bs(eyeLookOutLeft=gaze, eyeLookInRight=gaze, eyeBlinkLeft=blink, eyeBlinkRight=blink),
         "m": _mat(yaw)} if face else None
    return {"t": t, "f": f, "p": _pose(hand, shift) if pose else None}


def _session(n=200, **kw):
    """5 fps、从 T0 开始的 n 帧。"""
    return [_frame(T0 + i / 5, **kw) for i in range(n)]


def test_cam_blendshapes_cover_every_blendshape_features_reads():
    used = {"eyeLookOutLeft", "eyeLookInRight", "eyeLookInLeft", "eyeLookOutRight", "eyeLookUpLeft",
            "eyeLookUpRight", "eyeLookDownLeft", "eyeLookDownRight", "eyeBlinkLeft", "eyeBlinkRight"}
    used |= {n for _, names in AU_MAP for n in names}
    assert len(CAM_BLENDSHAPES) == 26 == len(set(CAM_BLENDSHAPES))
    assert set(CAM_BLENDSHAPES) == used


@pytest.mark.parametrize("layout", ["col", "row"])
def test_matrix_layout_is_detected_from_where_the_translation_sits(layout):
    from apps.emotion.face_body.features import euler_from_matrix
    yaw, pitch, roll = euler_from_matrix(matrix_from_flat(_mat(25.0, layout)))
    assert yaw == pytest.approx(25.0, abs=1e-6) and abs(pitch) < 1e-6 and abs(roll) < 1e-6


def test_rotation_only_matrix_falls_back_to_the_declared_layout():
    from apps.emotion.face_body.features import euler_from_matrix
    flat = _mat(25.0, "col", tz=0.0)
    flat[12] = flat[13] = 0.0  # 平移全为 0：看不出行列序
    assert euler_from_matrix(matrix_from_flat(flat, layout="col"))[0] == pytest.approx(25.0, abs=1e-6)
    assert euler_from_matrix(matrix_from_flat(flat, layout="row"))[0] == pytest.approx(-25.0, abs=1e-6)


def test_frame_record_has_the_same_shape_as_offline_frame_record():
    rec = to_frame_record(_frame(T0 + 2.5, yaw=10.0, gaze=0.3, blink=0.6, hand=True), T0)
    assert rec["t"] == pytest.approx(2.5)
    assert rec["face"] is True and rec["pose"] is True
    assert rec["yaw"] == pytest.approx(10.0, abs=1e-6)
    assert rec["gaze_h"] == pytest.approx(0.3) and rec["blink"] == pytest.approx(0.6)
    assert list(rec["au"]) == [name for name, _ in AU_MAP]
    assert rec["hand_face"] is True and "shoulders" not in rec and 11 in rec["kp"]


def test_frame_without_face_or_shoulders_is_not_a_detection():
    rec = to_frame_record({"t": T0, "f": None, "p": None}, T0)
    assert rec == {"t": 0.0, "face": False, "pose": False}
    cut = to_frame_record({"t": T0, "f": None, "p": _pose(shoulders=False)}, T0)
    assert cut["pose"] is False


def test_load_frames_skips_bad_lines_and_sorts_by_server_time(tmp_path):
    path = tmp_path / "s.frames.jsonl"
    rows = [json.dumps({"t": T0 + 1, "f": None, "p": None}), "not json", json.dumps([1, 2]),
            json.dumps({"t": "x", "f": None}), json.dumps({"t": T0, "f": None, "p": None}), '{"t": 17900']
    path.write_text("\n".join(rows), encoding="utf-8")
    assert [r["t"] for r in load_frames(path)] == [T0, T0 + 1]


def test_load_events_keeps_user_with_text_and_assistant(tmp_path):
    path = tmp_path / "s.jsonl"
    evs = [{"t": T0 + 1, "kind": "assistant", "text": "哪里不舒服？"}, {"t": T0 + 2, "kind": "user", "text": " "},
           {"t": T0 + 3, "kind": "user", "text": "胃疼"}, {"t": T0 + 4, "kind": "summary", "doctor": "…"},
           {"kind": "user", "text": "没有时间"}]
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in evs), encoding="utf-8")
    assert load_events(path) == [{"t": T0 + 1, "kind": "assistant"}, {"t": T0 + 3, "kind": "user"}]


def test_answer_intervals_start_at_the_previous_reply_or_answer_capped_at_60s():
    evs = [{"t": 100.0, "kind": "user"},                                   # 前面只有开场白：往前 60 秒
           {"t": 110.0, "kind": "assistant"}, {"t": 130.0, "kind": "user"},  # 上一句助手回复 → 本句
           {"t": 140.0, "kind": "user"},                                   # 连说两句：从上一句算起
           {"t": 150.0, "kind": "assistant"}, {"t": 300.0, "kind": "user"}]  # 隔太久：最多 60 秒
    assert answer_intervals(evs) == [(40.0, 100.0), (110.0, 130.0), (130.0, 140.0), (240.0, 300.0)]


EVENTS = [{"t": T0 + 8, "kind": "assistant"}, {"t": T0 + 20, "kind": "user"},
          {"t": T0 + 22, "kind": "assistant"}, {"t": T0 + 35, "kind": "user"}]


def test_segments_follow_answers_and_carry_the_exact_event_time():
    obs = build_observation(_session(), EVENTS, session_id="abc12345")
    assert obs["schema_version"] == SCHEMA_VERSION and obs["session_id"] == "abc12345"
    assert [s["t"] for s in obs["segments"]] == [T0 + 20, T0 + 35]  # 原样的 t，医生端按它对回原句
    s1, s2 = obs["segments"]
    assert s1["interval"] == [round(T0 + 8, 3), round(T0 + 20, 3)]
    assert s1["frames"] == 61 and s1["face_status"] == "ok" and s1["body_status"] == "ok"
    assert s1["head_motion_deg_per_frame"] == 0.0 and s1["hand_face_ratio"] == 0.0
    assert obs["camera_frames"] == 200 and obs["face_detect_ratio"] == 1.0 and obs["pose_detect_ratio"] == 1.0
    assert obs["baseline"]["source"] == "first_5s"


def test_gaze_away_blinks_and_hand_to_face_per_segment():
    frames = []
    for i in range(200):
        t = i / 5
        away = t >= 22                        # 第二段目光偏开
        blink = 0.8 if i in (50, 51, 70, 71) else 0.0  # 第一段两次眨眼
        frames.append(_frame(T0 + t, gaze=0.7 if away else 0.0, blink=blink, hand=(t >= 22 and i % 2 == 0)))
    s1, s2 = build_observation(frames, EVENTS)["segments"]
    assert s1["gaze_away_ratio"] == 0.0 and s1["blink_count"] == 2 and s1["blink_per_min"] == 10.0
    assert s2["gaze_away_ratio"] == 1.0 and s2["blink_count"] == 0
    assert s2["hand_face_ratio"] == pytest.approx(0.5, abs=0.02)


def test_segment_without_frames_or_with_too_few_is_unknown_without_numbers():
    few = [_frame(T0 + 19 + i / 5) for i in range(5)]  # 只有 5 帧，且不到半段
    obs = build_observation([_frame(T0)] + few, EVENTS)
    s1, s2 = obs["segments"]
    assert s1["face_status"] == "unknown" and s1["gaze_away_ratio"] is None and s1["blink_per_min"] is None
    assert s2["frames"] == 0 and s2["face_status"] == s2["body_status"] == "unknown"
    assert all(s2[k] is None for k in live.SEGMENT_KEYS)


def test_face_only_and_pose_only_segments():
    face_only = build_observation(_session(pose=False), EVENTS)["segments"][0]
    assert face_only["face_status"] == "ok" and face_only["body_status"] == "unknown"
    assert face_only["gaze_away_ratio"] is not None and face_only["hand_face_ratio"] is None
    pose_only = build_observation(_session(face=False), EVENTS)["segments"][0]
    assert pose_only["face_status"] == "unknown" and pose_only["body_status"] == "ok"
    assert pose_only["gaze_away_ratio"] is None and pose_only["body_motion_x1000"] == 0.0


def test_first_answer_before_any_reply_is_measured_from_camera_start():
    # 开场白不进问诊记录：第一句回答前没有助手事件；摄像头从 T0 开到回答，整段都有帧，应当给数
    obs = build_observation(_session(n=60), [{"t": T0 + 11.8, "kind": "user"}])
    seg = obs["segments"][0]
    assert seg["interval"][0] == round(T0 + 11.8 - 60, 3)
    assert seg["face_status"] == "ok" and seg["frames"] == 60


def test_camera_switched_off_mid_answer_makes_that_segment_unknown():
    frames = _session(n=140)  # 摄像头在第二段中途（T0+27.8）关掉：第二段只覆盖了 5.8 / 13 秒
    s1, s2 = build_observation(frames, EVENTS)["segments"]
    assert s1["face_status"] == "ok"
    assert s2["frames"] == 30 and s2["face_status"] == "unknown" and s2["gaze_away_ratio"] is None


def test_session_medians_skip_unknown_segments():
    frames = []
    for i in range(200):
        t = i / 5
        frames.append(_frame(T0 + t, gaze=0.7 if t >= 22 else 0.0))
    obs = build_observation(frames, EVENTS + [{"t": T0 + 60, "kind": "user"}])  # 第三段没有帧
    assert obs["medians"]["gaze_away_ratio"] == 0.5  # (0.0 + 1.0) / 2，unknown 段不参与
    assert obs["segments"][2]["face_status"] == "unknown"


def test_no_frames_at_all_gives_unknown_segments_and_zero_ratios():
    obs = build_observation([], EVENTS)
    assert obs["camera_frames"] == 0 and obs["face_detect_ratio"] == 0.0 and obs["baseline"] is None
    assert [s["face_status"] for s in obs["segments"]] == ["unknown", "unknown"]


def test_write_observation_replaces_atomically_and_leaves_no_temp_file(tmp_path):
    obs = build_observation(_session(), EVENTS, session_id="abc12345")
    path = write_observation(obs, tmp_path / "out")
    assert path.name == "abc12345.observe.json"
    assert json.loads(path.read_text(encoding="utf-8"))["segments"][0]["t"] == T0 + 20
    write_observation(obs, tmp_path / "out")
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["abc12345.observe.json"]


def test_observe_session_and_cli(tmp_path, capsys):
    consult = tmp_path / "abc12345.jsonl"
    consult.write_text("\n".join(json.dumps(dict(e, text="…")) for e in EVENTS), encoding="utf-8")
    frames = tmp_path / "abc12345.frames.jsonl"
    frames.write_text("\n".join(json.dumps(f) for f in _session()), encoding="utf-8")
    path = observe_session(consult, frames, tmp_path / "out")
    assert json.loads(path.read_text(encoding="utf-8"))["session_id"] == "abc12345"
    assert live.main(["--consult", str(consult), "--frames", str(frames), "--out-dir", str(tmp_path / "o2")]) == 0
    assert "2 段回答" in capsys.readouterr().out
````

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest apps/emotion/face_body/tests/test_live.py -q -p no:cacheprovider`
Expected: FAIL —— 收集阶段报 `ModuleNotFoundError: No module named 'apps.emotion.face_body.live'`（`1 error`）。

- [ ] **Step 3: Write minimal implementation**

Create `apps/emotion/face_body/live.py`：
````python
# -*- coding: utf-8 -*-
"""实时通道（浏览器打点）：患者页上传的逐帧关键点数值 → 按患者每次回答切段的同期观察。

输入：
- `<OBS_DIR>/<会话>.frames.jsonl`：doctor_service 追加写，每行
  `{"t": 服务器秒, "f": {"bs": {26 个 blendshape}, "m": [16 个数]} | null, "p": [[x, y, visibility] × 25] | null}`；
- `<CONSULT_DIR>/<会话>.jsonl`：数字人的问诊记录，事件 `{"t", "kind": "user"|"assistant"|"summary", "text"}`。
输出：`<JUDGE_OUT>/<会话>.observe.json`（`schema_version: face_body-live-0.1`），医生工作台读它。

口径与离线视频相同：逐帧换算用 features.py，本人基线、平滑、眨眼滞回、unknown 判定用 windows.py；
每段检出帧 < 6 或检出率 < 0.5 记 unknown、不给数。不做人脸识别，不做表情或情绪分类。纯 numpy。

    python -m apps.emotion.face_body.live --consult <会话>.jsonl --frames <会话>.frames.jsonl --out-dir <目录>
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import pathlib
import sys
import tempfile
from types import SimpleNamespace

import numpy as np

from .features import au_proxy, blink_score, euler_from_matrix, gaze_from_blendshapes, pose_features
from .windows import NOTICE, aggregate, individual_baseline

SCHEMA_VERSION = "face_body-live-0.1"
# 浏览器上传的 blendshape 白名单：features.py 用到的 26 个（目光 8、眨眼 2、AU 近似 16）。
# 与 apps/multimodal/web/camera-metrics.js、apps/multimodal/deploy/livetalking/doctor_service.py 三处一致，有测试核对。
CAM_BLENDSHAPES = (
    "eyeLookOutLeft", "eyeLookOutRight", "eyeLookInLeft", "eyeLookInRight",
    "eyeLookUpLeft", "eyeLookUpRight", "eyeLookDownLeft", "eyeLookDownRight",
    "eyeBlinkLeft", "eyeBlinkRight",
    "browInnerUp", "browOuterUpLeft", "browOuterUpRight", "browDownLeft", "browDownRight",
    "cheekSquintLeft", "cheekSquintRight", "eyeSquintLeft", "eyeSquintRight",
    "mouthSmileLeft", "mouthSmileRight", "mouthFrownLeft", "mouthFrownRight",
    "mouthPressLeft", "mouthPressRight", "jawOpen",
)
# MediaPipe 网页版 Matrix.data 的行列序：它把 MatrixData 的 packed_data 原样给出，默认列主序
# （核实记录：docs/superpowers/plans/notes/2026-09-29-mediapipe-js-matrix.md）。
# matrix_from_flat 先按平移所在位置自动判断，只有判断不了（平移为 0 的合成矩阵）时才用它。
MATRIX_LAYOUT = "col"
BASELINE_S = 5.0        # 本人基线：开启摄像头后前 5 秒
MAX_SEGMENT_S = 60.0    # 一段最长截取 60 秒
MIN_FRAMES = 6          # 约 5 fps，一段至少 6 帧检出才给数
MIN_RATIO = 0.5
SEGMENT_KEYS = ("gaze_away_ratio", "blink_per_min", "head_motion_deg_per_frame",
                "hand_face_ratio", "body_motion_x1000")


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def matrix_from_flat(values, layout: str = MATRIX_LAYOUT) -> np.ndarray:
    """浏览器发来的 16 个数 → 4x4 矩阵，与 Python mediapipe 的 facial_transformation_matrixes[0] 同向。

    真矩阵最后一行是 [0, 0, 0, 1]，平移在最后一列（人脸离镜头几十厘米，平移不会是 0）：
    按行排开后平移落在最后一行，说明发来的是列主序，转置回来；两处都为 0 时按 layout。"""
    m = np.asarray(values, dtype=float).reshape(4, 4)
    bottom, right = float(np.abs(m[3, :3]).sum()), float(np.abs(m[:3, 3]).sum())
    if bottom > right:
        return m.T
    if right > bottom:
        return m
    return m.T if layout == "col" else m


def to_frame_record(frame: dict, t0: float) -> dict:
    """frames.jsonl 的一行 → 与 analyze.frame_record 同形的帧记录；t 为相对 t0（第一帧）的秒数。"""
    rec = {"t": float(frame["t"]) - t0, "face": False, "pose": False}
    f = frame.get("f")
    if isinstance(f, dict):
        bs = {k: float(f["bs"][k]) for k in CAM_BLENDSHAPES}
        yaw, pitch, roll = euler_from_matrix(matrix_from_flat(f["m"]))
        gaze_h, gaze_v = gaze_from_blendshapes(bs)
        rec.update(face=True, yaw=yaw, pitch=pitch, roll=roll, gaze_h=gaze_h, gaze_v=gaze_v,
                   blink=blink_score(bs), au=au_proxy(bs))
    p = frame.get("p")
    if isinstance(p, list) and len(p) >= 25:
        feats = pose_features([SimpleNamespace(x=float(q[0]), y=float(q[1]), visibility=float(q[2]))
                               for q in p[:25]])
        if feats.pop("shoulders"):
            rec.update(pose=True, **feats)
    return rec


def load_frames(path) -> list:
    """读 frames.jsonl，按服务器时间 t 排序；坏行（写了一半、不是对象、t 不是有限数）跳过。"""
    out = []
    for line in pathlib.Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and _finite(row.get("t")):
            out.append(row)
    out.sort(key=lambda r: r["t"])
    return out


def load_events(path) -> list:
    """问诊记录 → [{"t", "kind"}]：只要 t 是有限数的 user（有文字）与 assistant 事件，按 t 排序。"""
    out = []
    for line in pathlib.Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict) or not _finite(ev.get("t")):
            continue
        kind = ev.get("kind")
        if kind == "assistant" or (kind == "user" and str(ev.get("text") or "").strip()):
            out.append({"t": ev["t"], "kind": kind})
    out.sort(key=lambda e: e["t"])
    return out


def answer_intervals(events) -> list:
    """[(起点, t_u), ...]：每条患者回答一段。起点取「此前最近一条助手回复」与「上一条患者回答」中较晚的
    （患者连说两句时两段不重叠）；都没有（第一句之前只有开场白，开场白不进记录）或早于 t_u - 60 秒时取 t_u - 60 秒。"""
    out, last = [], None
    for ev in events:
        if ev["kind"] == "user":
            t_u = ev["t"]
            start = t_u - MAX_SEGMENT_S
            if last is not None and last > start:
                start = last
            out.append((start, t_u))
        last = ev["t"]
    return out


def summarize_segment(recs, a: float, b: float, baseline) -> dict:
    """相对时间 [a, b] 内的帧 → 一段的检出状态与指标。时间改为相对段内第一帧，窗长 = b - a，
    所以 windows.aggregate 只会给一个窗：摄像头只开了不到半段时记 unknown，眨眼率按实际覆盖的时长算。"""
    seg = [r for r in recs if a <= r["t"] <= b]
    out = {"frames": len(seg), "face_status": "unknown", "body_status": "unknown", "blink_count": None}
    out.update({k: None for k in SEGMENT_KEYS})
    if not seg or b - a <= 0:
        return out
    first = seg[0]["t"]
    wins = aggregate([dict(r, t=r["t"] - first) for r in seg], window=b - a, min_ratio=MIN_RATIO,
                     baseline=baseline, min_frames=MIN_FRAMES)
    if len(wins) != 1:  # 只有一帧（时长为 0）时没有窗
        return out
    w = wins[0]
    out.update(face_status=w["face_status"], body_status=w["body_status"])
    if w["face_status"] == "ok":
        out.update(gaze_away_ratio=w["gaze"]["away_ratio"], blink_count=w["blink"]["count"],
                   blink_per_min=w["blink"]["per_min"], head_motion_deg_per_frame=w["head"]["motion_deg_per_frame"])
    if w["body_status"] == "ok":
        out.update(hand_face_ratio=w["body"]["hand_face_ratio"], body_motion_x1000=w["body"]["motion_x1000"])
    return out


def _median(values):
    xs = [v for v in values if v is not None]
    return round(float(np.median(xs)), 2) if xs else None


def build_observation(frames, events, session_id: str = "") -> dict:
    """逐帧数值 + 问诊事件 → observe.json 的内容。frames 为 load_frames 的结果（已按 t 排序）。"""
    t0 = frames[0]["t"] if frames else 0.0
    recs = []
    for fr in frames:
        try:
            recs.append(to_frame_record(fr, t0))
        except (KeyError, TypeError, ValueError, IndexError):
            continue  # 单帧数据不全就跳过，不影响其余帧
    baseline = individual_baseline(recs, BASELINE_S) if recs else None
    segments = []
    for start, t_u in answer_intervals(events):
        seg = {"t": t_u, "interval": [round(start, 3), round(t_u, 3)]}
        # 摄像头开启之前没有「漏看」：起点不早于第一帧，否则第一句回答（前面只有开场白）总是覆盖不足
        seg.update(summarize_segment(recs, max(start - t0, 0.0), t_u - t0, baseline))
        segments.append(seg)
    n = len(recs)
    return {
        "schema_version": SCHEMA_VERSION,
        "notice": NOTICE,
        "session_id": session_id,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "camera_frames": n,
        "face_detect_ratio": round(sum(r["face"] for r in recs) / n, 2) if n else 0.0,
        "pose_detect_ratio": round(sum(r["pose"] for r in recs) / n, 2) if n else 0.0,
        "min_frames": MIN_FRAMES,
        "min_ratio": MIN_RATIO,
        "max_segment_s": MAX_SEGMENT_S,
        "baseline": ({k: (round(v, 3) if isinstance(v, float) else v) for k, v in baseline.items()}
                     if baseline else None),
        "medians": {k: _median(s[k] for s in segments) for k in SEGMENT_KEYS},
        "segments": segments,
    }


def write_observation(obs: dict, out_dir) -> pathlib.Path:
    """写 <out_dir>/<会话>.observe.json：先写同目录临时文件再改名，医生端不会读到写了一半的文件。"""
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{obs['session_id']}.observe.json"
    fd, tmp = tempfile.mkstemp(prefix=dest.name + ".", suffix=".tmp", dir=str(out_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obs, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, dest)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return dest


def observe_session(consult_path, frames_path, out_dir) -> pathlib.Path:
    """一次问诊：读 frames 与问诊记录 → 写 observe.json，返回路径。会话编号取问诊记录的文件名。"""
    consult_path = pathlib.Path(consult_path)
    obs = build_observation(load_frames(frames_path), load_events(consult_path), session_id=consult_path.stem)
    return write_observation(obs, out_dir)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m apps.emotion.face_body.live",
                                description="浏览器打点的逐帧数值 + 问诊记录 → 每条患者回答的同期观察（observe.json）")
    p.add_argument("--consult", required=True, help="问诊记录 <会话>.jsonl")
    p.add_argument("--frames", required=True, help="<会话>.frames.jsonl")
    p.add_argument("--out-dir", required=True)
    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    path = observe_session(args.consult, args.frames, args.out_dir)
    data = json.loads(path.read_text(encoding="utf-8"))
    ok = sum(1 for s in data["segments"] if s["face_status"] == "ok" or s["body_status"] == "ok")
    print(f"{path.name}：{data['camera_frames']} 帧，{len(data['segments'])} 段回答，其中 {ok} 段有数")
    return 0


if __name__ == "__main__":
    sys.exit(main())
````

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest apps/emotion/face_body/tests/test_live.py -q -p no:cacheprovider`
Expected: `19 passed`
Run: `python -m pytest apps/emotion/face_body/tests -q -p no:cacheprovider`
Expected: `62 passed`（原有 43 个不受影响）

- [ ] **Step 5: Commit**

```bash
git add apps/emotion/face_body/live.py apps/emotion/face_body/tests/test_live.py
git commit -m "feat(face_body): 实时通道 live.py，按每条患者回答统计同期观察 (#8)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `emotion-judge-watch` 在会话结束后生成 observe.json

**Files:**
- Modify: `apps/emotion/judge/watch.py`（模块文档 `:1-16`、常量 `:33-35`、`PoliteBackend` 之前 `:129`、`describe` `:194-202`、`build_parser` `:225`、`main` `:230-256`）
- Modify: `apps/emotion/deploy/spark.env:23-26`
- Test: `apps/emotion/judge/tests/test_watch.py`（文件末尾追加）

**Interfaces:**
- Consumes：`apps.emotion.face_body.live.observe_session(consult_path, frames_path, out_dir) -> Path`（Task 2）；`watch._scan(path) -> (ended, patient)`（已有）。
- Produces：`watch.DEFAULT_OBS_DIR = "~/livetalking-logs/observations"`；`watch.observe_pending(consult_dir, obs_dir, out_dir, now=None, idle_s=IDLE_S) -> list[(sid, record_path, frames_path)]`；`watch.run_observe(consult_dir, obs_dir, out_dir, now=None, idle_s=IDLE_S, failures=None) -> list[dict]`（`{"session_id", "status": "observe", "segments", "measured", "seconds"}` 或 `{"session_id", "status": "observe_error", "error": 异常类名, "seconds"}`）；命令行 `--obs-dir`（默认 `$EMOTION_OBS_DIR`，否则 `~/livetalking-logs/observations`）；`spark.env` 导出 `EMOTION_OBS_DIR`。observe.json 写在 judge 的 `--out-dir`（Spark 上是 `$EMOTION_OUT/judge/consult`），与 `<会话>.judge.json` 同目录——Task 4 的 doctor_service 从 `DOCTOR_JUDGE_DIR` 读它。

- [ ] **Step 1: Write the failing tests**

在 `apps/emotion/judge/tests/test_watch.py` 末尾追加：
（在文件末尾空两行后追加）

````python
# ---- #8 实时摄像头观察：会话结束后生成 observe.json，不经过大模型 ----

def _obs_dirs(tmp_path):
    rec, out = _dirs(tmp_path)
    obs = tmp_path / "obs"
    obs.mkdir()
    return rec, out, obs


def _frames(path, n=20, t0=1.0, mtime=None):
    """n 帧没有检出的空帧（f / p 都是 null）：够 live.py 生成段落，不依赖具体数值。"""
    path.write_text("".join(json.dumps({"t": t0 + i / 5, "f": None, "p": None}) + "\n" for i in range(n)),
                    encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_observe_is_built_for_an_ended_session_with_frames(tmp_path):
    rec, out, obs = _obs_dirs(tmp_path)
    _write(rec / "s1.jsonl", ENDED, mtime=NOW - 10)
    _frames(obs / "s1.frames.jsonl", mtime=NOW - 10)
    _write(rec / "s2.jsonl", ONGOING, mtime=NOW - 20)            # 还在问：不生成
    _frames(obs / "s2.frames.jsonl", mtime=NOW - 20)
    _write(rec / "s3.jsonl", ENDED, mtime=NOW - 10)              # 没开摄像头：不生成
    done = watch.run_observe(rec, obs, out, now=NOW, idle_s=180)
    assert [(d["session_id"], d["status"]) for d in done] == [("s1", "observe")]
    data = json.loads((out / "s1.observe.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == "face_body-live-0.1" and [s["t"] for s in data["segments"]] == [2.0]
    assert not (out / "s2.observe.json").exists() and not (out / "s3.observe.json").exists()
    assert "s1 同期观察已生成：1 段回答" in describe(done[0])


def test_observe_is_not_rebuilt_until_frames_or_record_change(tmp_path):
    rec, out, obs = _obs_dirs(tmp_path)
    _write(rec / "s1.jsonl", ENDED, mtime=NOW - 100)
    _frames(obs / "s1.frames.jsonl", mtime=NOW - 100)
    assert len(watch.run_observe(rec, obs, out, now=NOW, idle_s=180)) == 1
    assert watch.run_observe(rec, obs, out, now=NOW + 30, idle_s=180) == []   # 没变化：不重算
    later = (out / "s1.observe.json").stat().st_mtime + 5
    _frames(obs / "s1.frames.jsonl", n=30, mtime=later)                       # 问诊结束后又到了一批帧
    assert [d["status"] for d in watch.run_observe(rec, obs, out, now=NOW + 60, idle_s=180)] == ["observe"]


def test_observe_error_is_logged_by_class_and_does_not_block_judge(tmp_path, monkeypatch, capsys):
    from apps.emotion.face_body import live
    rec, out, obs = _obs_dirs(tmp_path)
    _write(rec / "abcdef123456.jsonl", ENDED, mtime=NOW - 10)
    _frames(obs / "abcdef123456.frames.jsonl", mtime=NOW - 10)

    def boom(*args, **kwargs):
        raise ValueError("胃疼两天了")  # 异常文本可能带对话内容：日志只能有类名

    monkeypatch.setattr(live, "observe_session", boom)
    argv = ["--once", "--consult-dir", str(rec), "--out-dir", str(out), "--obs-dir", str(obs)]
    assert main(argv, backend=AlwaysAnswer()) == 0
    printed = capsys.readouterr().out
    assert "同期观察出错：ValueError" in printed and "胃疼" not in printed
    assert (out / "abcdef123456.judge.json").is_file() and not (out / "abcdef123456.observe.json").exists()


def test_failed_observe_is_not_retried_on_the_same_data(tmp_path, monkeypatch):
    from apps.emotion.face_body import live
    rec, out, obs = _obs_dirs(tmp_path)
    _write(rec / "s1.jsonl", ENDED, mtime=NOW - 10)
    _frames(obs / "s1.frames.jsonl", mtime=NOW - 10)
    real = live.observe_session
    monkeypatch.setattr(live, "observe_session", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    failures = {}
    assert [d["status"] for d in watch.run_observe(rec, obs, out, now=NOW, failures=failures)] == ["observe_error"]
    monkeypatch.setattr(live, "observe_session", real)
    assert watch.run_observe(rec, obs, out, now=NOW + 30, failures=failures) == []  # 同样的数据：不空转
    _frames(obs / "s1.frames.jsonl", n=25, mtime=NOW + 40)
    assert [d["status"] for d in watch.run_observe(rec, obs, out, now=NOW + 60, failures=failures)] == ["observe"]


def test_observe_is_written_even_when_the_judge_backend_is_down(tmp_path):
    rec, out, obs = _obs_dirs(tmp_path)
    _write(rec / "s1.jsonl", ENDED, mtime=NOW - 10)
    _frames(obs / "s1.frames.jsonl", mtime=NOW - 10)
    argv = ["--once", "--consult-dir", str(rec), "--out-dir", str(out), "--obs-dir", str(obs)]
    assert main(argv, backend=Down()) == 0  # 大模型不在线：judge 失败退避，同期观察照常生成
    assert (out / "s1.observe.json").is_file() and not (out / "s1.judge.json").exists()
````

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest apps/emotion/judge/tests/test_watch.py -q -p no:cacheprovider`
Expected: FAIL —— `5 failed, 16 passed`：新加的 5 个失败（3 个 `AttributeError: module 'apps.emotion.judge.watch' has no attribute 'run_observe'`，2 个是 `main` 报 `unrecognized arguments: --obs-dir` 的 `SystemExit: 2`），原有的 16 个照常通过。

- [ ] **Step 3: Implement**

在 `apps/emotion/judge/watch.py` 依次做下面 8 处替换：
第 1 处 · `apps/emotion/judge/watch.py`

查找：

````python
单条会话出意外（坏文件、磁盘、后端抛了别的异常）只让这一条退避，其余会话照常，进程不退出；日志只写异常类名。
"""
````

替换为：

````python
单条会话出意外（坏文件、磁盘、后端抛了别的异常）只让这一条退避，其余会话照常，进程不退出；日志只写异常类名。
同期观察：患者开了摄像头的会话（--obs-dir 里有 <会话>.frames.jsonl），结束后先用 face_body/live.py 生成
`<out-dir>/<会话>.observe.json`；只算数值，不调用大模型、不等模型空闲，出错只记异常类名，不影响 judge。
"""
````

第 2 处 · `apps/emotion/judge/watch.py`

查找：

````python
DEFAULT_LT_ADMIN = "http://127.0.0.1:8010/api/admin/sessions"
````

替换为：

````python
DEFAULT_LT_ADMIN = "http://127.0.0.1:8010/api/admin/sessions"
DEFAULT_OBS_DIR = "~/livetalking-logs/observations"
````

第 3 处 · `apps/emotion/judge/watch.py`

查找：

````python
class PoliteBackend:
````

替换为：

````python
def observe_pending(consult_dir, obs_dir, out_dir, now=None, idle_s: float = IDLE_S) -> list:
    """需要（重新）生成同期观察的 (会话编号, 问诊记录, frames)，按文件名排序。
    条件：有 frames 与问诊记录；会话已结束（与 judge 同一标准：有 summary，或 idle_s 秒没新内容）；
    observe.json 不存在，或比 frames、问诊记录旧（问诊结束后才到的 frames 也会触发重算）。"""
    now = time.time() if now is None else now
    consult_dir, obs_dir, out_dir = pathlib.Path(consult_dir), pathlib.Path(obs_dir), pathlib.Path(out_dir)
    if not obs_dir.is_dir() or not consult_dir.is_dir():
        return []
    todo = []
    for frames in sorted(obs_dir.glob("*.frames.jsonl")):
        sid = frames.name[:-len(".frames.jsonl")]
        record = consult_dir / f"{sid}.jsonl"
        result = out_dir / f"{sid}.observe.json"
        try:
            if not record.is_file():
                continue
            rec_m, fr_m = record.stat().st_mtime, frames.stat().st_mtime
            if result.is_file() and result.stat().st_mtime >= max(rec_m, fr_m):
                continue
            ended, _patient = _scan(record)
        except OSError:
            continue
        if ended or now - rec_m >= idle_s:
            todo.append((sid, record, frames))
    return todo


def run_observe(consult_dir, obs_dir, out_dir, now=None, idle_s: float = IDLE_S, failures=None) -> list:
    """给已结束的会话生成 observe.json。不经过 PoliteBackend、不占模型；一条出错只记类名，
    同样的数据不再重试（frames 或问诊记录变了再试），不影响其余会话和 judge。"""
    failures = {} if failures is None else failures
    try:
        from ..face_body import live
    except ImportError:  # 只部署了 judge、没部署 face_body：跳过同期观察
        return []
    out_dir = pathlib.Path(out_dir)
    done = []
    for sid, record, frames in observe_pending(consult_dir, obs_dir, out_dir, now, idle_s):
        started, key = time.time(), None
        try:
            key = max(record.stat().st_mtime, frames.stat().st_mtime)
            if failures.get(sid) == key:
                continue
            path = live.observe_session(record, frames, out_dir)
            if max(record.stat().st_mtime, frames.stat().st_mtime) != key:  # 生成期间又来了数据：下一轮再算
                os.utime(path, (key, key))
            segments = json.loads(path.read_text(encoding="utf-8")).get("segments") or []
        except Exception as exc:  # noqa: BLE001 - 同期观察出错不能拖垮 judge
            failures[sid] = key
            done.append({"session_id": sid, "status": "observe_error", "error": type(exc).__name__,
                         "seconds": round(time.time() - started, 1)})
            continue
        failures.pop(sid, None)
        done.append({"session_id": sid, "status": "observe", "segments": len(segments),
                     "measured": sum(1 for s in segments if "ok" in (s.get("face_status"), s.get("body_status"))),
                     "seconds": round(time.time() - started, 1)})
    return done


class PoliteBackend:
````

第 4 处 · `apps/emotion/judge/watch.py`

查找：

````python
def describe(item: dict) -> str:
    sid = item["session_id"][:8]
    if item["status"] == "error":
````

替换为：

````python
def describe(item: dict) -> str:
    sid = item["session_id"][:8]
    if item["status"] == "observe":
        return f"{sid} 同期观察已生成：{item['segments']} 段回答，其中 {item['measured']} 段有数（{item['seconds']}s）"
    if item["status"] == "observe_error":
        return f"{sid} 同期观察出错：{item['error']}，数据更新后再试（{item['seconds']}s）"
    if item["status"] == "error":
````

第 5 处 · `apps/emotion/judge/watch.py`

查找：

````python
    p.add_argument("--lt-admin-url", default=os.environ.get("LT_ADMIN_URL") or DEFAULT_LT_ADMIN)
````

替换为：

````python
    p.add_argument("--lt-admin-url", default=os.environ.get("LT_ADMIN_URL") or DEFAULT_LT_ADMIN)
    p.add_argument("--obs-dir", default=os.environ.get("EMOTION_OBS_DIR") or DEFAULT_OBS_DIR,
                   help="患者页摄像头观察的逐帧数值（doctor_service 写的 <会话>.frames.jsonl）")
````

第 6 处 · `apps/emotion/judge/watch.py`

查找：

````python
    consult_dir = pathlib.Path(args.consult_dir).expanduser()
    out_dir = pathlib.Path(args.out_dir).expanduser()
````

替换为：

````python
    consult_dir = pathlib.Path(args.consult_dir).expanduser()
    out_dir = pathlib.Path(args.out_dir).expanduser()
    obs_dir = pathlib.Path(args.obs_dir).expanduser()
````

第 7 处 · `apps/emotion/judge/watch.py`

查找：

````python
        f"结束或静默 {args.idle:.0f}s 后判断")
````

替换为：

````python
        f"结束或静默 {args.idle:.0f}s 后判断；同期观察读 {obs_dir}")
````

第 8 处 · `apps/emotion/judge/watch.py`

查找：

````python
    failures: dict = {}
    while True:
        ok = True
        try:
            for item in run_once(
````

替换为：

````python
    failures: dict = {}
    obs_failures: dict = {}
    while True:
        ok = True
        try:  # 同期观察先做：只算数值、很快，不用等 judge 给数字人让路
            for item in run_observe(consult_dir, obs_dir, out_dir, idle_s=args.idle, failures=obs_failures):
                log(describe(item))
        except Exception as exc:  # noqa: BLE001 - 同期观察出意外不影响 judge
            log(f"本轮同期观察出错：{type(exc).__name__}")
        try:
            for item in run_once(
````

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest apps/emotion/judge/tests -q -p no:cacheprovider`
Expected: `88 passed`

- [ ] **Step 5: `spark.env` 加 `EMOTION_OBS_DIR`**

`apps/emotion/deploy/spark.env`

查找：

````bash
: "${LT_ADMIN_URL:=http://127.0.0.1:8010/api/admin/sessions}" # 数字人在线会话；自动判断在有人问诊时让路
export EMOTION_HOME EMOTION_VENV EMOTION_OUT VIEWER_PORT FACE_BODY_MODEL_DIR PIP_MIRROR PROXY \
       LOCAL_LLM_BASE_URL LOCAL_LLM_MODEL LOCAL_LLM_KEY_FILE CONSULT_DIR LT_ADMIN_URL
````

替换为：

````bash
: "${LT_ADMIN_URL:=http://127.0.0.1:8010/api/admin/sessions}" # 数字人在线会话；自动判断在有人问诊时让路
# 患者页摄像头观察的关键点数值（阶段二 doctor_service 写入）；与 ~/livetalking-deploy/env.sh 的 DOCTOR_OBS_DIR 必须相同
: "${EMOTION_OBS_DIR:=$HOME/livetalking-logs/observations}"
export EMOTION_HOME EMOTION_VENV EMOTION_OUT VIEWER_PORT FACE_BODY_MODEL_DIR PIP_MIRROR PROXY \
       LOCAL_LLM_BASE_URL LOCAL_LLM_MODEL LOCAL_LLM_KEY_FILE CONSULT_DIR LT_ADMIN_URL EMOTION_OBS_DIR
````

Run: `bash -n apps/emotion/deploy/spark.env && EMOTION_LOCAL_ENV=/nonexistent bash -c 'source apps/emotion/deploy/spark.env; echo "$EMOTION_OBS_DIR"'`
Expected: 打印 `<你的 HOME>/livetalking-logs/observations`，没有报错。

- [ ] **Step 6: Commit**

```bash
git add apps/emotion/judge/watch.py apps/emotion/judge/tests/test_watch.py apps/emotion/deploy/spark.env
git commit -m "feat(judge): watch 在问诊结束后生成摄像头同期观察，不经过大模型 (#8)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: doctor_service：接收关键点数值，`/highlights` 附同期观察

**Files:**
- Modify: `apps/multimodal/deploy/livetalking/doctor_service.py`（文档与 import `:1-28`、常量 `:43-44` 之后、CORS `:50-55`、`_recorder_disabled` `:75-76` 之后、`/health` `:181-194`、`/highlights` `:257-287`，新路由接在 `/highlights` 之后）
- Modify: `apps/multimodal/deploy/livetalking/env.sh:112`、`:149`
- Modify: `apps/multimodal/deploy/livetalking/14_setup_doctor_console.sh:59-61`、`:74`
- Create: `apps/multimodal/deploy/livetalking/tests/conftest.py`
- Test: `apps/multimodal/deploy/livetalking/tests/test_doctor_observe.py`

**Interfaces:**
- Consumes：Task 2 的 `CAM_BLENDSHAPES`（复制一份，测试核对一致）、observe.json 结构；Task 3 把 observe.json 写到 `DOCTOR_JUDGE_DIR`。
- Produces（Task 6、7、9 用）：
  - `POST /api/observe/{sid}`，请求体 `{"v": "cam-0.1", "sent_ct": 毫秒, "frames": [{"ct": 毫秒, "f": null | {"bs": {26 个}, "m": [16]}, "p": null | 25 × [x, y, visibility]}]}` → 200 `{"ok": true, "accepted": n}`；非法 → 400；请求体 > 64 KB 或文件将超 20 MB → 413；`DOCTOR_OBSERVE=0` → 404。每条写成一行 `{"t": 服务器秒（3 位小数）, "f": …, "p": …}` 追加到 `<OBS_DIR>/<sid>.frames.jsonl`。
  - `GET /api/doctor/sessions/{sid}/highlights` 在原有字段外，**无论 judge 是否就绪**都带：`camera: bool`、`observe_ready: bool`、`observe_segments: [段]`（白名单字段：`t, interval, frames, face_status, body_status, gaze_away_ratio, blink_count, blink_per_min, head_motion_deg_per_frame, hand_face_ratio, body_motion_x1000`）、`observe_medians: {5 个键}`；judge 就绪时每条命中多 `observe: 段 | null`（`abs(hit.t - seg.t) < 0.5`）。
  - `/health` 多 `obs_dir`、`obs_dir_exists`、`observe_enabled`；CORS 允许 `GET`、`POST`。
  - 模块级 `OBS_DIR`、`OBS_MAX_BODY`、`OBS_MAX_FRAMES`、`OBS_MAX_FILE`、`OBS_MAX_AGE_MS`、`CAM_BLENDSHAPES`；环境变量 `DOCTOR_OBS_DIR`（默认 `~/livetalking-logs/observations`）、`DOCTOR_OBSERVE`（默认 `1`，请求时读取）。

- [ ] **Step 1: Write the failing tests**

Create `apps/multimodal/deploy/livetalking/tests/conftest.py`：
````python
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
````

Create `apps/multimodal/deploy/livetalking/tests/test_doctor_observe.py`：
````python
# -*- coding: utf-8 -*-
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

SID = "0f3c9a4e-2b7d-4c1a-9e8f-5a6b7c8d9e0f"


def _frame(ct, face=True, pose=True):
    f = {"bs": {k: 0.1 for k in _cam()}, "m": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1.5, -2, -45, 1]} if face else None
    p = [[0.5, 0.5, 0.9] for _ in range(25)] if pose else None
    return {"ct": ct, "f": f, "p": p}


def _cam():
    import doctor_service
    return doctor_service.CAM_BLENDSHAPES


def _batch(n=3, sent=1_790_000_000_000, age_ms=400, **kw):
    return {"v": "cam-0.1", "sent_ct": sent, "frames": [_frame(sent - age_ms - 200 * i, **kw) for i in range(n)]}


def _lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def test_valid_batch_is_appended_with_server_time_and_without_client_time(ds):
    mod, dirs = ds
    client = TestClient(mod.app)
    before = time.time()
    r = client.post(f"/api/observe/{SID}", json=_batch(3))
    after = time.time()
    assert r.status_code == 200 and r.json() == {"ok": True, "accepted": 3}
    rows = _lines(dirs["obs"] / f"{SID}.frames.jsonl")
    assert len(rows) == 3 and all(set(row) == {"t", "f", "p"} for row in rows)
    assert before - 0.4 - 0.01 <= rows[0]["t"] <= after - 0.4 + 0.01   # 采集时刻 = 收到时刻 - 0.4 秒
    assert rows[1]["t"] == pytest.approx(rows[0]["t"] - 0.2, abs=2e-3)
    client.post(f"/api/observe/{SID}", json=_batch(2))
    assert len(_lines(dirs["obs"] / f"{SID}.frames.jsonl")) == 5      # 追加，不覆盖（重连沿用同一会话编号）


def test_browser_clock_far_off_does_not_shift_server_time(ds):
    mod, dirs = ds
    skewed = int((time.time() + 3600) * 1000)   # 患者电脑时钟快了一小时
    assert TestClient(mod.app).post(f"/api/observe/{SID}", json=_batch(1, sent=skewed)).status_code == 200
    (row,) = _lines(dirs["obs"] / f"{SID}.frames.jsonl")
    assert abs(row["t"] - time.time()) < 5


def test_frames_without_face_or_pose_are_kept_as_null(ds):
    mod, dirs = ds
    r = TestClient(mod.app).post(f"/api/observe/{SID}", json=_batch(2, face=False, pose=False))
    assert r.status_code == 200
    assert all(row["f"] is None and row["p"] is None for row in _lines(dirs["obs"] / f"{SID}.frames.jsonl"))


@pytest.mark.parametrize("sid", ["short", "bad.sid.1234", "a" * 65, "..%2F..%2Fetc12"])
def test_bad_session_id_is_rejected(ds, sid):
    mod, dirs = ds
    assert TestClient(mod.app).post(f"/api/observe/{sid}", json=_batch(1)).status_code in (400, 404)
    assert list(dirs["obs"].iterdir()) == []


def _mutate(kind):
    b = _batch(2)
    fr = b["frames"][0]
    if kind == "missing_bs":
        fr["f"]["bs"].pop("jawOpen")
    elif kind == "extra_bs":
        fr["f"]["bs"]["tongueOut"] = 0.1
    elif kind == "short_matrix":
        fr["f"]["m"] = fr["f"]["m"][:15]
    elif kind == "pose_24":
        fr["p"] = fr["p"][:24]
    elif kind == "pose_point_2":
        fr["p"][3] = [0.5, 0.5]
    elif kind == "bool_value":
        fr["f"]["bs"]["eyeBlinkLeft"] = True
    elif kind == "string_value":
        fr["p"][0][0] = "0.5"
    elif kind == "extra_frame_key":
        fr["img"] = "data:image/jpeg;base64,xxxx"   # 任何图像字段都不收
    elif kind == "future_frame":
        fr["ct"] = b["sent_ct"] + 5000
    elif kind == "too_old":
        fr["ct"] = b["sent_ct"] - 120_000
    elif kind == "wrong_version":
        b["v"] = "cam-9"
    elif kind == "no_frames":
        b["frames"] = []
    elif kind == "too_many_frames":
        b["frames"] = [_frame(b["sent_ct"] - 10 * i) for i in range(51)]
    return b


@pytest.mark.parametrize("kind", ["missing_bs", "extra_bs", "short_matrix", "pose_24", "pose_point_2", "bool_value",
                                  "string_value", "extra_frame_key", "future_frame", "too_old", "wrong_version",
                                  "no_frames", "too_many_frames"])
def test_any_bad_field_rejects_the_whole_batch(ds, kind):
    mod, dirs = ds
    r = TestClient(mod.app).post(f"/api/observe/{SID}", json=_mutate(kind))
    assert r.status_code == 400
    assert not (dirs["obs"] / f"{SID}.frames.jsonl").exists()


def test_non_finite_numbers_and_non_json_are_rejected(ds):
    mod, dirs = ds
    client = TestClient(mod.app)
    body = json.dumps(_batch(1)).replace("0.1", "NaN", 1)
    headers = {"Content-Type": "application/json"}
    assert client.post(f"/api/observe/{SID}", content=body, headers=headers).status_code == 400
    assert client.post(f"/api/observe/{SID}", content=b"\xff\xfe", headers=headers).status_code == 400
    assert not (dirs["obs"] / f"{SID}.frames.jsonl").exists()


def test_oversized_body_and_full_file_return_413(ds, monkeypatch):
    mod, dirs = ds
    client = TestClient(mod.app)
    big = json.dumps(_batch(2)) + " " * (mod.OBS_MAX_BODY + 1)
    r = client.post(f"/api/observe/{SID}", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    monkeypatch.setattr(mod, "OBS_MAX_FILE", 3000)
    assert client.post(f"/api/observe/{SID}", json=_batch(1)).status_code == 200
    path = dirs["obs"] / f"{SID}.frames.jsonl"
    size = path.stat().st_size
    assert client.post(f"/api/observe/{SID}", json=_batch(3)).status_code == 413
    assert path.stat().st_size == size   # 超限的那批一条都不写


def test_observe_switched_off_returns_404(ds, monkeypatch):
    mod, dirs = ds
    monkeypatch.setenv("DOCTOR_OBSERVE", "0")
    client = TestClient(mod.app)
    assert client.post(f"/api/observe/{SID}", json=_batch(1)).status_code == 404
    assert client.get("/health").json()["observe_enabled"] is False
    assert list(dirs["obs"].iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="Windows 没有 POSIX 权限位")
def test_frames_file_is_owner_only(ds, tmp_path, monkeypatch):
    mod, dirs = ds
    fresh = tmp_path / "fresh-obs"
    monkeypatch.setattr(mod, "OBS_DIR", str(fresh))
    assert TestClient(mod.app).post(f"/api/observe/{SID}", json=_batch(1)).status_code == 200
    assert (fresh.stat().st_mode & 0o777) == 0o700
    assert ((fresh / f"{SID}.frames.jsonl").stat().st_mode & 0o777) == 0o600


def test_cors_preflight_allows_post_from_the_patient_page(ds):
    mod, _ = ds
    r = TestClient(mod.app).options(f"/api/observe/{SID}", headers={
        "Origin": "http://127.0.0.1:8010", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200
    assert "POST" in r.headers["access-control-allow-methods"]
    assert "content-type" in r.headers["access-control-allow-headers"].lower()


def test_health_reports_observation_settings(ds):
    mod, dirs = ds
    h = TestClient(mod.app).get("/health").json()
    assert h["obs_dir"] == str(dirs["obs"]) and h["obs_dir_exists"] is True and h["observe_enabled"] is True
    assert h["ok"] is True and "judge_dir" in h   # 原有字段不变


OBSERVE = {
    "schema_version": "face_body-live-0.1", "camera_frames": 120,
    "medians": {"gaze_away_ratio": 0.2, "blink_per_min": 12.0, "head_motion_deg_per_frame": 0.5,
                "hand_face_ratio": 0.0, "body_motion_x1000": 0.6},
    "segments": [
        {"t": 1790000020.123456, "interval": [1790000008.0, 1790000020.123], "frames": 60, "face_status": "ok",
         "body_status": "ok", "gaze_away_ratio": 0.3, "blink_count": 3, "blink_per_min": 18.0,
         "head_motion_deg_per_frame": 0.6, "hand_face_ratio": 0.1, "body_motion_x1000": 0.8, "secret": "x"},
        {"t": 1790000035.5, "interval": [1790000022.0, 1790000035.5], "frames": 3, "face_status": "unknown",
         "body_status": "unknown", "gaze_away_ratio": None, "blink_count": None, "blink_per_min": None,
         "head_motion_deg_per_frame": None, "hand_face_ratio": None, "body_motion_x1000": None},
    ],
}
JUDGE = {"generated_at": "2026-09-29T12:00:00+00:00", "review_notice": "待医务人员确认", "schema_version": "judge-0.1",
         "errors": 0, "hits": [{"t": 1790000020.123456, "turn_index": 1, "text": "胃疼", "risk": False},
                               {"t": 1790000099.0, "turn_index": 5, "text": "没有了", "risk": False}]}


def _put(dirs, judge=None, observe=None, frames=False):
    if judge is not None:
        (dirs["judge"] / f"{SID}.judge.json").write_text(json.dumps(judge), encoding="utf-8")
    if observe is not None:
        (dirs["judge"] / f"{SID}.observe.json").write_text(json.dumps(observe), encoding="utf-8")
    if frames:
        (dirs["obs"] / f"{SID}.frames.jsonl").write_text('{"t": 1, "f": null, "p": null}\n', encoding="utf-8")


def test_highlights_attach_the_matching_segment_to_each_hit(ds):
    mod, dirs = ds
    _put(dirs, judge=JUDGE, observe=OBSERVE, frames=True)
    h = TestClient(mod.app).get(f"/api/doctor/sessions/{SID}/highlights").json()
    assert h["ready"] is True and h["camera"] is True and h["observe_ready"] is True
    assert h["hits"][0]["observe"]["gaze_away_ratio"] == 0.3 and "secret" not in h["hits"][0]["observe"]
    assert h["hits"][1]["observe"] is None        # 没有对应段
    assert [s["t"] for s in h["observe_segments"]] == [1790000020.123456, 1790000035.5]
    assert h["observe_medians"]["blink_per_min"] == 12.0


def test_highlights_carry_observation_before_judge_is_ready(ds):
    mod, dirs = ds
    _put(dirs, observe=OBSERVE, frames=True)
    h = TestClient(mod.app).get(f"/api/doctor/sessions/{SID}/highlights").json()
    assert h["ready"] is False and h["hits"] == [] and h["observe_ready"] is True
    assert len(h["observe_segments"]) == 2


def test_session_without_camera_says_so_once_in_the_payload(ds):
    mod, dirs = ds
    _put(dirs, judge=JUDGE)
    h = TestClient(mod.app).get(f"/api/doctor/sessions/{SID}/highlights").json()
    assert h["camera"] is False and h["observe_ready"] is False and h["observe_segments"] == []
    assert all(hit["observe"] is None for hit in h["hits"])


def test_camera_on_but_observation_not_built_yet(ds):
    mod, dirs = ds
    _put(dirs, judge=JUDGE, frames=True)
    h = TestClient(mod.app).get(f"/api/doctor/sessions/{SID}/highlights").json()
    assert h["camera"] is True and h["observe_ready"] is False


def test_broken_observe_file_is_treated_as_not_ready(ds):
    mod, dirs = ds
    _put(dirs, judge=JUDGE, frames=True)
    (dirs["judge"] / f"{SID}.observe.json").write_text('{"segments": [', encoding="utf-8")
    h = TestClient(mod.app).get(f"/api/doctor/sessions/{SID}/highlights").json()
    assert h["ready"] is True and h["observe_ready"] is False and h["observe_segments"] == []


def test_existing_read_endpoints_are_unchanged(ds):
    mod, dirs = ds
    (dirs["rec"] / f"{SID}.jsonl").write_text(
        json.dumps({"t": 1790000020.123456, "kind": "user", "text": "胃疼"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    client = TestClient(mod.app)
    d = client.get(f"/api/doctor/sessions/{SID}").json()
    assert d["messages"] == [{"role": "user", "text": "胃疼", "t": 1790000020.123456, "source": ""}]
    assert client.get("/api/doctor/sessions").json()["total"] == 1
    assert client.get("/api/doctor/sessions/..bad/highlights").status_code == 400
    assert client.post("/api/doctor/sessions").status_code == 405   # 只读接口没有写方法


def test_blendshape_list_matches_phase_three():
    np = pytest.importorskip("numpy")  # noqa: F841 - 阶段三模块需要 numpy
    from apps.emotion.face_body.live import CAM_BLENDSHAPES as live_list
    assert tuple(_cam()) == tuple(live_list)
````

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest apps/multimodal/deploy/livetalking/tests -q -p no:cacheprovider`
Expected: FAIL —— Windows 上汇总为 `1 failed, 1 skipped, 31 errors`：夹具报 `AttributeError: <module 'doctor_service' …> has no attribute 'OBS_DIR'`，三方对照那条报 `has no attribute 'CAM_BLENDSHAPES'`（没有一条通过）。开发机需要 `fastapi`、`httpx`（TestClient 用）、`numpy`；缺的话 `python -m pip install fastapi httpx`。

- [ ] **Step 3: Implement**

在 `apps/multimodal/deploy/livetalking/doctor_service.py` 依次做下面 6 处替换（第 6 处把 `/highlights` 整段换掉，并在它后面加上新的辅助函数和 `POST /api/observe`）：
第 1 处 · `apps/multimodal/deploy/livetalking/doctor_service.py`

查找：

````python
    GET  /api/doctor/sessions/<id>/highlights
                                      阶段三 judge 标出的「重点」（只读；还没生成时 ready=false）

安全边界：只读本机磁盘与回环接口；不做任何诊断判断，也不修改问诊内容。
"""
import json
import os
import time
import urllib.request

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
````

替换为：

````python
    GET  /api/doctor/sessions/<id>/highlights
                                      阶段三 judge 标出的「重点」（只读；还没生成时 ready=false），
                                      并附每条患者回答的摄像头同期观察（observe_segments）
    POST /api/observe/<id>            患者页「摄像头观察」上传的关键点数值（唯一的写接口；DOCTOR_OBSERVE=0 关闭）

安全边界：除 /api/observe 追加写关键点数值外只读本机磁盘与回环接口；不存图像，不做任何诊断判断，也不修改问诊内容。
"""
import json
import math
import os
import re
import threading
import time
import urllib.request

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
````

第 2 处 · `apps/multimodal/deploy/livetalking/doctor_service.py`

查找：

````python
_HIT_FIELDS = ("t", "turn_index", "text", "question", "group", "group_label",
               "importance", "risk", "labels", "evidence", "source")
````

替换为：

````python
_HIT_FIELDS = ("t", "turn_index", "text", "question", "group", "group_label",
               "importance", "risk", "labels", "evidence", "source")
# 摄像头观察：患者页只上传关键点数值（blendshape 分数、头姿矩阵、姿态点），追加写到这里；
# 阶段三 emotion-judge-watch 在问诊结束后读它，生成 <JUDGE_DIR>/<会话>.observe.json
OBS_DIR = os.path.expanduser(os.getenv("DOCTOR_OBS_DIR", "~/livetalking-logs/observations"))
OBS_MAX_BODY = 64 * 1024            # 一批请求体上限（约 2 秒、10 帧，实际十几 KB）
OBS_MAX_FRAMES = 50                 # 一批最多帧数
OBS_MAX_FILE = 20 * 1024 * 1024     # 单个会话的 frames 文件上限，超过返回 413
OBS_MAX_AGE_MS = 60_000             # 一帧的采集时刻最多比发送时刻早 60 秒（只用浏览器时钟的差值，不怕两边时钟不齐）
# 与 apps/emotion/face_body/live.py、apps/multimodal/web/camera-metrics.js 三处一致（有测试核对）；
# 本服务的 venv 没有 numpy，不能 import 阶段三，所以复制一份
CAM_BLENDSHAPES = (
    "eyeLookOutLeft", "eyeLookOutRight", "eyeLookInLeft", "eyeLookInRight",
    "eyeLookUpLeft", "eyeLookUpRight", "eyeLookDownLeft", "eyeLookDownRight",
    "eyeBlinkLeft", "eyeBlinkRight",
    "browInnerUp", "browOuterUpLeft", "browOuterUpRight", "browDownLeft", "browDownRight",
    "cheekSquintLeft", "cheekSquintRight", "eyeSquintLeft", "eyeSquintRight",
    "mouthSmileLeft", "mouthSmileRight", "mouthFrownLeft", "mouthFrownRight",
    "mouthPressLeft", "mouthPressRight", "jawOpen",
)
_CAM_SET = frozenset(CAM_BLENDSHAPES)
_SID_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")   # 与 consult_recorder._safe_sid 同一规则：文件名与问诊记录对齐
_OBS_FIELDS = ("t", "interval", "frames", "face_status", "body_status", "gaze_away_ratio", "blink_count",
               "blink_per_min", "head_motion_deg_per_frame", "hand_face_ratio", "body_motion_x1000")
_OBS_MEDIAN_KEYS = ("gaze_away_ratio", "blink_per_min", "head_motion_deg_per_frame",
                    "hand_face_ratio", "body_motion_x1000")
_OBS_LOCK = threading.Lock()
````

第 3 处 · `apps/multimodal/deploy/livetalking/doctor_service.py`

查找：

````python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)
````

替换为：

````python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],   # POST 只有 /api/observe：患者页（8010）跨端口上传关键点数值
    allow_headers=["*"],             # 含 Content-Type（application/json 会触发预检）
)
````

第 4 处 · `apps/multimodal/deploy/livetalking/doctor_service.py`

查找：

````python
def _recorder_disabled() -> bool:
    return os.getenv("DOCTOR_RECORD", "1") == "0"
````

替换为：

````python
def _recorder_disabled() -> bool:
    return os.getenv("DOCTOR_RECORD", "1") == "0"


def _observe_enabled() -> bool:
    """总开关：DOCTOR_OBSERVE=0 时不收摄像头观察数据（接口 404，患者页按上传失败处理，问诊不受影响）。"""
    return os.getenv("DOCTOR_OBSERVE", "1") != "0"
````

第 5 处 · `apps/multimodal/deploy/livetalking/doctor_service.py`

查找：

````python
        "judge_dir": JUDGE_DIR,
        "judge_dir_exists": os.path.isdir(JUDGE_DIR),
        "live_talking_reachable": bool(_lt_sessions()),
    }
````

替换为：

````python
        "judge_dir": JUDGE_DIR,
        "judge_dir_exists": os.path.isdir(JUDGE_DIR),
        "obs_dir": OBS_DIR,
        "obs_dir_exists": os.path.isdir(OBS_DIR),
        "observe_enabled": _observe_enabled(),
        "live_talking_reachable": bool(_lt_sessions()),
    }
````

第 6 处 · `apps/multimodal/deploy/livetalking/doctor_service.py`

查找：

````python
    path = os.path.join(JUDGE_DIR, "%s.judge.json" % sid)
    if not os.path.isfile(path):
        return {"ready": False, "hits": []}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"ready": False, "hits": [], "error": "重点结果暂时读不了"}
    record = os.path.join(RECORD_DIR, "%s.jsonl" % sid)
    stale = os.path.isfile(record) and os.path.getmtime(record) > os.path.getmtime(path)
    hits = [{k: h.get(k) for k in _HIT_FIELDS}
            for h in (data.get("hits") or []) if isinstance(h, dict)]
    return {
        "ready": True,
        "stale": stale,
        "hits": hits,
        "generated_at": data.get("generated_at"),
        "review_notice": data.get("review_notice") or "",
        "schema_version": data.get("schema_version") or "",
        "errors": data.get("errors") or 0,
    }
````

替换为：

````python
    obs = _observe_payload(sid)   # 同期观察可能比 judge 先出来：judge 还没好时也照常带上
    path = os.path.join(JUDGE_DIR, "%s.judge.json" % sid)
    if not os.path.isfile(path):
        return dict({"ready": False, "hits": []}, **obs)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return dict({"ready": False, "hits": [], "error": "重点结果暂时读不了"}, **obs)
    record = os.path.join(RECORD_DIR, "%s.jsonl" % sid)
    stale = os.path.isfile(record) and os.path.getmtime(record) > os.path.getmtime(path)
    hits = [{k: h.get(k) for k in _HIT_FIELDS}
            for h in (data.get("hits") or []) if isinstance(h, dict)]
    for h in hits:  # 每条命中附上同一句回答的同期观察（按问诊记录的事件时间 t 对齐）
        h["observe"] = _match_segment(h.get("t"), obs["observe_segments"])
    return dict({
        "ready": True,
        "stale": stale,
        "hits": hits,
        "generated_at": data.get("generated_at"),
        "review_notice": data.get("review_notice") or "",
        "schema_version": data.get("schema_version") or "",
        "errors": data.get("errors") or 0,
    }, **obs)


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _observe_payload(sid: str) -> dict:
    """<JUDGE_DIR>/<sid>.observe.json → 白名单字段；camera = 这场开过摄像头（有 frames，或 observe 里有帧）。"""
    data = None
    try:
        with open(os.path.join(JUDGE_DIR, "%s.observe.json" % sid), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        data = None
    segments = [{k: s.get(k) for k in _OBS_FIELDS}
                for s in ((data or {}).get("segments") or []) if isinstance(s, dict) and _num(s.get("t"))]
    medians = (data or {}).get("medians")
    medians = medians if isinstance(medians, dict) else {}
    frames = os.path.join(OBS_DIR, "%s.frames.jsonl" % sid)
    return {
        "camera": os.path.isfile(frames) or bool(data and _num(data.get("camera_frames"))
                                                  and data["camera_frames"] > 0),
        "observe_ready": data is not None,
        "observe_segments": segments,
        "observe_medians": {k: medians.get(k) for k in _OBS_MEDIAN_KEYS},
    }


def _match_segment(t, segments):
    if not _num(t):
        return None
    for seg in segments:
        if abs(seg["t"] - t) < 0.5:
            return seg
    return None


def _check_frame(fr) -> bool:
    """一帧的白名单校验：{"ct": 毫秒, "f": null | {"bs": {26 个有限数}, "m": [16 个有限数]}, "p": null | 25×[x, y, 可见度]}。"""
    if not isinstance(fr, dict) or set(fr) - {"ct", "f", "p"} or not _num(fr.get("ct")):
        return False
    f, p = fr.get("f"), fr.get("p")
    if f is not None:
        if not isinstance(f, dict) or set(f) != {"bs", "m"}:
            return False
        bs, m = f["bs"], f["m"]
        if not isinstance(bs, dict) or set(bs) != _CAM_SET or not all(_num(v) for v in bs.values()):
            return False
        if not isinstance(m, list) or len(m) != 16 or not all(_num(v) for v in m):
            return False
    if p is not None:
        if not isinstance(p, list) or len(p) != 25:
            return False
        if not all(isinstance(q, list) and len(q) == 3 and all(_num(v) for v in q) for q in p):
            return False
    return True


@app.post("/api/observe/{sid}")
async def observe(sid: str, request: Request):
    """患者页摄像头观察的一批关键点数值 → 追加写 <OBS_DIR>/<sid>.frames.jsonl（目录 700、文件 600）。

    整批校验，任何一处不合格整批丢弃（400）；时间换成服务器秒：t = 收到时刻 - (sent_ct - ct) / 1000，
    只用浏览器时钟的差值，两边时钟差多少都不影响。不存图像，也不保存浏览器时间 ct。"""
    if not _observe_enabled():
        raise HTTPException(404, "摄像头观察已关闭")
    if not _SID_RE.fullmatch(sid or ""):
        raise HTTPException(400, "非法会话标识")
    body = await request.body()
    recv = time.time()
    if len(body) > OBS_MAX_BODY:
        raise HTTPException(413, "请求体过大")
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(400, "不是 JSON")
    if not isinstance(data, dict) or data.get("v") != "cam-0.1" or not _num(data.get("sent_ct")):
        raise HTTPException(400, "格式不对")
    frames = data.get("frames")
    if not isinstance(frames, list) or not 1 <= len(frames) <= OBS_MAX_FRAMES:
        raise HTTPException(400, "frames 数量不对")
    if not all(_check_frame(fr) for fr in frames):
        raise HTTPException(400, "帧数据不合格")
    ages = [data["sent_ct"] - fr["ct"] for fr in frames]
    if not all(0 <= a <= OBS_MAX_AGE_MS for a in ages):
        raise HTTPException(400, "帧时间不对")
    lines = "".join(json.dumps({"t": round(recv - a / 1000.0, 3), "f": fr.get("f"), "p": fr.get("p")},
                               separators=(",", ":")) + "\n" for a, fr in zip(ages, frames)).encode("utf-8")
    path = os.path.join(OBS_DIR, "%s.frames.jsonl" % sid)
    with _OBS_LOCK:
        os.makedirs(OBS_DIR, exist_ok=True)
        try:
            os.chmod(OBS_DIR, 0o700)
        except OSError:
            pass
        size = os.path.getsize(path) if os.path.isfile(path) else 0
        if size + len(lines) > OBS_MAX_FILE:
            raise HTTPException(413, "本次问诊的观察数据已达上限")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, lines)
        finally:
            os.close(fd)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return {"ok": True, "accepted": len(frames)}
````

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest apps/multimodal/deploy/livetalking/tests -q -p no:cacheprovider`
Expected: Windows 上 `32 passed, 1 skipped`（权限位那条只在 POSIX 上跑）；Linux 上 `33 passed`。
Run: `python -c "import ast; ast.parse(open('apps/multimodal/deploy/livetalking/doctor_service.py', encoding='utf-8').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 5: 部署配置：`env.sh` 与 `14_setup_doctor_console.sh`**

第 1 处 · `apps/multimodal/deploy/livetalking/env.sh`

查找：

````bash
: "${DOCTOR_RECORD:=1}"                                        # 0 = 暂停问诊记录落盘（一旦涉及隐私演练）
````

替换为：

````bash
: "${DOCTOR_RECORD:=1}"                                        # 0 = 暂停问诊记录落盘（一旦涉及隐私演练）
# 患者页「摄像头观察」：浏览器只上传关键点数值，doctor_service 追加写到这里（与阶段三 spark.env 的 EMOTION_OBS_DIR 必须相同）
: "${DOCTOR_OBS_DIR:=$HOME/livetalking-logs/observations}"
: "${DOCTOR_OBSERVE:=1}"                                       # 0 = 不收摄像头观察数据（接口返回 404，患者页照常问诊）
````

第 2 处 · `apps/multimodal/deploy/livetalking/env.sh`

查找：

````bash
export DOCTOR_ACTIVE_WINDOW DOCTOR_LT_ADMIN_URL DOCTOR_RECORD
````

替换为：

````bash
export DOCTOR_ACTIVE_WINDOW DOCTOR_LT_ADMIN_URL DOCTOR_RECORD DOCTOR_OBS_DIR DOCTOR_OBSERVE
````

第 1 处 · `apps/multimodal/deploy/livetalking/14_setup_doctor_console.sh`

查找：

````bash
echo "==> [3/5] 准备问诊记录目录：$DOCTOR_RECORD_DIR（权限 700）"
mkdir -p "$DOCTOR_RECORD_DIR"
chmod 700 "$DOCTOR_RECORD_DIR"
````

替换为：

````bash
echo "==> [3/5] 准备问诊记录目录：$DOCTOR_RECORD_DIR 与摄像头观察目录：$DOCTOR_OBS_DIR（权限 700）"
mkdir -p "$DOCTOR_RECORD_DIR" "$DOCTOR_OBS_DIR"
chmod 700 "$DOCTOR_RECORD_DIR" "$DOCTOR_OBS_DIR"
````

第 2 处 · `apps/multimodal/deploy/livetalking/14_setup_doctor_console.sh`

查找：

````bash
export DOCTOR_LT_ADMIN_URL DOCTOR_ACTIVE_WINDOW
````

替换为：

````bash
export DOCTOR_LT_ADMIN_URL DOCTOR_ACTIVE_WINDOW DOCTOR_OBS_DIR DOCTOR_OBSERVE
````

Run:
```bash
cd apps/multimodal/deploy/livetalking && bash -n env.sh && bash -n 14_setup_doctor_console.sh && ICE_HOST=127.0.0.1 bash -c 'source ./env.sh; echo "$DOCTOR_OBS_DIR $DOCTOR_OBSERVE"'; cd - >/dev/null
```
Expected: 打印 `<你的 HOME>/livetalking-logs/observations 1`，没有语法错误。

- [ ] **Step 6: Commit**

```bash
git add apps/multimodal/deploy/livetalking/doctor_service.py apps/multimodal/deploy/livetalking/tests apps/multimodal/deploy/livetalking/env.sh apps/multimodal/deploy/livetalking/14_setup_doctor_console.sh
git commit -m "feat(doctor): 接收摄像头关键点数值，重点接口附每条回答的同期观察 (#8)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: `camera-metrics.js`：浏览器端换算与统计（与 live.py 一致性测试）

**Files:**
- Create: `apps/multimodal/web/camera-metrics.js`
- Create: `apps/multimodal/web/tests/make_parity_fixture.py`
- Create（生成物，提交）: `apps/multimodal/web/tests/fixtures/camera-parity.json`
- Test: `apps/multimodal/web/tests/camera-metrics.test.js`

**Interfaces:**
- Consumes：Task 2 的 `live.CAM_BLENDSHAPES`、`live.to_frame_record`、`live.summarize_segment`、`live.BASELINE_S`，`windows.individual_baseline`；Task 4 的 `doctor_service.py` 源码里的 `CAM_BLENDSHAPES = (...)`（测试用正则读出，核对三处一致）。
- Produces（Task 6 用；浏览器里是 `window.CameraMetrics`，node 里 `require()` 得到同一对象）：
  - `CAM_BLENDSHAPES: string[26]`；`CONST = {MATRIX_LAYOUT:'col', GAZE_AWAY:0.25, YAW_AWAY:20, PITCH_AWAY:15, BLINK_CLOSE:0.5, BLINK_OPEN:0.3, SMOOTH_K:9, BASELINE_S:5, MIN_FRAMES:6, MIN_RATIO:0.5, MAX_SEGMENT_S:60, VISIBLE:0.5, HAND_FACE_DIST:0.18}`；
  - `matrixFromFlat(data16, layout?) -> number[4][4]`、`eulerFromMatrix(m) -> {yaw, pitch, roll}`、`gazeFromBlendshapes(bs) -> {h, v}`、`blinkScore(bs) -> number`、`poseFeatures(p25x3) -> {shoulders, handFace, kp}`；
  - `frameRecord({f, p}, tSeconds) -> {t, face, pose, yaw?, pitch?, roll?, gaze_h?, gaze_v?, blink?, hand_face?, kp?}`；
  - `rollingMedian(values, k?)`、`blinkOnsets(values)`、`baseline(recs, seconds?) -> {gaze_h, gaze_v, yaw, pitch, source, frames} | null`；
  - `summarize(recs, base, {window, minFrames?}) -> {frames, face_status, body_status, blink_count, gaze_away_ratio, blink_per_min, head_motion_deg_per_frame, hand_face_ratio, body_motion_x1000}`（与 `live.summarize_segment` 同口径：时间按段内第一帧算、覆盖不到半段记 unknown）；
  - `formatAnswerLine(summary) -> "本次回答观察：目光偏离 20% · 眨眼 18 次/分 · 手触脸 0% · 小动作 0.6"`（帧数 < 6 或两通道都 unknown 时 `"本次回答观察：观察数据不足"`）；
  - `formatLivePanel({baselineReady, yaw, pitch, segment, handFace}) -> "左右转头 +12° · 俯仰 −5° · 本次回答 眨眼 3 次 · 目光偏离 20% · 手触脸 否"`（基线未就绪时 `"正在建立本人基线…"`，检出不足的项显示 `—`）。

- [ ] **Step 1: 写一致性数据生成器**

Create `apps/multimodal/web/tests/make_parity_fixture.py`：
````python
# -*- coding: utf-8 -*-
"""生成 camera-metrics.js 与阶段三 face_body/live.py 的一致性测试数据（合成帧，固定公式、没有随机数）。

    python apps/multimodal/web/tests/make_parity_fixture.py   # 改了 live.py / windows.py 的口径后重跑并提交

输出 fixtures/camera-parity.json：上传格式的逐帧数值 + Python 算出的逐帧记录、本人基线和各段结果；
camera-metrics.test.js 用同一批帧在 node 里算一遍，逐项核对。
"""
import json
import math
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from apps.emotion.face_body import live  # noqa: E402
from apps.emotion.face_body.windows import individual_baseline  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent / "fixtures" / "camera-parity.json"
T0 = 1_790_000_000.0


def _rot(yaw, pitch, roll):
    y, p, r = (math.radians(v) for v in (yaw, pitch, roll))
    rx = np.array([[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]])
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rz = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
    m = np.eye(4)
    m[:3, :3] = rz @ ry @ rx
    m[:3, 3] = [1.5, -2.0, -45.0]
    return [round(float(v), 6) for v in m.T.reshape(-1)]  # 浏览器的排法：列主序


def _frame(i):
    t = i / 5
    face = i % 17 != 0
    pose = i % 13 != 0
    f = None
    if face:
        look = 0.1 + (0.35 if 80 <= i < 120 else 0.0) + 0.05 * math.sin(i / 3)
        blink = 0.9 if i in (20, 21, 55, 56, 57, 140, 141) else (0.45 if i in (58, 59) else 0.05)
        bs = {k: round(0.1 * abs(math.sin(i / 7 + n)), 4) for n, k in enumerate(live.CAM_BLENDSHAPES)}
        bs.update(eyeLookOutLeft=round(look, 4), eyeLookInRight=round(look, 4), eyeLookInLeft=0.05,
                  eyeLookOutRight=0.05, eyeBlinkLeft=blink, eyeBlinkRight=blink)
        f = {"bs": bs, "m": _rot(15 * math.sin(i / 15), 8 * math.sin(i / 23), 3 * math.sin(i / 31))}
    p = None
    if pose:
        dx = 0.002 * math.sin(i / 5)
        p = [[0.5, 0.5, 0.0] for _ in range(25)]
        for j, (x, y) in {0: (0.50, 0.30), 11: (0.62, 0.55), 12: (0.38, 0.55), 13: (0.66, 0.72), 14: (0.34, 0.72),
                          15: (0.70, 0.90), 16: (0.30, 0.90), 23: (0.58, 0.95), 24: (0.42, 0.95)}.items():
            p[j] = [round(x + dx, 5), y, 0.98]
        if 150 <= i < 170:
            p[15] = [round(0.53 + dx, 5), 0.33, 0.97]   # 手触脸
        if i % 29 == 0:
            p[12][2] = 0.2                                # 右肩不可见：这帧不算身体检出
    return {"t": T0 + t, "f": f, "p": p}


def main():
    frames = [_frame(i) for i in range(200)]
    recs = [live.to_frame_record(fr, T0) for fr in frames]
    base = individual_baseline(recs, live.BASELINE_S)
    spans = [(0.0, 39.8), (8.0, 20.0), (16.0, 24.0), (30.0, 39.8), (22.0, 23.0), (35.0, 60.0), (5.0, 5.1)]
    segments = [{"a": a, "b": b, "expect": live.summarize_segment(recs, a, b, base)} for a, b in spans]
    keep = ("t", "face", "pose", "yaw", "pitch", "roll", "gaze_h", "gaze_v", "blink", "hand_face")
    data = {
        "note": "由 make_parity_fixture.py 生成，勿手改",
        "cam_blendshapes": list(live.CAM_BLENDSHAPES),
        "t0": T0,
        "frames": frames,
        "records": [{k: r[k] for k in keep if k in r} for r in recs],
        "baseline": {k: base[k] for k in ("gaze_h", "gaze_v", "yaw", "pitch")},
        "segments": segments,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    ok = sum(1 for s in segments if s["expect"]["face_status"] == "ok")
    print(f"写出 {OUT.name}：{len(frames)} 帧，{len(segments)} 段（其中人脸 ok {ok} 段）")


if __name__ == "__main__":
    main()
````

- [ ] **Step 2: 生成一致性数据**

Run: `python apps/multimodal/web/tests/make_parity_fixture.py`
Expected: `写出 camera-parity.json：200 帧，7 段（其中人脸 ok 5 段）`，生成 `apps/multimodal/web/tests/fixtures/camera-parity.json`（约 290 KB，全是合成数值）。

- [ ] **Step 3: Write the failing test**

Create `apps/multimodal/web/tests/camera-metrics.test.js`：
````javascript
/* camera-metrics.js 的单元测试与「与 face_body/live.py 一致」的核对。
 *   node --test apps/multimodal/web/tests/camera-metrics.test.js
 * fixtures/camera-parity.json 由 make_parity_fixture.py 用 live.py 生成。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const M = require('../camera-metrics.js');
const FIX = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'camera-parity.json'), 'utf8'));

function near(a, b, tol, msg) {
    if (a === null || b === null) { assert.equal(a, b, msg); return; }
    assert.ok(Math.abs(a - b) <= tol, `${msg}: ${a} vs ${b}`);
}

test('CAM_BLENDSHAPES 与 live.py、doctor_service.py 三处一致', () => {
    assert.deepEqual(M.CAM_BLENDSHAPES, FIX.cam_blendshapes);
    const src = fs.readFileSync(path.join(__dirname, '..', '..', 'deploy', 'livetalking', 'doctor_service.py'), 'utf8');
    const block = src.match(/CAM_BLENDSHAPES = \(([\s\S]*?)\)/)[1];
    assert.deepEqual(block.match(/"([A-Za-z]+)"/g).map((s) => s.slice(1, -1)), M.CAM_BLENDSHAPES);
});

test('行列序：平移在哪儿就按哪种排法还原；只有旋转时按声明的排法', () => {
    const c = Math.cos(25 * Math.PI / 180), s = Math.sin(25 * Math.PI / 180);
    const rows = [[c, 0, s, 1.5], [0, 1, 0, -2], [-s, 0, c, -45], [0, 0, 0, 1]];
    const rowMajor = rows.flat();
    const colMajor = [0, 1, 2, 3].flatMap((j) => rows.map((r) => r[j]));
    near(M.eulerFromMatrix(M.matrixFromFlat(colMajor)).yaw, 25, 1e-9, 'col');
    near(M.eulerFromMatrix(M.matrixFromFlat(rowMajor)).yaw, 25, 1e-9, 'row');
    const rotOnly = colMajor.slice();
    rotOnly[12] = rotOnly[13] = rotOnly[14] = 0;
    near(M.eulerFromMatrix(M.matrixFromFlat(rotOnly, 'col')).yaw, 25, 1e-9, 'fallback col');
    near(M.eulerFromMatrix(M.matrixFromFlat(rotOnly, 'row')).yaw, -25, 1e-9, 'fallback row');
});

test('逐帧记录与 live.to_frame_record 一致（头部角度差 < 0.5°）', () => {
    FIX.frames.forEach((fr, i) => {
        const js = M.frameRecord(fr, fr.t - FIX.t0);
        const py = FIX.records[i];
        assert.equal(js.face, py.face, `face #${i}`);
        assert.equal(js.pose, py.pose, `pose #${i}`);
        near(js.t, py.t, 1e-9, `t #${i}`);
        if (py.face) {
            ['yaw', 'pitch', 'roll'].forEach((k) => near(js[k], py[k], 0.5, `${k} #${i}`));
            ['gaze_h', 'gaze_v', 'blink'].forEach((k) => near(js[k], py[k], 1e-9, `${k} #${i}`));
        }
        if (py.pose) { assert.equal(js.hand_face, py.hand_face, `hand_face #${i}`); }
    });
});

test('本人基线与 windows.individual_baseline 一致', () => {
    const recs = FIX.frames.map((fr) => M.frameRecord(fr, fr.t - FIX.t0));
    const base = M.baseline(recs, 5);
    ['gaze_h', 'gaze_v', 'yaw', 'pitch'].forEach((k) => near(base[k], FIX.baseline[k], 1e-9, k));
});

test('各段的状态、眨眼次数、目光偏离、手触脸与 live.summarize_segment 一致', () => {
    const recs = FIX.frames.map((fr) => M.frameRecord(fr, fr.t - FIX.t0));
    const base = M.baseline(recs, 5);
    FIX.segments.forEach(({ a, b, expect }) => {
        const seg = recs.filter((r) => a <= r.t && r.t <= b);
        const got = M.summarize(seg, base, { window: b - a });
        const tag = `[${a}, ${b}]`;
        assert.equal(got.frames, expect.frames, `${tag} frames`);
        assert.equal(got.face_status, expect.face_status, `${tag} face_status`);
        assert.equal(got.body_status, expect.body_status, `${tag} body_status`);
        assert.equal(got.blink_count, expect.blink_count, `${tag} blink_count`);
        near(got.gaze_away_ratio, expect.gaze_away_ratio, 0.011, `${tag} gaze_away_ratio`);
        near(got.blink_per_min, expect.blink_per_min, 0.11, `${tag} blink_per_min`);
        near(got.head_motion_deg_per_frame, expect.head_motion_deg_per_frame, 0.011, `${tag} head_motion`);
        near(got.hand_face_ratio, expect.hand_face_ratio, 0.011, `${tag} hand_face_ratio`);
        near(got.body_motion_x1000, expect.body_motion_x1000, 0.011, `${tag} body_motion`);
    });
    assert.ok(FIX.segments.some((s) => s.expect.face_status === 'ok' && s.expect.gaze_away_ratio > 0),
        '合成数据里至少有一段目光偏离');
    assert.ok(FIX.segments.some((s) => s.expect.blink_count >= 2), '合成数据里至少有一段眨眼 2 次以上');
    assert.ok(FIX.segments.some((s) => s.expect.hand_face_ratio > 0), '合成数据里至少有一段手触脸');
    assert.ok(FIX.segments.some((s) => s.expect.face_status === 'unknown'), '合成数据里至少有一段 unknown');
});

test('回答观察行：有数、只有面部、数据不足', () => {
    const ok = { frames: 60, face_status: 'ok', body_status: 'ok', gaze_away_ratio: 0.2, blink_per_min: 18.04,
        hand_face_ratio: 0, body_motion_x1000: 0.63, blink_count: 4 };
    assert.equal(M.formatAnswerLine(ok), '本次回答观察：目光偏离 20% · 眨眼 18 次/分 · 手触脸 0% · 小动作 0.6');
    const faceOnly = Object.assign({}, ok, { body_status: 'unknown', hand_face_ratio: null, body_motion_x1000: null });
    assert.equal(M.formatAnswerLine(faceOnly), '本次回答观察：目光偏离 20% · 眨眼 18 次/分 · 手触脸 — · 小动作 —');
    assert.equal(M.formatAnswerLine({ frames: 5, face_status: 'ok', body_status: 'ok' }), '本次回答观察：观察数据不足');
    assert.equal(M.formatAnswerLine({ frames: 40, face_status: 'unknown', body_status: 'unknown' }),
        '本次回答观察：观察数据不足');
});

test('实时面板：基线未就绪、有数、检出不足', () => {
    assert.equal(M.formatLivePanel({ baselineReady: false }), '正在建立本人基线…');
    const seg = { face_status: 'ok', blink_count: 3, gaze_away_ratio: 0.2 };
    assert.equal(M.formatLivePanel({ baselineReady: true, yaw: 12.4, pitch: -5.2, segment: seg, handFace: false }),
        '左右转头 +12° · 俯仰 −5° · 本次回答 眨眼 3 次 · 目光偏离 20% · 手触脸 否');
    assert.equal(M.formatLivePanel({ baselineReady: true, yaw: null, pitch: null,
        segment: { face_status: 'unknown' }, handFace: null }),
    '左右转头 — · 俯仰 — · 本次回答 眨眼 — · 目光偏离 — · 手触脸 —');
});
````

- [ ] **Step 4: Run test to verify it fails**

Run: `node --test apps/multimodal/web/tests/camera-metrics.test.js`
Expected: FAIL —— `Error: Cannot find module '../camera-metrics.js'`。

- [ ] **Step 5: Write implementation**

Create `apps/multimodal/web/camera-metrics.js`：
````javascript
/* camera-metrics.js —— 摄像头观察的逐帧换算与统计（纯函数，不碰 DOM，node 可直接测）
 *
 * 口径照搬阶段三 face_body（apps/emotion/face_body/features.py、windows.py、live.py）：
 *   头姿：4×4 头姿矩阵 → yaw / pitch / roll（行列序自动判断，同 live.matrix_from_flat）；
 *   目光：eyeLook* blendshape 差值，9 帧滑动中位数后与本人基线比，偏 > 0.25 或 yaw 偏 > 20° 或 pitch 偏 > 15° 记偏离；
 *   眨眼：两眼 eyeBlink 均值，> 0.5 判闭、< 0.3 判开（滞回）；
 *   手触脸：手腕（可见度 > 0.5）到鼻尖距离 < 0.18；小动作：同一关节相邻帧位移均值 × 1000；
 *   一段检出帧 < 6、检出率 < 0.5、或覆盖不到半段时记 unknown，不给数。
 * 患者页上的数值只作近似展示；医生端看到的权威数值由 Spark 上的 live.py 计算。
 * 浏览器里挂在 window.CameraMetrics；node 里 require() 得到同一个对象。
 */
(function (root, factory) {
    var api = factory();
    if (typeof module === 'object' && module.exports) { module.exports = api; } else { root.CameraMetrics = api; }
}(typeof self !== 'undefined' ? self : this, function () {
    'use strict';

    // 与 apps/emotion/face_body/live.py、apps/multimodal/deploy/livetalking/doctor_service.py 三处一致（有测试核对）
    var CAM_BLENDSHAPES = [
        'eyeLookOutLeft', 'eyeLookOutRight', 'eyeLookInLeft', 'eyeLookInRight',
        'eyeLookUpLeft', 'eyeLookUpRight', 'eyeLookDownLeft', 'eyeLookDownRight',
        'eyeBlinkLeft', 'eyeBlinkRight',
        'browInnerUp', 'browOuterUpLeft', 'browOuterUpRight', 'browDownLeft', 'browDownRight',
        'cheekSquintLeft', 'cheekSquintRight', 'eyeSquintLeft', 'eyeSquintRight',
        'mouthSmileLeft', 'mouthSmileRight', 'mouthFrownLeft', 'mouthFrownRight',
        'mouthPressLeft', 'mouthPressRight', 'jawOpen'
    ];
    var C = {
        MATRIX_LAYOUT: 'col',
        GAZE_AWAY: 0.25, YAW_AWAY: 20, PITCH_AWAY: 15,
        BLINK_CLOSE: 0.5, BLINK_OPEN: 0.3,
        SMOOTH_K: 9, BASELINE_S: 5, MIN_FRAMES: 6, MIN_RATIO: 0.5, MAX_SEGMENT_S: 60,
        VISIBLE: 0.5, HAND_FACE_DIST: 0.18
    };
    var NOSE = 0, L_SHOULDER = 11, R_SHOULDER = 12, L_WRIST = 15, R_WRIST = 16;
    var DEG = 180 / Math.PI;

    function round(x, n) { var k = Math.pow(10, n); return Math.round(x * k) / k; }

    function median(xs) {
        if (!xs.length) { return null; }
        var s = xs.slice().sort(function (a, b) { return a - b; });
        var mid = s.length >> 1;
        return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
    }

    function mean(xs) {
        if (!xs.length) { return null; }
        var sum = 0;
        for (var i = 0; i < xs.length; i += 1) { sum += xs[i]; }
        return sum / xs.length;
    }

    /** 16 个数 → 4×4 行数组。平移落在最后一行说明是列主序（转置）；平移全为 0 时按 layout。 */
    function matrixFromFlat(d, layout) {
        var m = [[d[0], d[1], d[2], d[3]], [d[4], d[5], d[6], d[7]],
            [d[8], d[9], d[10], d[11]], [d[12], d[13], d[14], d[15]]];
        var bottom = Math.abs(m[3][0]) + Math.abs(m[3][1]) + Math.abs(m[3][2]);
        var right = Math.abs(m[0][3]) + Math.abs(m[1][3]) + Math.abs(m[2][3]);
        var col = bottom > right ? true : (right > bottom ? false : (layout || C.MATRIX_LAYOUT) === 'col');
        if (!col) { return m; }
        return [0, 1, 2, 3].map(function (i) { return [m[0][i], m[1][i], m[2][i], m[3][i]]; });
    }

    /** 同 features.euler_from_matrix：→ {yaw, pitch, roll}，单位度。 */
    function eulerFromMatrix(m) {
        var sy = Math.hypot(m[0][0], m[1][0]);
        var pitch, roll;
        if (sy > 1e-6) {
            pitch = Math.atan2(m[2][1], m[2][2]);
            roll = Math.atan2(m[1][0], m[0][0]);
        } else {
            pitch = Math.atan2(-m[1][2], m[1][1]);
            roll = 0;
        }
        return { yaw: Math.atan2(-m[2][0], sy) * DEG, pitch: pitch * DEG, roll: roll * DEG };
    }

    function gazeFromBlendshapes(bs) {
        return {
            h: ((bs.eyeLookOutLeft + bs.eyeLookInRight) - (bs.eyeLookInLeft + bs.eyeLookOutRight)) / 2,
            v: ((bs.eyeLookUpLeft + bs.eyeLookUpRight) - (bs.eyeLookDownLeft + bs.eyeLookDownRight)) / 2
        };
    }

    function blinkScore(bs) { return (bs.eyeBlinkLeft + bs.eyeBlinkRight) / 2; }

    /** 25 个 [x, y, 可见度] → {shoulders, handFace, kp}，同 features.pose_features 里用到的几项。 */
    function poseFeatures(p) {
        var vis = function (i) { return p[i][2] > C.VISIBLE; };
        var dists = [L_WRIST, R_WRIST].filter(vis).map(function (i) {
            return Math.hypot(p[i][0] - p[NOSE][0], p[i][1] - p[NOSE][1]);
        });
        var kp = {};
        for (var i = 0; i < 25; i += 1) { if (vis(i)) { kp[i] = [p[i][0], p[i][1]]; } }
        return {
            shoulders: vis(L_SHOULDER) && vis(R_SHOULDER),
            handFace: dists.length > 0 && Math.min.apply(null, dists) < C.HAND_FACE_DIST,
            kp: kp
        };
    }

    /** 上传格式的一帧 {f, p} + 相对秒数 t → 帧记录（同 live.to_frame_record 的字段）。 */
    function frameRecord(frame, t) {
        var rec = { t: t, face: false, pose: false };
        var f = frame && frame.f;
        if (f && f.bs && f.m && f.m.length === 16) {
            var e = eulerFromMatrix(matrixFromFlat(f.m));
            var g = gazeFromBlendshapes(f.bs);
            rec.face = true;
            rec.yaw = e.yaw; rec.pitch = e.pitch; rec.roll = e.roll;
            rec.gaze_h = g.h; rec.gaze_v = g.v;
            rec.blink = blinkScore(f.bs);
        }
        var p = frame && frame.p;
        if (p && p.length >= 25) {
            var pf = poseFeatures(p);
            if (pf.shoulders) { rec.pose = true; rec.hand_face = pf.handFace; rec.kp = pf.kp; }
        }
        return rec;
    }

    function rollingMedian(values, k) {
        var half = Math.floor((k || C.SMOOTH_K) / 2);
        return values.map(function (_, i) {
            return median(values.slice(Math.max(0, i - half), i + half + 1));
        });
    }

    function blinkOnsets(values) {
        var closed = false;
        return values.map(function (v) {
            var onset = !closed && v > C.BLINK_CLOSE;
            if (onset) { closed = true; } else if (closed && v < C.BLINK_OPEN) { closed = false; }
            return onset;
        });
    }

    /** 本人基线：前 seconds 秒有人脸帧的中位数；前段没有人脸就用全部人脸帧；一帧人脸都没有返回 null。 */
    function baseline(recs, seconds) {
        var faces = recs.filter(function (r) { return r.face; });
        if (!faces.length) { return null; }
        var s = seconds === undefined ? C.BASELINE_S : seconds;
        var early = faces.filter(function (r) { return r.t < s; });
        var use = early.length ? early : faces;
        var out = { source: early.length ? 'first_' + s + 's' : 'all_frames', frames: use.length };
        ['gaze_h', 'gaze_v', 'yaw', 'pitch'].forEach(function (k) {
            out[k] = median(use.map(function (r) { return r[k]; }));
        });
        return out;
    }

    /**
     * 一段帧记录（t 单调）→ 同 live.summarize_segment 的结果。
     * opts.window：这一段的名义时长（秒），覆盖不到一半记 unknown；眨眼率按实际覆盖的时长算。
     */
    function summarize(recs, base, opts) {
        var windowS = (opts && opts.window) || 0;
        var minFrames = (opts && opts.minFrames) || C.MIN_FRAMES;
        var out = {
            frames: recs.length, face_status: 'unknown', body_status: 'unknown', blink_count: null,
            gaze_away_ratio: null, blink_per_min: null, head_motion_deg_per_frame: null,
            hand_face_ratio: null, body_motion_x1000: null
        };
        if (recs.length < 2 || windowS <= 0) { return out; }
        var span = recs[recs.length - 1].t - recs[0].t;
        var ff = recs.filter(function (r) { return r.face; });
        var pf = recs.filter(function (r) { return r.pose; });
        var status = function (n) {
            return n >= minFrames && n / recs.length >= C.MIN_RATIO && span >= windowS / 2 ? 'ok' : 'unknown';
        };
        out.face_status = status(ff.length);
        out.body_status = status(pf.length);
        if (out.face_status === 'ok') {
            var sm = {};
            ['gaze_h', 'gaze_v', 'yaw', 'pitch'].forEach(function (k) {
                sm[k] = rollingMedian(ff.map(function (r) { return r[k]; }));
            });
            if (base) {
                var away = ff.map(function (_, i) {
                    return Math.abs(sm.gaze_h[i] - base.gaze_h) > C.GAZE_AWAY ||
                        Math.abs(sm.gaze_v[i] - base.gaze_v) > C.GAZE_AWAY ||
                        Math.abs(sm.yaw[i] - base.yaw) > C.YAW_AWAY ||
                        Math.abs(sm.pitch[i] - base.pitch) > C.PITCH_AWAY ? 1 : 0;
                });
                out.gaze_away_ratio = round(mean(away), 2);
            }
            var blinks = blinkOnsets(ff.map(function (r) { return r.blink; })).filter(Boolean).length;
            out.blink_count = blinks;
            out.blink_per_min = span > 0 ? round(blinks * 60 / span, 1) : null;
            var dang = [];
            for (var j = 1; j < ff.length; j += 1) {
                dang.push(Math.abs(ff[j].yaw - ff[j - 1].yaw) + Math.abs(ff[j].pitch - ff[j - 1].pitch));
            }
            out.head_motion_deg_per_frame = dang.length ? round(mean(dang), 2) : null;
        }
        if (out.body_status === 'ok') {
            out.hand_face_ratio = round(mean(pf.map(function (r) { return r.hand_face ? 1 : 0; })), 2);
            var moves = [];
            for (var q = 1; q < pf.length; q += 1) {
                var a = pf[q - 1].kp, b = pf[q].kp;
                var common = Object.keys(a).filter(function (k) { return Object.prototype.hasOwnProperty.call(b, k); });
                if (common.length) {
                    moves.push(mean(common.map(function (k) {
                        return Math.hypot(a[k][0] - b[k][0], a[k][1] - b[k][1]);
                    })) * 1000);
                }
            }
            out.body_motion_x1000 = moves.length ? round(mean(moves), 2) : null;
        }
        return out;
    }

    function pct(x) { return x === null || x === undefined ? '—' : Math.round(x * 100) + '%'; }
    function num(x, n) { return x === null || x === undefined ? '—' : String(round(x, n)); }

    /** 每条回答下方的一行。 */
    function formatAnswerLine(s) {
        if (!s || s.frames < C.MIN_FRAMES || (s.face_status !== 'ok' && s.body_status !== 'ok')) {
            return '本次回答观察：观察数据不足';
        }
        return '本次回答观察：目光偏离 ' + pct(s.gaze_away_ratio) +
            ' · 眨眼 ' + (s.blink_per_min === null ? '—' : Math.round(s.blink_per_min) + ' 次/分') +
            ' · 手触脸 ' + pct(s.hand_face_ratio) +
            ' · 小动作 ' + num(s.body_motion_x1000, 1);
    }

    function signed(x) {
        if (x === null || x === undefined) { return '—'; }
        var v = Math.round(x);
        return (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v) + '°';
    }

    /**
     * 小窗下方的实时面板。
     * live = {baselineReady, yaw, pitch（相对基线的度数，没有人脸为 null）, segment（summarize 的结果）, handFace（true/false/null）}
     */
    function formatLivePanel(live) {
        if (!live || !live.baselineReady) { return '正在建立本人基线…'; }
        var s = live.segment || {};
        return '左右转头 ' + signed(live.yaw) + ' · 俯仰 ' + signed(live.pitch) +
            ' · 本次回答 眨眼 ' + (s.face_status === 'ok' ? s.blink_count + ' 次' : '—') +
            ' · 目光偏离 ' + (s.face_status === 'ok' ? pct(s.gaze_away_ratio) : '—') +
            ' · 手触脸 ' + (live.handFace === null || live.handFace === undefined ? '—' : (live.handFace ? '是' : '否'));
    }

    return {
        CAM_BLENDSHAPES: CAM_BLENDSHAPES,
        CONST: C,
        matrixFromFlat: matrixFromFlat,
        eulerFromMatrix: eulerFromMatrix,
        gazeFromBlendshapes: gazeFromBlendshapes,
        blinkScore: blinkScore,
        poseFeatures: poseFeatures,
        frameRecord: frameRecord,
        rollingMedian: rollingMedian,
        blinkOnsets: blinkOnsets,
        baseline: baseline,
        summarize: summarize,
        formatAnswerLine: formatAnswerLine,
        formatLivePanel: formatLivePanel
    };
}));
````

- [ ] **Step 6: Run tests to verify they pass**

Run: `node --check apps/multimodal/web/camera-metrics.js && node --test apps/multimodal/web/tests/camera-metrics.test.js`
Expected: 末尾 `# tests 7`、`# pass 7`、`# fail 0`。

- [ ] **Step 7: Commit**

```bash
git add apps/multimodal/web/camera-metrics.js apps/multimodal/web/tests/make_parity_fixture.py apps/multimodal/web/tests/fixtures/camera-parity.json apps/multimodal/web/tests/camera-metrics.test.js
git commit -m "feat(web): 摄像头观察的浏览器端换算与统计，与 face_body 做一致性测试 (#8)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: 患者页：`camera-observe.js` 与 `triage.*` 钩子

**Files:**
- Create: `apps/multimodal/web/camera-observe.js`
- Create: `apps/multimodal/web/tests/make_face_y4m.py`、`apps/multimodal/web/tests/smoke-camera.mjs`
- Modify: `apps/multimodal/web/triage.html`（`:39` toast 之后、`:72-74` 麦克风条末尾、`:117-120` 脚本）
- Modify: `apps/multimodal/web/triage.css`（`:711` 「响应式」之前、`:728`）
- Modify: `apps/multimodal/web/triage.js`（`addUserMessage` `:225-234`、`onLLMDone` `:554`、`onUserText` `:701`、`hideAvatarToStart` `:784`、`closeAvatar` `:805`、`resumeConsultation` `:923`、`enableSessionUI` `:1049-1055`、`beforeunload` `:1212`、`renderDemo` `:1243-1247`、`init` `:1313-1316`）

**Interfaces:**
- Consumes：Task 5 的 `window.CameraMetrics`（`CAM_BLENDSHAPES`、`CONST`、`frameRecord`、`baseline`、`summarize`、`formatAnswerLine`、`formatLivePanel`）；Task 4 的 `POST :8110/api/observe/<consultId>`；Task 1 的 `headless.mjs` 与本机 `vendor/mediapipe/`；`triage.js` 的 `state.consultId`、`showToast(msg, kind, ms)`。
- Produces：
  - `window.CameraObserve = { init({getConsultId, toast}), sessionReady(), sessionEnded(), markReplyEnd(), onAnswer(msgNode), appendLine(node, text), stop(), debug() }`，`debug()` 返回 `{running, ready, unavailable, baseline, toggle: 'off'|'on'|'loading'|'unavailable', stats: {frames, faces, poses, batches, ok, failed, dropped}}`；
  - DOM：`#cam-toggle`（`data-state`）、`#cam-toggle-label`、`#cam-box`、`#cam-video`、`#cam-canvas`、`#cam-panel-body`、`#cam-fold`；患者气泡下的 `.msg-obs`（含 `.obs-info` 说明图标）；
  - 上传：每 2 秒 `{"v":"cam-0.1","sent_ct":…,"frames":[…]}`（每批 ≤ 50 帧，数值保留 4 位小数，矩阵原样列主序），`?demo=1` 或没有 consultId 时不上传；`?obs_port=<端口>` 只改上传端口（默认 8110）；
  - `addUserMessage(text, source)` 现在返回气泡节点 `wrap`。
- 生命周期：`init` 在 `triage.js` 的 `init()` 里调用；`enableSessionUI` 与 `resumeConsultation` → `sessionReady()`（开关可点）；`hideAvatarToStart`、`closeAvatar`（在清空 consultId 之前）→ `sessionEnded()`（停采集、送出最后一批、释放摄像头、开关变灰）；`beforeunload` → `stop()`；`onLLMDone` → `markReplyEnd()`（下一段从这里算）；`onUserText` → `onAnswer(node)`（统计这一段、加观察行、清零）。断线重连（`reconnect`）不动摄像头，consultId 不变，frames 接着写同一个文件。

- [ ] **Step 1: 写冒烟测试与人脸假视频生成器**

Create `apps/multimodal/web/tests/make_face_y4m.py`：
````python
# -*- coding: utf-8 -*-
"""把一张人脸照片做成 Chrome 假摄像头能用的 Y4M 视频（逐帧轻微转头），只用于本机冒烟测试。

    python apps/multimodal/web/tests/make_face_y4m.py --out <临时目录>/face.y4m [--image <照片>]

不给 --image 时下载 MediaPipe 官方测试图 portrait.jpg（MediaPipe 仓库的公开测试素材）。
照片和视频都只放在临时目录，**不进仓库**；不要用真实患者或同事的照片。需要 numpy、pillow。
Chrome 用法：--use-fake-device-for-media-stream --use-file-for-fake-video-capture=<face.y4m>
"""
import argparse
import math
import pathlib
import urllib.request

import numpy as np
from PIL import Image

PORTRAIT_URL = "https://storage.googleapis.com/mediapipe-assets/portrait.jpg"
W, H, FPS, N = 640, 480, 10, 50   # 5 秒一圈，Chrome 循环播放


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--image")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    src = pathlib.Path(args.image) if args.image else out.with_name("portrait.jpg")
    if not src.is_file():
        urllib.request.urlretrieve(PORTRAIT_URL, src)
    face = Image.open(src).convert("RGB")
    face = face.resize((round(face.width * H / face.height), H))
    with open(out, "wb") as fh:
        fh.write(f"YUV4MPEG2 W{W} H{H} F{FPS}:1 Ip A1:1 C420jpeg\n".encode("ascii"))
        for k in range(N):
            frame = Image.new("RGB", (W, H), (96, 110, 118))
            turned = face.rotate(8 * math.sin(2 * math.pi * k / N), resample=Image.BICUBIC,
                                 fillcolor=(96, 110, 118))
            frame.paste(turned, ((W - turned.width) // 2, 0))
            ycc = np.asarray(frame.convert("YCbCr"), dtype=np.float32)
            y = ycc[:, :, 0].astype(np.uint8)
            u = ycc[:, :, 1].reshape(H // 2, 2, W // 2, 2).mean(axis=(1, 3)).round().astype(np.uint8)
            v = ycc[:, :, 2].reshape(H // 2, 2, W // 2, 2).mean(axis=(1, 3)).round().astype(np.uint8)
            fh.write(b"FRAME\n" + y.tobytes() + u.tobytes() + v.tobytes())
    print(f"写出 {out}（{N} 帧，{W}x{H}，{FPS} fps）")


if __name__ == "__main__":
    main()
````

Create `apps/multimodal/web/tests/smoke-camera.mjs`：
````javascript
// 患者页「摄像头观察」本机冒烟：无头 Chrome + 假摄像头 + 本地静态服务 + 本地 doctor_service。
//
//   node apps/multimodal/web/tests/smoke-camera.mjs [--face <face.y4m>]
//
// 前提：apps/multimodal/web/vendor/mediapipe/ 已按实施计划 Task 1 放好（不进仓库）；python 能 import fastapi、uvicorn。
// 用 18010 / 18110 端口，不碰 8010 / 8110（那两个可能正转发着 Spark）；数据写在系统临时目录，结束后删除。
// 带 --face 时假摄像头播放人脸视频（make_face_y4m.py 生成），要求检出人脸；不带时是 Chrome 自带的测试画面，f 为 null。
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { launchChrome, sleep } from './headless.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(HERE, '..');
const SERVICE = path.resolve(WEB, '..', 'deploy', 'livetalking', 'doctor_service.py');
const PY = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const faceArg = process.argv.indexOf('--face');
const FACE = faceArg > 0 ? path.resolve(process.argv[faceArg + 1]) : '';
const SID = 'smoke-cam-0001';
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'cam-smoke-data-'));
const procs = [];
let failed = 0;

function check(ok, msg) {
    console.log(`${ok ? 'PASS' : 'FAIL'}  ${msg}`);
    if (!ok) { failed += 1; }
}

async function waitHttp(url, ms = 20000) {
    const until = Date.now() + ms;
    for (;;) {
        try { if ((await fetch(url)).ok) { return; } } catch (e) { /* 还没起来 */ }
        if (Date.now() > until) { throw new Error(`服务没起来：${url}`); }
        await sleep(300);
    }
}

function serveStatic(root, port) {
    const p = spawn(PY, ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', root], { stdio: 'ignore' });
    procs.push(p);
    return waitHttp(`http://127.0.0.1:${port}/triage.html`);
}

function startDoctor() {
    for (const d of ['obs', 'rec', 'judge']) { fs.mkdirSync(path.join(tmp, d)); }
    const env = Object.assign({}, process.env, {
        DOCTOR_PORT: '18110', DOCTOR_HOST: '127.0.0.1', DOCTOR_WEB_DIR: WEB,
        DOCTOR_OBS_DIR: path.join(tmp, 'obs'), DOCTOR_RECORD_DIR: path.join(tmp, 'rec'),
        DOCTOR_JUDGE_DIR: path.join(tmp, 'judge'), DOCTOR_LT_ADMIN_URL: 'http://127.0.0.1:9/api/admin/sessions',
    });
    const p = spawn(PY, [SERVICE], { env, stdio: 'ignore' });
    procs.push(p);
    return waitHttp('http://127.0.0.1:18110/health');
}

function framesOnDisk() {
    const f = path.join(tmp, 'obs', `${SID}.frames.jsonl`);
    return fs.existsSync(f) ? fs.readFileSync(f, 'utf8').trim().split('\n').map((l) => JSON.parse(l)) : [];
}

async function turnOn(page) {
    await page.eval(`window.__triage.consultId = '${SID}'; window.CameraObserve.sessionReady(); true`);
    await page.eval(`document.getElementById('cam-toggle').click(); true`);
}

async function main() {
    if (!fs.existsSync(path.join(WEB, 'vendor', 'mediapipe', 'vision_bundle.js'))) {
        throw new Error('缺少 web/vendor/mediapipe/：先按实施计划 Task 1 放好 MediaPipe 网页版与模型');
    }
    await serveStatic(WEB, 18010);
    await startDoctor();
    const noVendor = path.join(tmp, 'web-no-vendor');
    fs.mkdirSync(noVendor);
    for (const f of fs.readdirSync(WEB)) {
        if (/\.(html|css|js)$/.test(f)) { fs.copyFileSync(path.join(WEB, f), path.join(noVendor, f)); }
    }
    await serveStatic(noVendor, 18011);

    const chrome = await launchChrome(FACE ? [`--use-file-for-fake-video-capture=${FACE}`] : []);
    try {
        // 1. 正常链路：开关 → 加载 → 打点 → 上传 → 写 frames.jsonl
        const page = await chrome.open('http://127.0.0.1:18010/triage.html?obs_port=18110');
        await page.waitFor('window.CameraObserve && document.readyState === "complete"');
        check(await page.eval(`document.getElementById('cam-toggle').disabled`), '会话开始前开关不可点');
        await turnOn(page);
        await page.waitFor('window.CameraObserve.debug().running', 60000);
        await sleep(7000);
        const dbg = await page.eval('window.CameraObserve.debug()');
        console.log('      ', JSON.stringify(dbg));
        check(dbg.stats.frames >= 15, `打点帧数 ${dbg.stats.frames} ≥ 15（约 5 fps）`);
        check(dbg.stats.ok >= 2 && dbg.stats.failed === 0, `上传成功 ${dbg.stats.ok} 批，失败 ${dbg.stats.failed} 批`);
        const rows = framesOnDisk();
        check(rows.length >= 10 && rows.every((r) => typeof r.t === 'number' && !('ct' in r)),
            `frames.jsonl ${rows.length} 行，都有服务器时间 t、没有浏览器时间 ct`);
        if (FACE) {
            check(rows.some((r) => r.f && r.f.m.length === 16 && Object.keys(r.f.bs).length === 26), '检出人脸：f 带 26 个 blendshape 和 16 个矩阵数');
            check(dbg.baseline, '开启 5 秒后本人基线就绪');
            const panel = await page.eval(`document.getElementById('cam-panel-body').textContent`);
            check(/左右转头/.test(panel), `实时面板：${panel}`);
        } else {
            check(rows.every((r) => r.f === null), '测试画面里没有人脸：f 都是 null');
        }
        const line = await page.eval(`(function () {
            var n = document.createElement('div'); n.className = 'msg msg-user';
            document.getElementById('chat-list').appendChild(n);
            window.CameraObserve.onAnswer(n); return n.textContent; })()`);
        check(/^本次回答观察：/.test(line), `回答观察行：${line}`);
        // 2. 会话中途摄像头断开（撤销授权 / 拔掉摄像头）：停止采集、提示一次，问诊不受影响
        await page.eval(`document.getElementById('cam-video').srcObject.getVideoTracks()[0].dispatchEvent(new Event('ended')); true`);
        await sleep(500);
        const afterEnd = await page.eval('window.CameraObserve.debug()');
        const toastText = await page.eval(`document.getElementById('toast').textContent`);
        check(!afterEnd.running && afterEnd.toggle === 'off', '摄像头断开后停止采集，开关回到「关」');
        check(/摄像头已断开/.test(toastText), `提示：${toastText}`);
        // 3. 问诊结束：释放摄像头，开关变灰
        await turnOn(page);
        await page.waitFor('window.CameraObserve.debug().running', 30000);
        await page.eval('window.CameraObserve.sessionEnded(); true');
        const ended = await page.eval(`({ d: window.CameraObserve.debug(), box: document.getElementById('cam-box').hidden,
            dis: document.getElementById('cam-toggle').disabled, src: document.getElementById('cam-video').srcObject })`);
        check(!ended.d.running && ended.box && ended.dis && ended.src === null, '问诊结束：小窗隐藏、摄像头释放、开关变灰');
        page.close();

        // 4. 8110 没转发：上传失败只丢弃、连续 5 批后提示一次，页面照常
        const down = await chrome.open('http://127.0.0.1:18010/triage.html?obs_port=18119');
        await down.waitFor('window.CameraObserve && document.readyState === "complete"');
        await turnOn(down);
        await down.waitFor('window.CameraObserve.debug().running', 60000);
        await down.waitFor(`/观察数据未能上传/.test(document.getElementById('toast').textContent)`, 25000);
        const dd = await down.eval('window.CameraObserve.debug()');
        check(dd.running && dd.stats.failed >= 5, `上传失败 ${dd.stats.failed} 批后提示一次，采集照常`);
        down.close();

        // 5. 拒绝授权：开关回到「关」，提示，问诊照常
        const deny = await chrome.open('http://127.0.0.1:18010/triage.html?obs_port=18110');
        await deny.waitFor('window.CameraObserve && document.readyState === "complete"');
        await deny.eval(`navigator.mediaDevices.getUserMedia = function () {
            return Promise.reject(new DOMException('denied', 'NotAllowedError')); }; true`);
        await turnOn(deny);
        await deny.waitFor(`/未获得摄像头权限/.test(document.getElementById('toast').textContent)`, 60000);
        check((await deny.eval('window.CameraObserve.debug()')).toggle === 'off', '拒绝授权后开关回到「关」');
        deny.close();

        // 6. vendor 缺失：开关变灰「摄像头观察不可用」
        const nov = await chrome.open('http://127.0.0.1:18011/triage.html?obs_port=18110');
        await nov.waitFor('window.CameraObserve && document.readyState === "complete"');
        await turnOn(nov);
        await nov.waitFor(`window.CameraObserve.debug().toggle === 'unavailable'`, 20000);
        check(await nov.eval(`document.getElementById('cam-toggle').disabled
            && document.getElementById('cam-toggle-label').textContent === '摄像头观察不可用'`), 'vendor 缺失：开关变灰');
        nov.close();

        // 7. ?demo=1：可以开小窗打点，但不上传；示例回答带观察行
        const before = framesOnDisk().length;
        const demo = await chrome.open('http://127.0.0.1:18010/triage.html?demo=1&obs_port=18110');
        await demo.waitFor('window.CameraObserve && document.readyState === "complete"');
        check(await demo.eval(`document.querySelectorAll('.msg-obs').length === 3`), '演示页有 3 条示例观察行');
        await demo.eval(`document.getElementById('cam-toggle').click(); true`);
        await demo.waitFor('window.CameraObserve.debug().running', 60000);
        await sleep(4500);
        const dm = await demo.eval('window.CameraObserve.debug()');
        check(dm.stats.frames > 5 && dm.stats.batches === 0 && framesOnDisk().length === before,
            `演示模式打点 ${dm.stats.frames} 帧、上传 ${dm.stats.batches} 批`);
        demo.close();
    } finally {
        await chrome.close();
        procs.forEach((p) => p.kill());
        await sleep(500);
        try { fs.rmSync(tmp, { recursive: true, force: true }); } catch (e) { /* Windows 上可能还被占着 */ }
    }
    console.log(failed ? `\n${failed} 项失败` : '\n全部通过');
    process.exit(failed ? 1 : 0);
}

main().catch((err) => {
    console.error(err);
    procs.forEach((p) => p.kill());
    process.exit(1);
});
````

- [ ] **Step 2: Run smoke to verify it fails**

Run: `node apps/multimodal/web/tests/smoke-camera.mjs`
Expected: FAIL —— `Error: 等待超时（20000ms）：window.CameraObserve && document.readyState === "complete"`（页面上还没有 `CameraObserve`）。如果先报「缺少 web/vendor/mediapipe/」，回到 Task 1 Step 5。

- [ ] **Step 3: Write `camera-observe.js`**

Create `apps/multimodal/web/camera-observe.js`：
````javascript
/* ─────────────────────────────────────────────────────────────────────────
 * camera-observe.js —— 患者页「摄像头观察」（可选，默认关闭）
 *
 * 画面只在本机浏览器里处理：MediaPipe Tasks Vision 网页版（/vendor/mediapipe/，部署时由
 * 15_setup_camera_assets.sh 放好，不进仓库）在本机打点，小窗叠加面部稀疏点和上身骨架。
 * 离开浏览器的只有关键点数值（26 个 blendshape 分数、4×4 头姿矩阵、25 个姿态点 x/y/可见度），
 * 每 2 秒一批 POST 到医生端服务 :8110/api/observe/<consultId>。不录像、不截图、不缓存画面。
 * 小窗下方的实时面板和每条回答下的观察行由 camera-metrics.js 近似计算，只作展示；
 * 医生端看到的数值由 Spark 上的 face_body/live.py 计算。
 *
 * triage.js 通过 window.CameraObserve 的几个钩子驱动它；本文件缺失或 vendor 加载失败时，问诊照常。
 * `?demo=1`：可以开小窗打点，但不上传。`?obs_port=<端口>`：上传端口（默认 8110，本机冒烟测试用）。
 * ───────────────────────────────────────────────────────────────────────── */
(function () {
    'use strict';

    var M = window.CameraMetrics;
    var CFG = {
        vendor: '/vendor/mediapipe',
        fps: 5,                 // 打点频率；低配电脑卡顿时可降到 3
        batchMs: 2000,          // 每 2 秒上传一批
        panelMs: 500,           // 实时面板刷新间隔
        maxBatch: 50,           // 与 doctor_service 的上限一致
        failNotice: 5,          // 连续这么多批上传失败，提示一次
        demo: /[?&]demo=1\b/.test(window.location.search),
        port: (function () {
            var m = window.location.search.match(/[?&]obs_port=(\d{2,5})\b/);
            return m ? m[1] : '8110';
        })()
    };
    var CONSENT = '开启摄像头观察？\n\n画面只在本机处理，只把面部/姿态关键点数值发给系统；' +
        '可随时关闭；不开也能正常问诊。';
    var INFO_TIP = '这些是摄像头观察到的动作数值，不代表情绪或健康状况';
    var LABEL = { off: '摄像头观察：关', on: '摄像头观察：开', loading: '正在开启摄像头…', unavailable: '摄像头观察不可用' };
    var FACE_POINTS = [];
    for (var fp = 0; fp < 468; fp += 7) { FACE_POINTS.push(fp); }   // 面部 478 点里取约 70 个稀疏点
    var POSE_LINKS = [[11, 12], [11, 13], [13, 15], [12, 14], [14, 16], [11, 23], [12, 24], [23, 24]];

    var el = {};
    var st = {
        opts: {}, ready: false, unavailable: false, consented: false, running: false, starting: false,
        stream: null, face: null, pose: null, raf: 0, lastProc: 0, lastTs: 0,
        camStart: 0, recs: [], base: null, seg: [], segStart: 0,
        batch: [], batchTimer: 0, panelTimer: 0, fails: 0, warned: false,
        stats: { frames: 0, faces: 0, poses: 0, batches: 0, ok: 0, failed: 0, dropped: 0 }
    };
    var visionPromise = null;

    function r4(x) { return Math.round(x * 1e4) / 1e4; }

    function toast(msg, kind, ms) {
        if (st.opts.toast) { st.opts.toast(msg, kind, ms); } else { console.warn('[camera] ' + msg); }
    }

    function setToggle(s) {
        if (!el.toggle) { return; }
        el.toggle.dataset.state = s;
        el.toggle.setAttribute('aria-pressed', s === 'on' ? 'true' : 'false');
        el.toggleLabel.textContent = LABEL[s] || LABEL.off;
        el.toggle.disabled = s === 'loading' || s === 'unavailable' || (s === 'off' && !st.ready);
    }

    function markUnavailable(err) {
        st.unavailable = true;
        st.starting = false;
        console.warn('[camera] 摄像头观察不可用：' + (err && err.message ? err.message : err));
        setToggle('unavailable');
        toast('摄像头观察不可用，不影响问诊', 'warn', 5000);
    }

    /* ── 加载 MediaPipe（只加载一次）────────────────────────────────── */

    function loadScript(src) {
        return new Promise(function (resolve, reject) {
            var s = document.createElement('script');
            s.src = src;
            s.onload = resolve;
            s.onerror = function () { reject(new Error('加载失败 ' + src)); };
            document.head.appendChild(s);
        });
    }

    function loadVision() {
        if (visionPromise) { return visionPromise; }
        // vision_bundle.js 是经典脚本（定义全局 Vision），不依赖服务器给 .mjs 的 MIME 类型
        visionPromise = (window.Vision ? Promise.resolve() : loadScript(CFG.vendor + '/vision_bundle.js'))
            .then(function () {
                var V = window.Vision;
                if (!V || !V.FilesetResolver) { throw new Error('vision_bundle.js 里没有 Vision'); }
                return V.FilesetResolver.forVisionTasks(CFG.vendor + '/wasm').then(function (fileset) {
                    return Promise.all([
                        V.FaceLandmarker.createFromOptions(fileset, {
                            baseOptions: { modelAssetPath: CFG.vendor + '/face_landmarker.task', delegate: 'CPU' },
                            runningMode: 'VIDEO', numFaces: 1,
                            outputFaceBlendshapes: true, outputFacialTransformationMatrixes: true
                        }),
                        V.PoseLandmarker.createFromOptions(fileset, {
                            baseOptions: { modelAssetPath: CFG.vendor + '/pose_landmarker_full.task', delegate: 'CPU' },
                            runningMode: 'VIDEO', numPoses: 1
                        })
                    ]);
                });
            })
            .then(function (pair) { st.face = pair[0]; st.pose = pair[1]; });
        return visionPromise;
    }

    /* ── 开关 ─────────────────────────────────────────────────────────── */

    function cameraError(err) {
        var name = err && err.name;
        if (name === 'NotAllowedError' || name === 'SecurityError') { return '未获得摄像头权限，问诊照常进行'; }
        if (name === 'NotFoundError' || name === 'OverconstrainedError') { return '没有找到可用的摄像头，问诊照常进行'; }
        if (name === 'NotReadableError') { return '摄像头被其他程序占用，问诊照常进行'; }
        return '摄像头无法开启（' + (name || '未知原因') + '），问诊照常进行';
    }

    function enable() {
        if (st.running || st.starting || st.unavailable) { return; }
        if (!st.consented) {
            if (!window.confirm(CONSENT)) { return; }
            st.consented = true;
        }
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            toast('当前页面不能使用摄像头（请用 127.0.0.1 或 https 地址打开），问诊照常进行', 'warn', 6000);
            return;
        }
        st.starting = true;
        setToggle('loading');
        loadVision().then(function () {
            return navigator.mediaDevices.getUserMedia({
                video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }, audio: false
            }).then(startWith, function (err) {
                st.starting = false;
                setToggle('off');
                toast(cameraError(err), 'warn', 6000);
            });
        }, markUnavailable);
    }

    function stopStream(stream) {
        if (!stream) { return; }
        stream.getTracks().forEach(function (t) { try { t.stop(); } catch (e) { /* 忽略 */ } });
    }

    function startWith(stream) {
        st.starting = false;
        if (!st.ready) { stopStream(stream); setToggle('off'); return; }   // 加载期间问诊已结束
        st.stream = stream;
        st.running = true;
        el.video.srcObject = stream;
        var played = el.video.play();
        if (played && played.catch) { played.catch(function () { /* 静音视频，自动播放失败也不影响打点 */ }); }
        var track = stream.getVideoTracks()[0];
        if (track) {
            track.addEventListener('ended', function () {   // 拔掉摄像头、系统里撤销了授权
                if (st.stream !== stream) { return; }
                stop();
                toast('摄像头已断开，观察已停止；问诊照常进行', 'warn', 6000);
            });
        }
        st.camStart = Date.now();
        st.recs = [];
        st.base = null;
        st.seg = [];
        st.segStart = st.camStart;
        st.fails = 0;
        st.warned = false;
        el.box.hidden = false;
        setToggle('on');
        st.raf = window.requestAnimationFrame(loop);
        st.batchTimer = window.setInterval(flush, CFG.batchMs);
        st.panelTimer = window.setInterval(renderPanel, CFG.panelMs);
        renderPanel();
    }

    function stop() {
        var wasRunning = st.running;
        st.running = false;
        window.cancelAnimationFrame(st.raf);
        window.clearInterval(st.batchTimer);
        window.clearInterval(st.panelTimer);
        if (wasRunning) { flush(); }   // 最后一批也送出去（keepalive，页面关闭时也能送达）
        stopStream(st.stream);
        st.stream = null;
        if (el.video) { el.video.srcObject = null; }
        if (el.canvas) { el.canvas.getContext('2d').clearRect(0, 0, el.canvas.width, el.canvas.height); }
        if (el.box) { el.box.hidden = true; }
        setToggle(st.unavailable ? 'unavailable' : 'off');
    }

    /* ── 逐帧 ─────────────────────────────────────────────────────────── */

    function loop(now) {
        if (!st.running) { return; }
        st.raf = window.requestAnimationFrame(loop);
        if (now - st.lastProc < 1000 / CFG.fps - 5 || el.video.readyState < 2) { return; }
        st.lastProc = now;
        try { processFrame(); } catch (e) { console.warn('[camera] 打点出错：' + (e && e.message)); }
    }

    function faceOf(res) {
        if (!res || !res.faceLandmarks || !res.faceLandmarks.length) { return null; }
        var cats = res.faceBlendshapes && res.faceBlendshapes[0] && res.faceBlendshapes[0].categories;
        var mat = res.facialTransformationMatrixes && res.facialTransformationMatrixes[0];
        if (!cats || !mat || !mat.data || mat.data.length !== 16) { return null; }
        var byName = {};
        cats.forEach(function (c) { byName[c.categoryName] = c.score; });
        var bs = {};
        for (var i = 0; i < M.CAM_BLENDSHAPES.length; i += 1) {
            var v = byName[M.CAM_BLENDSHAPES[i]];
            if (typeof v !== 'number' || !isFinite(v)) { return null; }
            bs[M.CAM_BLENDSHAPES[i]] = r4(v);
        }
        var m = Array.prototype.map.call(mat.data, r4);   // 原样发送（列主序），由 Spark 上的 live.py 统一换算
        return m.every(isFinite) ? { bs: bs, m: m } : null;
    }

    function poseOf(res) {
        var lm = res && res.landmarks && res.landmarks[0];
        if (!lm || lm.length < 25) { return null; }
        var out = [];
        for (var i = 0; i < 25; i += 1) {
            var x = Number(lm[i].x), y = Number(lm[i].y);
            var v = lm[i].visibility === undefined ? 0 : Number(lm[i].visibility);
            if (!isFinite(x) || !isFinite(y) || !isFinite(v)) { return null; }
            out.push([r4(x), r4(y), r4(v)]);
        }
        return out;
    }

    function processFrame() {
        var ts = Math.max(st.lastTs + 1, Math.round(performance.now()));   // VIDEO 模式要求时间戳严格递增
        st.lastTs = ts;
        var fr = st.face.detectForVideo(el.video, ts);
        var pr = st.pose.detectForVideo(el.video, ts);
        var frame = { ct: Date.now(), f: faceOf(fr), p: poseOf(pr) };
        draw(fr, pr);
        st.stats.frames += 1;
        if (frame.f) { st.stats.faces += 1; }
        if (frame.p) { st.stats.poses += 1; }
        if (!CFG.demo) { st.batch.push(frame); }
        var rec = M.frameRecord(frame, (frame.ct - st.camStart) / 1000);
        st.recs.push(rec);
        if (st.recs.length > 600) { st.recs.shift(); }
        st.seg.push(rec);
        while (st.seg.length && rec.t - st.seg[0].t > M.CONST.MAX_SEGMENT_S) { st.seg.shift(); }
        if (!st.base && rec.t >= M.CONST.BASELINE_S) { st.base = M.baseline(st.recs, M.CONST.BASELINE_S); }
    }

    function draw(fr, pr) {
        var c = el.canvas, g = c.getContext('2d');
        g.clearRect(0, 0, c.width, c.height);
        var face = fr && fr.faceLandmarks && fr.faceLandmarks[0];
        if (face) {
            g.fillStyle = '#59e0e8';
            FACE_POINTS.forEach(function (i) {
                var q = face[i];
                if (q) { g.fillRect(q.x * c.width - 1, q.y * c.height - 1, 2, 2); }
            });
        }
        var pose = pr && pr.landmarks && pr.landmarks[0];
        if (pose) {
            g.strokeStyle = '#ffd166';
            g.lineWidth = 2;
            POSE_LINKS.forEach(function (link) {
                var a = pose[link[0]], b = pose[link[1]];
                if (a && b && a.visibility > 0.5 && b.visibility > 0.5) {
                    g.beginPath();
                    g.moveTo(a.x * c.width, a.y * c.height);
                    g.lineTo(b.x * c.width, b.y * c.height);
                    g.stroke();
                }
            });
        }
    }

    /* ── 上传 ─────────────────────────────────────────────────────────── */

    function uploadUrl(id) {
        return window.location.protocol + '//' + window.location.hostname + ':' + CFG.port +
            '/api/observe/' + encodeURIComponent(id);
    }

    function flush() {
        if (!st.batch.length) { return; }
        var id = st.opts.getConsultId ? st.opts.getConsultId() : '';
        if (CFG.demo || !id) {   // 演示模式、或还没有会话编号：不上传
            st.stats.dropped += st.batch.length;
            st.batch = [];
            return;
        }
        while (st.batch.length) { send(id, st.batch.splice(0, CFG.maxBatch)); }
    }

    function send(id, frames) {
        var body = JSON.stringify({ v: 'cam-0.1', sent_ct: Date.now(), frames: frames });
        st.stats.batches += 1;
        fetch(uploadUrl(id), {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body, keepalive: body.length < 60000
        }).then(function (r) {
            if (!r.ok) { throw new Error('HTTP ' + r.status); }
            st.stats.ok += 1;
            st.fails = 0;
        }).catch(function (err) {   // 失败的这一批直接丢弃，不重试、不阻塞问诊
            st.stats.failed += 1;
            st.fails += 1;
            console.warn('[camera] 观察数据上传失败，已丢弃这一批：' + (err && err.message));
            if (st.fails >= CFG.failNotice && !st.warned) {
                st.warned = true;
                toast('观察数据未能上传（不影响问诊）', 'warn', 6000);
            }
        });
    }

    /* ── 患者端实时显示 ──────────────────────────────────────────────── */

    function currentSegment() {
        var now = Date.now();
        var start = Math.max(st.segStart, st.camStart, now - M.CONST.MAX_SEGMENT_S * 1000);
        var from = (start - st.camStart) / 1000;
        var recs = st.seg.filter(function (r) { return r.t >= from; });
        return M.summarize(recs, st.base, { window: (now - start) / 1000 });
    }

    function renderPanel() {
        if (!st.running || !el.panelBody) { return; }
        var recent = st.recs.slice(-5).filter(function (r) { return r.face; });
        var yaw = null, pitch = null;
        if (st.base && recent.length) {
            yaw = recent.reduce(function (s, r) { return s + r.yaw; }, 0) / recent.length - st.base.yaw;
            pitch = recent.reduce(function (s, r) { return s + r.pitch; }, 0) / recent.length - st.base.pitch;
        }
        var last = st.recs[st.recs.length - 1];
        el.panelBody.textContent = M.formatLivePanel({
            baselineReady: !!st.base, yaw: yaw, pitch: pitch, segment: currentSegment(),
            handFace: last && last.pose ? !!last.hand_face : null
        });
    }

    function appendLine(node, text) {
        if (!node) { return; }
        var line = document.createElement('div');
        line.className = 'msg-obs';
        line.appendChild(document.createTextNode(text + ' '));
        var info = document.createElement('span');
        info.className = 'obs-info';
        info.textContent = 'ⓘ';
        info.title = INFO_TIP;
        line.appendChild(info);
        node.appendChild(line);
    }

    /** 患者这句话进入对话流：统计「上一次助手回复结束 → 现在」这一段，挂在气泡下方，然后清零。 */
    function onAnswer(node) {
        if (st.running) { appendLine(node, M.formatAnswerLine(currentSegment())); }
        st.seg = [];
        st.segStart = Date.now();
    }

    /** 助手这一轮回复生成完（llm_done）：下一段从这里开始。 */
    function markReplyEnd() {
        st.seg = [];
        st.segStart = Date.now();
    }

    function sessionReady() {
        st.ready = true;
        if (!st.unavailable) { setToggle(st.running ? 'on' : 'off'); }
    }

    function sessionEnded() {
        st.ready = CFG.demo;
        stop();
    }

    function init(opts) {
        st.opts = opts || {};
        el.toggle = document.getElementById('cam-toggle');
        el.toggleLabel = document.getElementById('cam-toggle-label');
        el.box = document.getElementById('cam-box');
        el.video = document.getElementById('cam-video');
        el.canvas = document.getElementById('cam-canvas');
        el.panelBody = document.getElementById('cam-panel-body');
        el.fold = document.getElementById('cam-fold');
        if (!el.toggle || !el.toggleLabel || !el.box || !el.video || !el.canvas) { return; }
        el.toggle.addEventListener('click', function () { if (st.running) { stop(); } else { enable(); } });
        if (el.fold && el.panelBody) {
            el.fold.addEventListener('click', function () {
                el.panelBody.hidden = !el.panelBody.hidden;
                el.fold.textContent = el.panelBody.hidden ? '展开' : '收起';
            });
        }
        st.ready = CFG.demo;
        if (!M) { markUnavailable(new Error('camera-metrics.js 没有加载')); return; }
        setToggle('off');
    }

    window.CameraObserve = {
        init: init,
        sessionReady: sessionReady,
        sessionEnded: sessionEnded,
        markReplyEnd: markReplyEnd,
        onAnswer: onAnswer,
        appendLine: appendLine,
        stop: stop,
        // 排障与冒烟测试用（只读）
        debug: function () {
            return {
                running: st.running, ready: st.ready, unavailable: st.unavailable, baseline: !!st.base,
                toggle: el.toggle ? el.toggle.dataset.state : '', stats: JSON.parse(JSON.stringify(st.stats))
            };
        }
    };
})();
````

- [ ] **Step 4: `triage.html`：小窗、开关、脚本**

第 1 处 · `apps/multimodal/web/triage.html`

查找：

````html
                <div class="toast" id="toast" hidden></div>
````

替换为：

````html
                <div class="toast" id="toast" hidden></div>

                <!-- 摄像头观察小窗：画面只在本机处理，只上传关键点数值（camera-observe.js） -->
                <div class="cam-box" id="cam-box" hidden>
                    <div class="cam-badge">摄像头观察中 · 画面只在本机处理</div>
                    <div class="cam-view">
                        <video id="cam-video" autoplay playsinline muted></video>
                        <canvas id="cam-canvas" width="320" height="240"></canvas>
                    </div>
                    <div class="cam-panel">
                        <div class="cam-panel-head">
                            <span>实时观察（近似）</span>
                            <span class="obs-info" title="这些是摄像头观察到的动作数值，不代表情绪或健康状况">ⓘ</span>
                            <button type="button" class="cam-fold" id="cam-fold">收起</button>
                        </div>
                        <div class="cam-panel-body" id="cam-panel-body">正在建立本人基线…</div>
                    </div>
                </div>
````

第 2 处 · `apps/multimodal/web/triage.html`

查找：

````html
                    <div class="level-num" id="level-num">电平 —</div>
                </div>
            </div>
````

替换为：

````html
                    <div class="level-num" id="level-num">电平 —</div>
                </div>

                <button type="button" class="cam-toggle" id="cam-toggle" data-state="off" aria-pressed="false" disabled
                        title="可选：画面只在本机处理，只把面部/姿态关键点数值发给系统；不开也能正常问诊">
                    <i class="cam-dot" aria-hidden="true"></i><span id="cam-toggle-label">摄像头观察：关</span>
                </button>
            </div>
````

第 3 处 · `apps/multimodal/web/triage.html`

查找：

````html
<script src="mic-asr.js" charset="UTF-8"></script>
<script src="triage.js" charset="UTF-8"></script>
````

替换为：

````html
<script src="mic-asr.js" charset="UTF-8"></script>
<script src="camera-metrics.js" charset="UTF-8"></script>
<script src="camera-observe.js" charset="UTF-8"></script>
<script src="triage.js" charset="UTF-8"></script>
````

- [ ] **Step 5: `triage.css`：开关、小窗、面板、观察行**

第 1 处 · `apps/multimodal/web/triage.css`

查找：

````css
/* ── 响应式 ───────────────────────────────────────────────────────────── */
````

替换为：

````css
/* ── 摄像头观察（camera-observe.js）────────────────────────────────────── */

.cam-toggle {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 7px 12px;
    border-radius: 999px;
    border: 1px solid var(--line);
    background: var(--bg-soft);
    color: var(--ink-2);
    font-size: 12.5px;
    white-space: nowrap;
}

.cam-toggle .cam-dot { width: 8px; height: 8px; border-radius: 50%; background: #b8c7cb; }
.cam-toggle[data-state="on"] { background: var(--brand-soft); color: var(--brand-ink); border-color: #bfe2e6; }
.cam-toggle[data-state="on"] .cam-dot { background: #e5484d; animation: pulse 1.4s ease-in-out infinite; }
.cam-toggle[data-state="loading"] .cam-dot { background: #e0b354; }

.cam-box {
    position: absolute;
    right: 12px;
    bottom: 12px;
    z-index: 5;
    width: 220px;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 6px;
}

.cam-box[hidden] { display: none; }

.cam-badge {
    padding: 3px 9px;
    border-radius: 999px;
    font-size: 11.5px;
    color: #fff;
    background: rgba(160, 45, 33, 0.82);
}

.cam-view {
    position: relative;
    width: 160px;
    height: 120px;
    border-radius: 10px;
    overflow: hidden;
    background: #0a1e23;
    border: 1px solid rgba(255, 255, 255, 0.22);
    transform: scaleX(-1);   /* 镜像显示；打点画在同一个镜像容器里，位置对得上 */
}

.cam-view video, .cam-view canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
}

.cam-panel {
    width: 100%;
    padding: 7px 10px;
    border-radius: 10px;
    font-size: 12px;
    line-height: 1.5;
    color: #e8f6f7;
    background: rgba(10, 30, 35, 0.72);
    backdrop-filter: blur(6px);
}

.cam-panel-head { display: flex; align-items: center; gap: 6px; color: #9fc3c9; }
.cam-fold { margin-left: auto; padding: 0 4px; border: none; background: none; color: #9fc3c9; font-size: 11.5px; }
.cam-panel-body { margin-top: 2px; font-variant-numeric: tabular-nums; }

.msg-obs {
    max-width: 92%;
    margin-top: 4px;
    font-size: 11.5px;
    color: var(--ink-3);
    font-variant-numeric: tabular-nums;
}

.obs-info { cursor: help; opacity: 0.8; }

/* ── 响应式 ───────────────────────────────────────────────────────────── */
````

第 2 处 · `apps/multimodal/web/triage.css`

查找：

````css
    .mic-info { flex-basis: 100%; order: 3; }
}
````

替换为：

````css
    .mic-info { flex-basis: 100%; order: 3; }
    .cam-box { width: 180px; }
}
````

- [ ] **Step 6: `triage.js`：生命周期钩子与演示观察行**

依次做下面 10 处替换：
第 1 处 · `apps/multimodal/web/triage.js`

查找：

````javascript
        wrap.querySelector('.msg-bubble').textContent = text;
        el.chatList.appendChild(wrap);
        scrollChat();
    }
````

替换为：

````javascript
        wrap.querySelector('.msg-bubble').textContent = text;
        el.chatList.appendChild(wrap);
        scrollChat();
        return wrap;
    }
````

第 2 处 · `apps/multimodal/web/triage.js`

查找：

````javascript
    function onLLMDone() {
        replySettled();
````

替换为：

````javascript
    function onLLMDone() {
        // 摄像头观察：助手这一轮回复结束，下一段「本次回答观察」从这里算起
        if (window.CameraObserve) { window.CameraObserve.markReplyEnd(); }
        replySettled();
````

第 3 处 · `apps/multimodal/web/triage.js`

查找：

````javascript
        addUserMessage(text, source);
        state.turn += 1;
````

替换为：

````javascript
        var node = addUserMessage(text, source);
        // 摄像头观察：这句话下面追加「本次回答观察」（没开摄像头时什么都不加）
        if (window.CameraObserve) { window.CameraObserve.onAnswer(node); }
        state.turn += 1;
````

第 4 处 · `apps/multimodal/web/triage.js`

查找：

````javascript
    function hideAvatarToStart() {
        state.ended = true;   // 收尾阶段链路断了也不要自动重连，否则数字人会自己回来
````

替换为：

````javascript
    function hideAvatarToStart() {
        if (window.CameraObserve) { window.CameraObserve.sessionEnded(); }   // 停止采集、释放摄像头，送出最后一批
        state.ended = true;   // 收尾阶段链路断了也不要自动重连，否则数字人会自己回来
````

第 5 处 · `apps/multimodal/web/triage.js`

查找：

````javascript
    function closeAvatar() {
        stopListening(false);
````

替换为：

````javascript
    function closeAvatar() {
        if (window.CameraObserve) { window.CameraObserve.sessionEnded(); }   // 必须在清空 consultId 之前
        stopListening(false);
````

第 6 处 · `apps/multimodal/web/triage.js`

查找：

````javascript
        if (el.sendBtn) { el.sendBtn.disabled = false; }
        state.userPaused = false;
        state.ended = false;      // 恢复自动重连能力
````

替换为：

````javascript
        if (el.sendBtn) { el.sendBtn.disabled = false; }
        if (window.CameraObserve) { window.CameraObserve.sessionReady(); }   // 继续问诊：可以重新开启摄像头观察
        state.userPaused = false;
        state.ended = false;      // 恢复自动重连能力
````

第 7 处 · `apps/multimodal/web/triage.js`

查找：

````javascript
        el.finishBtn.disabled = false;

    }
````

替换为：

````javascript
        el.finishBtn.disabled = false;
        // 会话已连上：允许开启摄像头观察（断线重连沿用同一个 consultId，观察数据接着写同一个文件）
        if (window.CameraObserve) { window.CameraObserve.sessionReady(); }
    }
````

第 8 处 · `apps/multimodal/web/triage.js`

查找：

````javascript
        window.addEventListener('beforeunload', function () {
            if (state.pc) { try { state.pc.close(); } catch (e) { /* 忽略 */ } }
````

替换为：

````javascript
        window.addEventListener('beforeunload', function () {
            if (window.CameraObserve) { window.CameraObserve.stop(); }
            if (state.pc) { try { state.pc.close(); } catch (e) { /* 忽略 */ } }
````

第 9 处 · `apps/multimodal/web/triage.js`

查找：

````javascript
        addUserMessage('这两天胃有点胀，吃完饭更明显', 'voice');
        addAssistantMessage('明白了。请问这种胀的感觉持续多久了？');
        addUserMessage('大概三四天', 'voice');
        addAssistantMessage('好的。除了胀，还有没有反酸、烧心，或者恶心的感觉？');
        addUserMessage('偶尔有点反酸，没有恶心', 'text');
````

替换为：

````javascript
        var u1 = addUserMessage('这两天胃有点胀，吃完饭更明显', 'voice');
        addAssistantMessage('明白了。请问这种胀的感觉持续多久了？');
        var u2 = addUserMessage('大概三四天', 'voice');
        addAssistantMessage('好的。除了胀，还有没有反酸、烧心，或者恶心的感觉？');
        var u3 = addUserMessage('偶尔有点反酸，没有恶心', 'text');
        if (window.CameraObserve) {   // 示例观察行（演示模式不上传任何数据）
            window.CameraObserve.appendLine(u1, '本次回答观察：目光偏离 12% · 眨眼 16 次/分 · 手触脸 0% · 小动作 0.5');
            window.CameraObserve.appendLine(u2, '本次回答观察：目光偏离 35% · 眨眼 24 次/分 · 手触脸 10% · 小动作 1.2');
            window.CameraObserve.appendLine(u3, '本次回答观察：观察数据不足');
        }
````

第 10 处 · `apps/multimodal/web/triage.js`

查找：

````javascript
        setPhase('idle', '点击「开始问诊」后自动开启语音交互');
        setMeta('等待开始');

        if (CFG.demo) { renderDemo(); }
````

替换为：

````javascript
        setPhase('idle', '点击「开始问诊」后自动开启语音交互');
        setMeta('等待开始');
        if (window.CameraObserve) {
            window.CameraObserve.init({ getConsultId: function () { return state.consultId; }, toast: showToast });
        }

        if (CFG.demo) { renderDemo(); }
````

- [ ] **Step 7: 语法检查**

Run: `node --check apps/multimodal/web/camera-observe.js && node --check apps/multimodal/web/triage.js && echo ok`
Expected: `ok`

- [ ] **Step 8: 生成人脸假视频并跑冒烟（有人脸 / 无人脸各一次）**

Run（Git Bash，仓库根目录）：
```bash
Y4M_DIR="$(mktemp -d)"
python apps/multimodal/web/tests/make_face_y4m.py --out "$Y4M_DIR/face.y4m"
node apps/multimodal/web/tests/smoke-camera.mjs --face "$Y4M_DIR/face.y4m"
node apps/multimodal/web/tests/smoke-camera.mjs
```
Expected（有人脸那次；`make_face_y4m.py` 先打印 `写出 …face.y4m（50 帧，640x480，10 fps）`，它会下载 MediaPipe 官方测试图到同一临时目录，下载不了时加 `--image <任意一张非真实患者的人脸图>`）：
```text
PASS  会话开始前开关不可点
       {"running":true,…,"baseline":true,"toggle":"on","stats":{"frames":3x,"faces":3x,"poses":3x,"batches":3,"ok":3,"failed":0,"dropped":0}}
PASS  打点帧数 3x ≥ 15（约 5 fps）
PASS  上传成功 3 批，失败 0 批
PASS  frames.jsonl 30 行，都有服务器时间 t、没有浏览器时间 ct
PASS  检出人脸：f 带 26 个 blendshape 和 16 个矩阵数
PASS  开启 5 秒后本人基线就绪
PASS  实时面板：左右转头 0° · 俯仰 0° · 本次回答 眨眼 0 次 · 目光偏离 0% · 手触脸 否
PASS  回答观察行：本次回答观察：目光偏离 0% · 眨眼 0 次/分 · 手触脸 0% · 小动作 9.6 ⓘ
PASS  摄像头断开后停止采集，开关回到「关」
PASS  提示：摄像头已断开，观察已停止；问诊照常进行
PASS  问诊结束：小窗隐藏、摄像头释放、开关变灰
PASS  上传失败 5 批后提示一次，采集照常
PASS  拒绝授权后开关回到「关」
PASS  vendor 缺失：开关变灰
PASS  演示页有 3 条示例观察行
PASS  演示模式打点 2x 帧、上传 0 批

全部通过
```
（具体帧数、面板里的角度和小动作数值每次略有不同，PASS 就行。）无人脸那次把「检出人脸」「基线」「面板」三行换成 `PASS  测试画面里没有人脸：f 都是 null`，回答观察行为 `本次回答观察：观察数据不足 ⓘ`，末尾同样 `全部通过`。

- [ ] **Step 9: Commit**

```bash
git add apps/multimodal/web/camera-observe.js apps/multimodal/web/triage.html apps/multimodal/web/triage.css apps/multimodal/web/triage.js apps/multimodal/web/tests/make_face_y4m.py apps/multimodal/web/tests/smoke-camera.mjs
git commit -m "feat(web): 患者页摄像头观察：本机打点、小窗、实时面板与逐句观察行 (#8)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: 医生工作台：「对话记录」逐条与「重点」命中的同期观察

**Files:**
- Modify: `apps/multimodal/web/doctor.js`（文件头 `:1-8`、`buildDemo` 的 `highlights` `:208-226`、「重点」一节之前 `:354`、`hitHTML` `:356-367`、`renderHighlights` `:397`、`markHits` 末尾 `:416-418`、`loadHighlights` 签名 `:424`）
- Modify: `apps/multimodal/web/doctor.css:455`
- Create: `apps/multimodal/web/tests/smoke-doctor.mjs`

**Interfaces:**
- Consumes：Task 4 的 `/highlights` 字段 `camera`、`observe_ready`、`observe_segments`、`observe_medians`、`hits[i].observe`；`tkey(t)`、`state.highlights`、`markHits()`（已有）。
- Produces：`obsLine(seg, medians) -> string`（两通道都 unknown → `同期观察：检出不足（unknown）`；否则 `同期观察（相对本人基线）：目光偏离 30% · 眨眼 18 次/分 · 手触脸 10% · 小动作 0.8`，超过会话中位数 1.5 倍的项加 ` ↑`）；`hitObsText(hit, h)`（旧服务没有 `camera` 字段时不显示；`camera === false` → `未开启摄像头`；未就绪 → `同期观察：暂不可用（问诊结束后自动生成）`）；`markObserve()`（`#chat li.msg-user` 下追加 `span.msg-obs`；没开摄像头 / 未就绪时只在 `#chat` 最前面插一条 `li.chat-obs-note`，不逐条重复）；`hitHTML(x, h)` 多一行 `.hl-obs`；演示数据覆盖正常、↑、unknown、未开启、未就绪五种情况。

- [ ] **Step 1: Write the failing smoke**

Create `apps/multimodal/web/tests/smoke-doctor.mjs`：
````javascript
// 医生工作台「同期观察」的离线演示冒烟（?demo=1，不连后端）：
//   node apps/multimodal/web/tests/smoke-doctor.mjs
// 核对：对话记录每条患者回答下有观察行（含 ↑ 与 unknown）；「重点」每条命中有观察行；
// 没开摄像头的会话只在最前面说一次「本场未开启摄像头」；观察还没生成时说明一次。
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { launchChrome, sleep } from './headless.mjs';

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PY = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
let failed = 0;
function check(ok, msg) { console.log(`${ok ? 'PASS' : 'FAIL'}  ${msg}`); if (!ok) { failed += 1; } }

const srv = spawn(PY, ['-m', 'http.server', '18012', '--bind', '127.0.0.1', '--directory', WEB], { stdio: 'ignore' });
const chrome = await launchChrome();
try {
    await sleep(1500);
    const base = 'http://127.0.0.1:18012/doctor.html?demo=1';
    const ended = await chrome.open(`${base}#7507329b-74ea-4e43-b8f3-cbaeef71e0c0`);
    await ended.waitFor(`document.querySelectorAll('#chat .msg-obs').length === 3`, 15000);
    const lines = await ended.eval(`Array.from(document.querySelectorAll('#chat .msg-obs')).map(function (n) { return n.textContent; })`);
    lines.forEach((l) => console.log('      ', l));
    check(/^同期观察（相对本人基线）：目光偏离 12%/.test(lines[0]), '第一条回答：正常观察行');
    check(/↑/.test(lines[1]), '第二条回答：超过会话中位数 1.5 倍的项标 ↑');
    check(lines[2] === '同期观察：检出不足（unknown）', '第三条回答：检出不足显示 unknown');
    check(await ended.eval(`document.querySelectorAll('#chat .chat-obs-note').length === 0`), '开了摄像头的会话没有「未开启」说明');
    await ended.eval(`document.querySelector('.tab[data-tab="highlights"]').click(); true`);
    await ended.waitFor(`document.querySelectorAll('#hl-list .hl-obs').length === 2`, 10000);
    const hl = await ended.eval(`Array.from(document.querySelectorAll('#hl-list .hl-obs')).map(function (n) { return n.textContent; })`);
    hl.forEach((l) => console.log('      ', l));
    check(/^同期观察（相对本人基线）/.test(hl[0]) && /unknown/.test(hl[1]), '「重点」每条命中带同期观察');
    await sleep(5500);   // 过一轮 5 秒轮询：重画后观察行不重复、不丢
    check(await ended.eval(`document.querySelectorAll('#chat .msg-obs').length === 3`), '轮询重画后仍是 3 行');
    ended.close();

    const nocam = await chrome.open(`${base}#c07a5e10-6d2d-4f6a-8d43-5a0e9c3f21b7`);
    await nocam.waitFor(`document.querySelectorAll('#chat li.msg').length > 0`, 15000);
    await nocam.waitFor(`document.querySelectorAll('#chat .chat-obs-note').length === 1`, 10000);
    check(await nocam.eval(`document.querySelector('#chat .chat-obs-note').textContent === '本场未开启摄像头'
        && document.querySelectorAll('#chat .msg-obs').length === 0`), '没开摄像头：只在最前面说一次，不逐条重复');
    nocam.close();

    const live = await chrome.open(`${base}#8f21c4de-1c3b-4c2f-9a71-0f2b6e4b91aa`);
    await live.waitFor(`document.querySelectorAll('#chat .chat-obs-note').length === 1`, 15000);
    check(/暂不可用/.test(await live.eval(`document.querySelector('#chat .chat-obs-note').textContent`)),
        '开了摄像头但观察还没生成：说明一次');
    live.close();
} finally {
    await chrome.close();
    srv.kill();
}
console.log(failed ? `\n${failed} 项失败` : '\n全部通过');
process.exit(failed ? 1 : 0);
````

- [ ] **Step 2: Run smoke to verify it fails**

Run: `node apps/multimodal/web/tests/smoke-doctor.mjs`
Expected: FAIL —— `Error: 等待超时（15000ms）：document.querySelectorAll('#chat .msg-obs').length === 3`。

- [ ] **Step 3: Implement `doctor.js`**

依次做下面 7 处替换：
第 1 处 · `apps/multimodal/web/doctor.js`

查找：

````javascript
 * 点一条跳回对话原句；`?tab=highlights` 打开页面时直接停在这个页签。
 */
````

替换为：

````javascript
 * 点一条跳回对话原句；`?tab=highlights` 打开页面时直接停在这个页签。
 * 患者开了摄像头观察时，同一个接口还带 observe_segments：「对话记录」每条患者回答、「重点」每条命中
 * 下方加一行「同期观察（相对本人基线）」；只有动作数值，不出情绪标签，数据不足显示 unknown。
 */
````

第 2 处 · `apps/multimodal/web/doctor.js`

查找：

````javascript
                    labels: { contains_key_info: '含医生需看的信息', risk_clue: '未见风险措辞', urgency: '紧急程度 3/9' },
                    evidence: '都没有', source: 'local:qwen3.6-35b-a3b'
                }
            ]
        };
````

替换为：

````javascript
                    labels: { contains_key_info: '含医生需看的信息', risk_clue: '未见风险措辞', urgency: '紧急程度 3/9' },
                    evidence: '都没有', source: 'local:qwen3.6-35b-a3b'
                }
            ]
        };
        // 摄像头同期观察的示例：一段正常、一段偏高（↑）、一段检出不足
        var segB = [
            { t: now - 1800, frames: 52, face_status: 'ok', body_status: 'ok', gaze_away_ratio: 0.12,
                blink_per_min: 16, hand_face_ratio: 0, body_motion_x1000: 0.5 },
            { t: now - 1700, frames: 48, face_status: 'ok', body_status: 'ok', gaze_away_ratio: 0.35,
                blink_per_min: 26, hand_face_ratio: 0.1, body_motion_x1000: 1.2 },
            { t: now - 1600, frames: 4, face_status: 'unknown', body_status: 'unknown', gaze_away_ratio: null,
                blink_per_min: null, hand_face_ratio: null, body_motion_x1000: null }
        ];
        highlights[items[1].id].camera = true;
        highlights[items[1].id].observe_ready = true;
        highlights[items[1].id].observe_segments = segB;
        highlights[items[1].id].observe_medians = { gaze_away_ratio: 0.2, blink_per_min: 16, hand_face_ratio: 0,
            body_motion_x1000: 0.6 };
        highlights[items[1].id].hits[0].observe = segB[0];
        highlights[items[1].id].hits[1].observe = segB[2];
        highlights[items[0].id] = { ready: false, hits: [], camera: true, observe_ready: false, observe_segments: [] };
        highlights[items[2].id] = { ready: false, hits: [], camera: false, observe_ready: false, observe_segments: [] };
````

第 3 处 · `apps/multimodal/web/doctor.js`

查找：

````javascript
    /* ── 重点（阶段三 judge）──────────────────────────────────────────── */

    function hitHTML(x) {
````

替换为：

````javascript
    /* ── 摄像头同期观察（阶段三 face_body/live.py）─────────────────────── */

    function pctText(v) { return v === null || v === undefined ? '—' : Math.round(v * 100) + '%'; }

    /** 超过会话中位数 1.5 倍标 ↑（中位数为 0 时只要有就标）。 */
    function upMark(v, m) {
        return v !== null && v !== undefined && m !== null && m !== undefined && v > 0 && v > 1.5 * m ? ' ↑' : '';
    }

    /** 一段同期观察 → 一行文字；两个通道都检出不足时只写 unknown。 */
    function obsLine(seg, medians) {
        if (!seg) { return ''; }
        if (seg.face_status !== 'ok' && seg.body_status !== 'ok') { return '同期观察：检出不足（unknown）'; }
        var md = medians || {};
        return '同期观察（相对本人基线）：目光偏离 ' + pctText(seg.gaze_away_ratio) + upMark(seg.gaze_away_ratio, md.gaze_away_ratio) +
            ' · 眨眼 ' + (seg.blink_per_min === null || seg.blink_per_min === undefined ? '—'
                : Math.round(seg.blink_per_min) + ' 次/分') + upMark(seg.blink_per_min, md.blink_per_min) +
            ' · 手触脸 ' + pctText(seg.hand_face_ratio) + upMark(seg.hand_face_ratio, md.hand_face_ratio) +
            ' · 小动作 ' + (seg.body_motion_x1000 === null || seg.body_motion_x1000 === undefined ? '—'
                : (Math.round(seg.body_motion_x1000 * 10) / 10)) + upMark(seg.body_motion_x1000, md.body_motion_x1000);
    }

    /** 「重点」里一条命中的观察行：没开摄像头 / 还没生成 / 有段落。旧版服务没有这些字段时不显示。 */
    function hitObsText(x, h) {
        if (!h || h.camera === undefined) { return ''; }
        if (h.camera === false) { return '未开启摄像头'; }
        if (!h.observe_ready) { return '同期观察：暂不可用（问诊结束后自动生成）'; }
        return obsLine(x.observe, h.observe_medians);
    }

    /** 「对话记录」里每条患者回答下方追加观察行；没开摄像头时整段只在最前面说一次。 */
    function markObserve() {
        var h = state.highlights || {};
        var old = el.chat.querySelectorAll('.msg-obs, .chat-obs-note');
        for (var i = 0; i < old.length; i += 1) { old[i].parentNode.removeChild(old[i]); }
        if (h.camera === undefined || !el.chat.querySelector('li.msg')) { return; }
        var note = h.camera === false ? '本场未开启摄像头'
            : (!h.observe_ready ? '摄像头观察结果暂不可用（问诊结束后自动生成）' : '');
        if (note) {
            var li = document.createElement('li');
            li.className = 'chat-obs-note';
            li.textContent = note;
            el.chat.insertBefore(li, el.chat.firstChild);
            return;
        }
        var byT = {};
        (h.observe_segments || []).forEach(function (s) {
            var k = tkey(s.t);
            if (k) { byT[k] = s; }
        });
        var msgs = el.chat.querySelectorAll('li.msg-user');
        for (var j = 0; j < msgs.length; j += 1) {
            var seg = byT[msgs[j].getAttribute('data-t') || ''];
            if (!seg) { continue; }
            var line = document.createElement('span');
            line.className = 'msg-obs';
            line.title = '摄像头观察到的动作数值，只与本人基线比较，不代表情绪或健康状况';
            line.textContent = obsLine(seg, h.observe_medians);
            msgs[j].appendChild(line);
        }
    }

    /* ── 重点（阶段三 judge）──────────────────────────────────────────── */

    function hitHTML(x, h) {
        var obs = hitObsText(x, h);
````

第 4 处 · `apps/multimodal/web/doctor.js`

查找：

````javascript
            (x.evidence ? '<span class="hl-ev">依据：「' + esc(x.evidence) + '」</span>' : '') +
            (labels.length
````

替换为：

````javascript
            (x.evidence ? '<span class="hl-ev">依据：「' + esc(x.evidence) + '」</span>' : '') +
            (obs ? '<span class="hl-obs">' + esc(obs) + '</span>' : '') +
            (labels.length
````

第 5 处 · `apps/multimodal/web/doctor.js`

查找：

````javascript
            el.hlList.innerHTML = hits.length ? hits.map(hitHTML).join('')
````

替换为：

````javascript
            el.hlList.innerHTML = hits.length ? hits.map(function (x) { return hitHTML(x, h); }).join('')
````

第 6 处 · `apps/multimodal/web/doctor.js`

查找：

````javascript
            msgs[i].classList.toggle('msg-hit-risk', hit && byT[k]);
        }
    }
````

替换为：

````javascript
            msgs[i].classList.toggle('msg-hit-risk', hit && byT[k]);
        }
        markObserve();   // 对话记录每次重画后，同期观察行也跟着补上
    }
````

第 7 处 · `apps/multimodal/web/doctor.js`

查找：

````javascript
            var sig = JSON.stringify([id, h.ready, h.stale, h.generated_at, (h.hits || []).length, h.error || '']);
````

替换为：

````javascript
            var sig = JSON.stringify([id, h.ready, h.stale, h.generated_at, (h.hits || []).length, h.error || '',
                h.camera, h.observe_ready, (h.observe_segments || []).map(function (s) { return s.frames; }).join(',')]);
````

- [ ] **Step 4: `doctor.css`**

`apps/multimodal/web/doctor.css`

查找：

````css
.hl-labels { display: flex; flex-wrap: wrap; gap: 2px 12px; font-size: 12px; color: var(--ink-2); }
````

替换为：

````css
.hl-labels { display: flex; flex-wrap: wrap; gap: 2px 12px; font-size: 12px; color: var(--ink-2); }
.hl-obs { font-size: 12.5px; color: var(--ink-2); font-variant-numeric: tabular-nums; }

/* 摄像头同期观察：对话记录里患者回答下方的一行，与没开摄像头时的一次性说明 */
.msg-obs { font-size: 12px; color: var(--ink-3); font-variant-numeric: tabular-nums; }
.chat-obs-note {
    align-self: stretch;
    padding: 6px 10px;
    border: 1px dashed var(--line);
    border-radius: var(--radius-sm);
    background: var(--bg-soft);
    font-size: 12.5px;
    color: var(--ink-3);
}
````

- [ ] **Step 5: Run smoke to verify it passes**

Run: `node --check apps/multimodal/web/doctor.js && node apps/multimodal/web/tests/smoke-doctor.mjs`
Expected:
```text
       同期观察（相对本人基线）：目光偏离 12% · 眨眼 16 次/分 · 手触脸 0% · 小动作 0.5
       同期观察（相对本人基线）：目光偏离 35% ↑ · 眨眼 26 次/分 ↑ · 手触脸 10% ↑ · 小动作 1.2 ↑
       同期观察：检出不足（unknown）
PASS  第一条回答：正常观察行
PASS  第二条回答：超过会话中位数 1.5 倍的项标 ↑
PASS  第三条回答：检出不足显示 unknown
PASS  开了摄像头的会话没有「未开启」说明
       同期观察（相对本人基线）：目光偏离 12% · 眨眼 16 次/分 · 手触脸 0% · 小动作 0.5
       同期观察：检出不足（unknown）
PASS  「重点」每条命中带同期观察
PASS  轮询重画后仍是 3 行
PASS  没开摄像头：只在最前面说一次，不逐条重复
PASS  开了摄像头但观察还没生成：说明一次

全部通过
```

- [ ] **Step 6: Commit**

```bash
git add apps/multimodal/web/doctor.js apps/multimodal/web/doctor.css apps/multimodal/web/tests/smoke-doctor.mjs
git commit -m "feat(web): 医生工作台对话记录与重点显示摄像头同期观察 (#8)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: 部署资源：`15_setup_camera_assets.sh`、`env.sh`、`13_deploy_web.sh`

**Files:**
- Create: `apps/multimodal/deploy/livetalking/15_setup_camera_assets.sh`
- Modify: `apps/multimodal/deploy/livetalking/env.sh`（Task 4 加的 `DOCTOR_OBSERVE` 那行之后、导出行）
- Modify: `apps/multimodal/deploy/livetalking/13_deploy_web.sh:24`、`:39-46`

**Interfaces:**
- Consumes：`env.sh` 的 `APP_DIR`、`PORT`、`PROXY`；`~/emotion-models/mediapipe/`（阶段三 `setup_spark.sh` 第 2 步已下载并校验）；Task 1 定下的 vendor 布局。
- Produces：`CAM_TASKS_VISION_VERSION=1.0.1`、`CAM_TASKS_VISION_INTEGRITY=sha512-rvRE…aUQ==`、`CAM_NPM_REGISTRY=https://registry.npmmirror.com`（`env.sh` 导出）；`15_setup_camera_assets.sh` 可选参数 `CAM_MODEL_DIR`（默认 `~/emotion-models/mediapipe`）、`CAM_ASSETS_TGZ`（离线 tgz）、`CAM_SELFTEST`（默认 1）；`$APP_DIR/web/vendor/mediapipe/` 布局与 Task 1 相同；`13_deploy_web.sh` 同步 `camera-metrics.js`、`camera-observe.js` 并自检 vendor。

- [ ] **Step 1: `env.sh` 加版本与校验值**

第 1 处 · `apps/multimodal/deploy/livetalking/env.sh`

查找：

````bash
export DOCTOR_ACTIVE_WINDOW DOCTOR_LT_ADMIN_URL DOCTOR_RECORD DOCTOR_OBS_DIR DOCTOR_OBSERVE
````

替换为：

````bash
export DOCTOR_ACTIVE_WINDOW DOCTOR_LT_ADMIN_URL DOCTOR_RECORD DOCTOR_OBS_DIR DOCTOR_OBSERVE
export CAM_TASKS_VISION_VERSION CAM_TASKS_VISION_INTEGRITY CAM_NPM_REGISTRY
````

第 2 处 · `apps/multimodal/deploy/livetalking/env.sh`

查找：

````bash
: "${DOCTOR_OBSERVE:=1}"                                       # 0 = 不收摄像头观察数据（接口返回 404，患者页照常问诊）
````

替换为：

````bash
: "${DOCTOR_OBSERVE:=1}"                                       # 0 = 不收摄像头观察数据（接口返回 404，患者页照常问诊）

# ---- 摄像头观察的网页端资源（15_setup_camera_assets.sh 使用）----
: "${CAM_TASKS_VISION_VERSION:=1.0.1}"                          # @mediapipe/tasks-vision，与阶段三 mediapipe==1.0.1 同版本
# npm 登记的 tgz 校验值；换版本时一起改：npm view @mediapipe/tasks-vision@<版本> dist.integrity
: "${CAM_TASKS_VISION_INTEGRITY:=sha512-rvRE2FmAZ6ZxKSw7wq+e+jQDpN3t1B/tD2mJz9SmAzb1msoDkd4dMoE4wAh8Z30Um0PQwLiHr9QtomhmXk3aUQ==}"
: "${CAM_NPM_REGISTRY:=https://registry.npmmirror.com}"         # 国内 npm 镜像，直连；不通时 15 改走官方源 + PROXY
````

- [ ] **Step 2: 写 15 号脚本**

Create `apps/multimodal/deploy/livetalking/15_setup_camera_assets.sh`：
````bash
#!/usr/bin/env bash
# 方案A-步骤15：患者页「摄像头观察」用的静态资源（MediaPipe Tasks Vision 网页版 + 两个模型）
#
# 装到 $APP_DIR/web/vendor/mediapipe/（LiveTalking 的静态目录，按请求读磁盘，不需要重启服务）：
#   vision_bundle.js（经典脚本，定义全局 Vision；患者页用它）、vision_bundle.mjs、wasm/*、package.json、VERSION、
#   face_landmarker.task、pose_landmarker_full.task
# 来源：
#   - 网页版：npm pack @mediapipe/tasks-vision@$CAM_TASKS_VISION_VERSION，先走 $CAM_NPM_REGISTRY（国内镜像，直连），
#     失败再走 npm 官方源（用 env.local.sh 的 PROXY）；两条都不通时在开发机下载 tgz 离线装：
#       CAM_ASSETS_TGZ=<mediapipe-tasks-vision-版本.tgz> bash 15_setup_camera_assets.sh
#     不管哪种来源，都按 CAM_TASKS_VISION_INTEGRITY（npm 登记的 sha512）校验；
#   - 模型：从阶段三的模型目录 $CAM_MODEL_DIR（默认 ~/emotion-models/mediapipe）复制，按 face_body/models.py 的 sha256 校验。
# 这些文件不进仓库（第三方二进制、体积大；.gitignore 已挡住 web/vendor/）。幂等：已装同版本就跳过下载。
# 自检（CAM_SELFTEST=0 跳过）：LiveTalking 在 :$PORT 运行时，用 curl 确认 4 个文件返回 200，并打印 Content-Type。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck disable=SC1091
source ./env.sh

: "${CAM_MODEL_DIR:=$HOME/emotion-models/mediapipe}"
: "${CAM_ASSETS_TGZ:=}"
: "${CAM_SELFTEST:=1}"
DEST="$APP_DIR/web/vendor/mediapipe"
# 与 apps/emotion/face_body/models.py 的登记一致
FACE_SHA=64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff
POSE_SHA=5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

integrity_of() { echo "sha512-$(openssl dgst -sha512 -binary "$1" | base64 | tr -d '\n')"; }

echo "==> [1/4] MediaPipe Tasks Vision 网页版 $CAM_TASKS_VISION_VERSION → $DEST"
mkdir -p "$DEST/wasm"
if [ -z "$CAM_ASSETS_TGZ" ] && [ -f "$DEST/vision_bundle.js" ] && [ -f "$DEST/VERSION" ] &&
   [ "$(cat "$DEST/VERSION")" = "$CAM_TASKS_VISION_VERSION" ]; then
  echo "    已是该版本，跳过下载（要重装先删 $DEST/VERSION）"
else
  tgz="$work/pkg.tgz"
  if [ -n "$CAM_ASSETS_TGZ" ]; then
    cp "$CAM_ASSETS_TGZ" "$tgz"
    echo "    离线安装：$CAM_ASSETS_TGZ"
  else
    command -v npm >/dev/null ||
      { echo "!! 没有 npm：在开发机 npm pack @mediapipe/tasks-vision@$CAM_TASKS_VISION_VERSION，再用 CAM_ASSETS_TGZ=<tgz> 离线安装"; exit 1; }
    pkg="@mediapipe/tasks-vision@$CAM_TASKS_VISION_VERSION"
    if ! (cd "$work" && env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
          npm pack "$pkg" --registry "$CAM_NPM_REGISTRY" >/dev/null 2>&1); then
      echo "    镜像 $CAM_NPM_REGISTRY 不通，改走 npm 官方源${PROXY:+（代理 $PROXY）}"
      (cd "$work" && npm pack "$pkg" --registry https://registry.npmjs.org/ \
          ${PROXY:+--proxy "$PROXY" --https-proxy "$PROXY"} >/dev/null)
    fi
    mv "$work"/mediapipe-tasks-vision-*.tgz "$tgz"
  fi
  got="$(integrity_of "$tgz")"
  if [ "$got" != "$CAM_TASKS_VISION_INTEGRITY" ]; then
    echo "!! tgz 校验失败：$got"
    echo "   应为 CAM_TASKS_VISION_INTEGRITY=$CAM_TASKS_VISION_INTEGRITY（换版本时两个变量一起改）"
    exit 1
  fi
  tar -xzf "$tgz" -C "$work"
  cp -f "$work/package/vision_bundle.js" "$work/package/vision_bundle.mjs" "$work/package/package.json" "$DEST/"
  rm -f "$DEST"/wasm/*
  cp -f "$work"/package/wasm/* "$DEST/wasm/"
  echo "$CAM_TASKS_VISION_VERSION" > "$DEST/VERSION"
  echo "    已安装（许可 Apache-2.0，见 $DEST/package.json）"
fi

echo "==> [2/4] 模型：$CAM_MODEL_DIR → $DEST（sha256 校验）"
for spec in "face_landmarker.task:$FACE_SHA" "pose_landmarker_full.task:$POSE_SHA"; do
  name="${spec%%:*}"
  want="${spec#*:}"
  if [ ! -f "$DEST/$name" ] || [ "$(sha256sum "$DEST/$name" | cut -d' ' -f1)" != "$want" ]; then
    src="$CAM_MODEL_DIR/$name"
    [ -f "$src" ] || { echo "!! 缺 $src：先在阶段三下载模型（apps/emotion/deploy/setup_spark.sh 第 2 步，或 python -m apps.emotion.face_body fetch-models --models $CAM_MODEL_DIR）"; exit 1; }
    [ "$(sha256sum "$src" | cut -d' ' -f1)" = "$want" ] || { echo "!! $src sha256 不对：重跑 fetch-models"; exit 1; }
    cp -f "$src" "$DEST/$name"
  fi
  echo "    OK   $name"
done

echo "==> [3/4] 自检（LiveTalking :$PORT 的静态路由）"
if [ "$CAM_SELFTEST" = "1" ]; then
  base="http://127.0.0.1:$PORT/vendor/mediapipe"
  fail=0
  for f in vision_bundle.js wasm/vision_wasm_internal.wasm face_landmarker.task pose_landmarker_full.task; do
    code="$(curl -s -o /dev/null -w '%{http_code}' -m 10 --noproxy '*' "$base/$f" || echo 000)"
    echo "    HTTP $code  /vendor/mediapipe/$f"
    [ "$code" = "200" ] || fail=1
  done
  for f in vision_bundle.js wasm/vision_wasm_internal.wasm; do
    ctype="$(curl -sI -m 10 --noproxy '*' "$base/$f" | tr -d '\r' | awk -F': ' 'tolower($1)=="content-type"{print $2}')"
    echo "    Content-Type  $f: ${ctype:-（无）}"
  done
  echo "    （.wasm 不是 application/wasm 时，浏览器会退回非流式编译，只是首次加载慢一点，不影响使用）"
  [ "$fail" = 0 ] || { echo "!! 有文件取不到：确认 LiveTalking 在运行（03_run.sh）、静态目录是 $APP_DIR/web"; exit 1; }
else
  echo "    跳过（CAM_SELFTEST=0）"
fi

echo "==> [4/4] 完成"
echo "    再跑 13_deploy_web.sh 同步 camera-observe.js / camera-metrics.js / triage.*，14_setup_doctor_console.sh 重启医生端服务"
echo "    患者页：http://<host>:$PORT/triage.html → 开始问诊后点「摄像头观察」"
````

- [ ] **Step 3: `13_deploy_web.sh` 同步新文件并自检 vendor**

第 1 处 · `apps/multimodal/deploy/livetalking/13_deploy_web.sh`

查找：

````bash
FILES=(triage.html triage.css triage.js mic-asr.js doctor.html doctor.css doctor.js)
````

替换为：

````bash
FILES=(triage.html triage.css triage.js mic-asr.js camera-metrics.js camera-observe.js doctor.html doctor.css doctor.js)
````

第 2 处 · `apps/multimodal/deploy/livetalking/13_deploy_web.sh`

查找：

````bash
    echo "    !!   缺少 $DEST/$dep（录音/识别会不可用，请先确认上游 LiveTalking 源码完整）"
  fi
done
````

替换为：

````bash
    echo "    !!   缺少 $DEST/$dep（录音/识别会不可用，请先确认上游 LiveTalking 源码完整）"
  fi
done
if [ -f "$DEST/vendor/mediapipe/vision_bundle.js" ]; then
  echo "    OK   vendor/mediapipe（摄像头观察，版本 $(cat "$DEST/vendor/mediapipe/VERSION" 2>/dev/null || echo 未知)）"
else
  echo "    --   没有 vendor/mediapipe：患者页的「摄像头观察」会显示不可用，问诊不受影响（装它跑 15_setup_camera_assets.sh）"
fi
````

- [ ] **Step 4: 语法检查**

Run: `cd apps/multimodal/deploy/livetalking && for f in env.sh 13_deploy_web.sh 14_setup_doctor_console.sh 15_setup_camera_assets.sh; do bash -n "$f" && echo "OK $f"; done; cd - >/dev/null`
Expected: 四行 `OK …`

- [ ] **Step 5: 本机演练（假的 APP_DIR + 本地静态服务，不碰 Spark）**

Run（Git Bash，仓库根目录；模型直接用 Task 1 放在 vendor 里的两个 `.task`）：
```bash
S="$(mktemp -d)"; mkdir -p "$S/app/web"
python -m http.server 18013 --bind 127.0.0.1 --directory "$S/app/web" >/dev/null 2>&1 &
SRV=$!; sleep 1
MODELS="$PWD/apps/multimodal/web/vendor/mediapipe"
cd apps/multimodal/deploy/livetalking
APP_DIR="$S/app" CAM_MODEL_DIR="$MODELS" PORT=18013 ICE_HOST=127.0.0.1 bash 15_setup_camera_assets.sh
echo "--- 再跑一次（应跳过下载）"
APP_DIR="$S/app" CAM_MODEL_DIR="$MODELS" PORT=18013 ICE_HOST=127.0.0.1 CAM_SELFTEST=0 bash 15_setup_camera_assets.sh | head -2
echo "--- 13 号脚本同步到假的 APP_DIR"
APP_DIR="$S/app" ICE_HOST=127.0.0.1 bash 13_deploy_web.sh | sed -n '1,20p'
cd - >/dev/null
kill "$SRV"
```
Expected（第一次，路径因机器而异）：
```text
==> [1/4] MediaPipe Tasks Vision 网页版 1.0.1 → …/app/web/vendor/mediapipe
    已安装（许可 Apache-2.0，见 …/package.json）
==> [2/4] 模型：… → …（sha256 校验）
    OK   face_landmarker.task
    OK   pose_landmarker_full.task
==> [3/4] 自检（LiveTalking :18013 的静态路由）
    HTTP 200  /vendor/mediapipe/vision_bundle.js
    HTTP 200  /vendor/mediapipe/wasm/vision_wasm_internal.wasm
    HTTP 200  /vendor/mediapipe/face_landmarker.task
    HTTP 200  /vendor/mediapipe/pose_landmarker_full.task
    Content-Type  vision_bundle.js: application/javascript
    Content-Type  wasm/vision_wasm_internal.wasm: application/wasm
…
==> [4/4] 完成
```
第二次第二行是 `    已是该版本，跳过下载（要重装先删 …/VERSION）`；13 号脚本列出的文件里有 `camera-metrics.js`、`camera-observe.js`，自检里有 `OK   vendor/mediapipe（摄像头观察，版本 1.0.1）`（本机没有 `asr/recorder-core.js`，那两行 `!!` 是预期的）。`kill` 在 Git Bash 里杀不掉时，用 PowerShell：`Get-NetTCPConnection -State Listen -LocalPort 18013 | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }`。

再验证校验失败会拦住（不需要 LiveTalking）：
```bash
tgz_dir="$(mktemp -d)"; (cd "$tgz_dir" && npm pack @mediapipe/tasks-vision@1.0.1 --registry https://registry.npmmirror.com >/dev/null)
printf 'x' >> "$tgz_dir"/mediapipe-tasks-vision-1.0.1.tgz
cd apps/multimodal/deploy/livetalking
APP_DIR="$(mktemp -d)" CAM_ASSETS_TGZ="$tgz_dir/mediapipe-tasks-vision-1.0.1.tgz" CAM_SELFTEST=0 ICE_HOST=127.0.0.1 bash 15_setup_camera_assets.sh; echo "exit=$?"
cd - >/dev/null
```
Expected: `!! tgz 校验失败：sha512-…` 与 `应为 CAM_TASKS_VISION_INTEGRITY=sha512-rvRE…aUQ==…`，`exit=1`。

- [ ] **Step 6: Commit**

```bash
git add apps/multimodal/deploy/livetalking/15_setup_camera_assets.sh apps/multimodal/deploy/livetalking/env.sh apps/multimodal/deploy/livetalking/13_deploy_web.sh
git commit -m "feat(deploy): 15 号脚本部署摄像头观察的网页端打点资源并校验 (#8)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: 本机端到端彩排（假摄像头 → frames → watch → observe → 医生端）

**Files:**
- Create: `apps/multimodal/web/tests/smoke-e2e.mjs`

**Interfaces:**
- Consumes：Task 1 `headless.mjs` 与本机 vendor；Task 2 `live.py`；Task 3 `python -m apps.emotion.judge.watch --once --obs-dir …`；Task 4 doctor_service（`DOCTOR_*` 环境变量）；Task 6 患者页与 `?obs_port=`；Task 7 医生端 `.msg-obs`。
- Produces：一条可重复的本机彩排命令，证明整条链路（问诊记录按真实时钟写虚构事件；judge 指向不存在的模型地址，只会判断失败，不影响同期观察）。

- [ ] **Step 1: 写彩排脚本**

Create `apps/multimodal/web/tests/smoke-e2e.mjs`：
````javascript
// 本机端到端彩排：假摄像头 → 患者页上传 → frames.jsonl → emotion-judge-watch --once（live.py）→ observe.json
// → doctor_service /highlights → 医生工作台「对话记录」每条患者回答下的同期观察。
//
//   node apps/multimodal/web/tests/smoke-e2e.mjs [--face <face.y4m>]
//
// 前提同 smoke-camera.mjs（vendor 已放好；python 有 fastapi、uvicorn、numpy）。仓库根目录下运行。
// 问诊记录是脚本按真实时钟写的虚构事件（没有 LiveTalking）；judge 指向不存在的模型地址，只会判断失败，不影响同期观察。
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { launchChrome, sleep } from './headless.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(HERE, '..');
const ROOT = path.resolve(WEB, '..', '..', '..');
const PY = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const faceArg = process.argv.indexOf('--face');
const FACE = faceArg > 0 ? path.resolve(process.argv[faceArg + 1]) : '';
const SID = 'e2e-cam-0001';
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'cam-e2e-'));
const dirs = { obs: path.join(tmp, 'obs'), rec: path.join(tmp, 'rec'), judge: path.join(tmp, 'judge') };
Object.values(dirs).forEach((d) => fs.mkdirSync(d));
const recPath = path.join(dirs.rec, `${SID}.jsonl`);
const procs = [];
let failed = 0;
function check(ok, msg) { console.log(`${ok ? 'PASS' : 'FAIL'}  ${msg}`); if (!ok) { failed += 1; } }

function event(kind, text) {   // 与 consult_recorder 同格式：服务器秒
    const ev = { t: Date.now() / 1000, kind, text };
    fs.appendFileSync(recPath, JSON.stringify(ev) + '\n');
    return ev;
}

async function waitHttp(url, ms = 20000) {
    const until = Date.now() + ms;
    for (;;) {
        try { if ((await fetch(url)).ok) { return; } } catch (e) { /* 还没起来 */ }
        if (Date.now() > until) { throw new Error(`服务没起来：${url}`); }
        await sleep(300);
    }
}

async function main() {
    procs.push(spawn(PY, ['-m', 'http.server', '18010', '--bind', '127.0.0.1', '--directory', WEB], { stdio: 'ignore' }));
    procs.push(spawn(PY, [path.join(ROOT, 'apps/multimodal/deploy/livetalking/doctor_service.py')], {
        stdio: 'ignore',
        env: Object.assign({}, process.env, {
            DOCTOR_PORT: '18110', DOCTOR_HOST: '127.0.0.1', DOCTOR_WEB_DIR: WEB, DOCTOR_OBS_DIR: dirs.obs,
            DOCTOR_RECORD_DIR: dirs.rec, DOCTOR_JUDGE_DIR: dirs.judge,
            DOCTOR_LT_ADMIN_URL: 'http://127.0.0.1:9/api/admin/sessions',
        }),
    }));
    await waitHttp('http://127.0.0.1:18010/triage.html');
    await waitHttp('http://127.0.0.1:18110/health');
    const chrome = await launchChrome(FACE ? [`--use-file-for-fake-video-capture=${FACE}`] : []);
    try {
        const page = await chrome.open('http://127.0.0.1:18010/triage.html?obs_port=18110');
        await page.waitFor('window.CameraObserve && document.readyState === "complete"');
        await page.eval(`window.__triage.consultId = '${SID}'; window.CameraObserve.sessionReady(); true`);
        await page.eval(`document.getElementById('cam-toggle').click(); true`);
        await page.waitFor('window.CameraObserve.debug().running', 60000);
        await sleep(6000);                                        // 前 5 秒建立本人基线
        event('assistant', '您好，请问哪里不舒服？');
        await page.eval('window.CameraObserve.markReplyEnd(); true');
        await sleep(6000);
        const u1 = event('user', '（虚构）胃胀两天');
        await sleep(1000);
        event('assistant', '吃完饭会更明显吗？');
        await page.eval('window.CameraObserve.markReplyEnd(); true');
        await sleep(6000);
        const u2 = event('user', '（虚构）饭后明显');
        await page.eval('window.CameraObserve.sessionEnded(); true');   // 点「结束问诊」：送出最后一批
        await sleep(1500);
        fs.appendFileSync(recPath, JSON.stringify({ t: Date.now() / 1000, kind: 'summary', doctor: '## 医生参考版（虚构）', patient: '' }) + '\n');
        page.close();

        const rows = fs.readFileSync(path.join(dirs.obs, `${SID}.frames.jsonl`), 'utf8').trim().split('\n');
        check(rows.length >= 60, `frames.jsonl ${rows.length} 行`);

        const watch = spawnSync(PY, ['-m', 'apps.emotion.judge.watch', '--once', '--consult-dir', dirs.rec,
            '--out-dir', dirs.judge, '--obs-dir', dirs.obs, '--backend', 'ollama', '--host', 'http://127.0.0.1:9',
            '--timeout', '2', '--max-wait', '0', '--lt-admin-url', 'http://127.0.0.1:9/x'],
        { cwd: ROOT, encoding: 'utf8' });
        console.log(watch.stdout.trim().split('\n').map((l) => '       ' + l).join('\n'));
        check(/同期观察已生成：2 段回答/.test(watch.stdout), 'watch --once 生成了同期观察（judge 失败不影响）');
        const obs = JSON.parse(fs.readFileSync(path.join(dirs.judge, `${SID}.observe.json`), 'utf8'));
        check(obs.segments.length === 2 && obs.segments[0].t === u1.t && obs.segments[1].t === u2.t,
            'observe.json 两段，t 与问诊记录的患者事件完全相同');
        if (FACE) {
            check(obs.segments.every((s) => s.face_status === 'ok'), `有人脸：两段 face_status 都是 ok（${obs.segments.map((s) => s.frames).join(', ')} 帧）`);
        }

        const h = await (await fetch(`http://127.0.0.1:18110/api/doctor/sessions/${SID}/highlights`)).json();
        check(h.camera === true && h.observe_ready === true && h.observe_segments.length === 2,
            `/highlights：camera=${h.camera} observe_ready=${h.observe_ready} 段数=${h.observe_segments.length}（judge ready=${h.ready}）`);

        const doc = await chrome.open(`http://127.0.0.1:18110/?tab=chat#${SID}`);
        await doc.waitFor(`document.querySelectorAll('#chat .msg-obs').length === 2`, 20000);
        const lines = await doc.eval(`Array.from(document.querySelectorAll('#chat .msg-obs')).map(function (n) { return n.textContent; })`);
        lines.forEach((l) => console.log('       ' + l));
        check(lines.every((l) => /^同期观察/.test(l)), '医生工作台「对话记录」两条患者回答下都有同期观察');
        doc.close();
    } finally {
        await chrome.close();
        procs.forEach((p) => p.kill());
        await sleep(500);
        try { fs.rmSync(tmp, { recursive: true, force: true }); } catch (e) { /* Windows 上可能还被占着 */ }
    }
    console.log(failed ? `\n${failed} 项失败` : '\n全部通过');
    process.exit(failed ? 1 : 0);
}

main().catch((err) => { console.error(err); procs.forEach((p) => p.kill()); process.exit(1); });
````

- [ ] **Step 2: 跑彩排**

Run（Git Bash，仓库根目录；`face.y4m` 用 Task 6 Step 8 生成的，临时目录没了就重新生成）：
```bash
Y4M_DIR="$(mktemp -d)"; python apps/multimodal/web/tests/make_face_y4m.py --out "$Y4M_DIR/face.y4m"
node apps/multimodal/web/tests/smoke-e2e.mjs --face "$Y4M_DIR/face.y4m"
```
Expected（时间、路径、数值因机器而异）：
```text
PASS  frames.jsonl 9x 行
       [watch] …盯 …rec → …judge；来源 local:…；结束或静默 180s 后判断；同期观察读 …obs
       [watch] … e2e-cam- 同期观察已生成：2 段回答，其中 2 段有数（0.0s）
       [watch] … e2e-cam- 判断失败：4 次后端出错，稍后重试（0.0s）
PASS  watch --once 生成了同期观察（judge 失败不影响）
PASS  observe.json 两段，t 与问诊记录的患者事件完全相同
PASS  有人脸：两段 face_status 都是 ok（30, 30 帧）
PASS  /highlights：camera=true observe_ready=true 段数=2（judge ready=false）
       同期观察（相对本人基线）：目光偏离 0% · 眨眼 0 次/分 · 手触脸 0% · 小动作 8.9
       同期观察（相对本人基线）：目光偏离 0% · 眨眼 0 次/分 · 手触脸 0% · 小动作 9
PASS  医生工作台「对话记录」两条患者回答下都有同期观察

全部通过
```

- [ ] **Step 3: 全量回归**

Run:
```bash
python -m pytest apps/emotion/face_body/tests -q -p no:cacheprovider
python -m pytest apps/emotion/judge/tests -q -p no:cacheprovider
python -m pytest apps/multimodal/deploy/livetalking/tests -q -p no:cacheprovider
node --test apps/multimodal/web/tests/camera-metrics.test.js
for f in camera-metrics.js camera-observe.js triage.js doctor.js mic-asr.js; do node --check "apps/multimodal/web/$f" || echo "FAIL $f"; done
node apps/multimodal/web/tests/smoke-doctor.mjs
```
Expected: `62 passed`；`88 passed`；`32 passed, 1 skipped`（Linux 上 `33 passed`）；`# pass 7` `# fail 0`；`node --check` 没有输出；`smoke-doctor` 末尾 `全部通过`。

- [ ] **Step 4: Commit**

```bash
git add apps/multimodal/web/tests/smoke-e2e.mjs
git commit -m "test(web): 摄像头观察本机端到端彩排脚本 (#8)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: 文档（README、隐私、face_body、实机手册、第三方声明、部署说明）

**Files:**
- Modify: `README.md`（「它能做什么」`:18-36`、架构图 `:42-77`、关键数据 `:104-105`、医疗安全 `:114`、仓库结构 `:130`）
- Modify: `docs/safety-and-privacy.md:30`
- Modify: `apps/emotion/face_body/README.md`（`:47` 之前新增一节、`:53`、`:67`、`:74`）
- Modify: `docs/实机测试操作手册.md`（`:82`、`:125`、`:148`、`:175`、`:194`、`:197`）
- Modify: `THIRD_PARTY_NOTICES.md:39`
- Modify: `apps/multimodal/README.md`（web 文件表 `doctor.js` 那一行之后）
- Modify: `apps/multimodal/deploy/livetalking/README.md`（`:30-31`、`:82`、`:192`、`:270`、`:307`）
- Modify: `apps/emotion/deploy/README.md:116`
- Modify（仓库状态里「face_body 只离线」的旧说法）: `AGENTS.md:98`、`apps/emotion/README.md:8`、`docs/architecture/overview.md:17`、`docs/product.md:32`

**Interfaces:**
- Consumes：前面各任务的实际行为与数字（测试数 62 / 88 / 33 / 7、约 5 fps、每 2 秒一批、64 KB / 50 帧 / 20 MB、目录与文件权限、`DOCTOR_OBSERVE=0`）。
- Produces：对外文档与实现一致；公开安全检查通过。

- [ ] **Step 1: README.md**

依次做下面 11 处替换：
第 1 处 · `README.md`

查找：

````markdown
5. 结束后生成两版记录，患者页展示"患者核对版"，患者可提出更正。
````

替换为：

````markdown
5. 结束后生成两版记录，患者页展示"患者核对版"，患者可提出更正；
6. **可选的摄像头观察**（默认关闭）：患者主动开启后，画面一角的小窗显示本人预览和面部打点、上身骨架，下方实时显示转头、眨眼、目光偏离等动作数值；每说完一句话，这句下面追加一行「本次回答观察」。画面只在浏览器里处理，只把关键点数值发给 Spark；不开摄像头时问诊流程完全不变。
````

第 2 处 · `README.md`

查找：

````markdown
2. 「对话记录」：整场问诊的文字版全文，区分患者/助手、语音/文字输入；
````

替换为：

````markdown
2. 「对话记录」：整场问诊的文字版全文，区分患者/助手、语音/文字输入；患者开了摄像头时，每条患者回答下附一行同期观察（相对本人基线的目光偏离、眨眼、手触脸、小动作，数据不足标 `unknown`；没开摄像头只在最前面说明一次）；
````

第 3 处 · `README.md`

查找：

````markdown
4. 「重点」：问诊结束后由本地大模型自动标出值得先看的患者回答，**风险线索永远排在最前**，点一条跳回对话原句；不给任何情绪标签。
````

替换为：

````markdown
4. 「重点」：问诊结束后由本地大模型自动标出值得先看的患者回答，**风险线索永远排在最前**，点一条跳回对话原句，每条命中同样附同期观察；不给任何情绪标签。
````

第 4 处 · `README.md`

查找：

````markdown
不做人脸识别，不做表情或情绪分类。目前离线处理视频文件，尚未接入实时问诊。
````

替换为：

````markdown
不做人脸识别，不做表情或情绪分类。既能离线处理视频文件，也用于实时问诊的摄像头观察：浏览器端打点（约 5 fps），问诊结束后由 `live.py` 按每条患者回答切段统计，不进 judge。
````

第 5 处 · `README.md`

查找：

````markdown
        PT["患者页<br/>数字人画面 · 麦克风 · 文字对话"]
````

替换为：

````markdown
        PT["患者页<br/>数字人画面 · 麦克风 · 文字对话<br/>可选摄像头观察（浏览器端打点）"]
````

第 6 处 · `README.md`

查找：

````markdown
        FB["face_body<br/>离线视频观察"]
    end
````

替换为：

````markdown
        FB["face_body<br/>离线视频 · 实时观察统计"]
        OBS[("关键点数值<br/>frames.jsonl")]
    end
````

第 7 处 · `README.md`

查找：

````markdown
    VID["录制的视频文件"] -.-> FB
````

替换为：

````markdown
    PT -.->|"关键点数值（可选，画面不出浏览器）"| DS
    DS -->|"追加写"| OBS
    OBS --> FB
    JW -->|"问诊结束后调用"| FB
    FB -->|"同期观察"| DS
    VID["录制的视频文件"] -.-> FB
````

第 8 处 · `README.md`

查找：

````markdown
| 面部与身体观察 | 约 9 帧/秒；人脸与姿态检出率 1.0 | Spark CPU，512×512 视频（5 s，125 帧） | [`face_body/README.md`](apps/emotion/face_body/README.md) |
````

替换为：

````markdown
| 面部与身体观察 | 约 9 帧/秒；人脸与姿态检出率 1.0 | Spark CPU，512×512 视频（5 s，125 帧） | [`face_body/README.md`](apps/emotion/face_body/README.md) |
| 摄像头观察（患者页） | 浏览器端约 5 fps 打点；每 2 秒上传一批关键点数值；画面不出浏览器 | MediaPipe Tasks Vision 网页版 1.0.1，患者电脑 CPU | [`face_body/README.md`](apps/emotion/face_body/README.md)「实时通道」 |
````

第 9 处 · `README.md`

查找：

````markdown
| 单元测试 | judge 83 个 + face_body 43 个，全部通过（本机与 Spark 均已运行） | 不需要模型、不联网 | `pytest apps/emotion/*/tests` |
````

替换为：

````markdown
| 单元测试 | judge 88 个 + face_body 62 个（本机与 Spark 均已运行）；医生端接口 33 个、浏览器端指标 7 个（本机） | 不需要模型、不联网 | `pytest apps/emotion/*/tests`、`pytest apps/multimodal/deploy/livetalking/tests`、`node --test apps/multimodal/web/tests/camera-metrics.test.js` |
````

第 10 处 · `README.md`

查找：

````markdown
- **数据最小化**：原始录音不落盘，只在内存中用于识别；问诊只保存文字记录，文件仅属主可读写，可整体关闭记录；face_body 只输出数值、不存图像；agent 的问诊记录与记忆不进仓库。
````

替换为：

````markdown
- **数据最小化**：原始录音不落盘，只在内存中用于识别；问诊只保存文字记录，文件仅属主可读写，可整体关闭记录；摄像头观察默认关闭，画面不出浏览器，Spark 只存关键点数值；face_body 只输出数值、不存图像；agent 的问诊记录与记忆不进仓库。
````

第 11 处 · `README.md`

查找：

````markdown
    face_body/             面部与身体观察（MediaPipe，离线）
````

替换为：

````markdown
    face_body/             面部与身体观察（MediaPipe；离线视频与实时摄像头观察）
````

- [ ] **Step 2: `docs/safety-and-privacy.md`**

`docs/safety-and-privacy.md`

查找：

````markdown
- 实时问诊的音频只在内存中用于识别，不落盘；实时问诊目前不采集摄像头画面。阶段三 face_body 只离线处理事先录好的视频，`analyze` 只输出数值、不存图像；
````

替换为：

````markdown
- 实时问诊的音频只在内存中用于识别，不落盘。阶段三 face_body 离线处理事先录好的视频时，`analyze` 只输出数值、不存图像；
- 实时问诊可选「摄像头观察」：默认关闭，由患者主动开启，开启前说明一次，开启期间画面上常驻「摄像头观察中 · 画面只在本机处理」角标，随时可关，不开也能正常问诊。画面只在患者浏览器的内存里处理（MediaPipe 网页版），不录像、不截图、不上传；离开浏览器的只有关键点数值（26 个 blendshape 分数、4×4 头姿矩阵、25 个姿态点的坐标与可见度），由医生端服务写到 Spark 的 `DOCTOR_OBS_DIR`（默认 `~/livetalking-logs/observations/<会话>.frames.jsonl`，文件 600、目录 700）；问诊结束后阶段三把它统计成 `<会话>.observe.json`（与 judge 结果同目录）。不做身份识别，不出情绪标签，医生端只显示相对本人基线的动作数值，数据不足标 `unknown`，也不进 judge 的判断。关闭方法：患者页上的开关；服务端在 `env.local.sh` 写 `DOCTOR_OBSERVE=0` 后重跑 `14_setup_doctor_console.sh`（接口返回 404）。目前没有保留期限和自动删除，**正式试用前需补充保留期限和删除流程**；
````

- [ ] **Step 3: `apps/emotion/face_body/README.md`**

第 1 处 · `apps/emotion/face_body/README.md`

查找：

````markdown
## 隐私与边界
````

替换为：

````markdown
## 实时通道（浏览器打点）

实时问诊时患者可以在患者页打开「摄像头观察」（默认关闭）。打点在患者浏览器里做（MediaPipe Tasks Vision 网页版 1.0.1，
与这里的 Python 版同一套模型），画面不出浏览器；只上传逐帧的关键点数值，统计在 Spark 上由 `live.py` 完成：

```text
患者页 camera-observe.js ──每 2 秒一批──▶ doctor_service POST /api/observe/<会话>
                                           └─ 追加写 ~/livetalking-logs/observations/<会话>.frames.jsonl
emotion-judge-watch（问诊结束后，不用大模型）──▶ live.py ──▶ outputs/judge/consult/<会话>.observe.json
                                                              └─ 医生工作台「对话记录」「重点」的同期观察
```

- **逐帧**：`frames.jsonl` 每行 `{"t": 服务器秒, "f": {"bs": 26 个 blendshape, "m": 16 个数} | null, "p": 25 × [x, y, 可见度] | null}`；
  `to_frame_record` 还原成与 `analyze.frame_record` 同形的帧记录。网页版的头姿矩阵按原样（列主序）上传，
  `matrix_from_flat` 按平移所在的位置自动还原（核实记录：`docs/superpowers/plans/notes/2026-09-29-mediapipe-js-matrix.md`）。
- **切段**：问诊记录里每条患者回答（`kind == "user"`，时间 `t_u`）一段，起点取「上一条助手回复或上一条患者回答」，
  最长 60 秒，且不早于开启摄像头；问诊记录的 `t` 是识别完成的时刻，所以一段覆盖「听题 + 作答」。
- **统计**：本人基线 = 开启后前 5 秒的中位数；每段用 `windows.aggregate`（同样的平滑、滞回和阈值），
  检出帧 < 6、检出率 < 0.5 或覆盖不到半段记 `unknown`、不给数；另给出各指标的会话中位数，医生端超过 1.5 倍标 ↑。
- **输出** `observe.json`（`schema_version: face_body-live-0.1`）：`camera_frames`、人脸 / 姿态检出率、`baseline`、`medians`、
  `segments[]`（`t`、`interval`、`frames`、`face_status`、`body_status`、`gaze_away_ratio`、`blink_count`、`blink_per_min`、
  `head_motion_deg_per_frame`、`hand_face_ratio`、`body_motion_x1000`）。
- 手动重算一场：`python -m apps.emotion.face_body.live --consult <会话>.jsonl --frames <会话>.frames.jsonl --out-dir <目录>`。
- 患者页上的实时面板和每条回答下的观察行是浏览器端近似（`apps/multimodal/web/camera-metrics.js`，口径照搬这里，
  有一致性测试），医生端的数以这里为准。

## 隐私与边界
````

第 2 处 · `apps/emotion/face_body/README.md`

查找：

````markdown
  本模块只是离线分析工具，实时接入数字人问诊时由集成方负责这些提示。
````

替换为：

````markdown
  实时通道的这些提示在患者页 `camera-observe.js` 里：默认关闭、开启前说明一次、常驻角标、随时可关。
````

第 3 处 · `apps/emotion/face_body/README.md`

查找：

````markdown
- 实时通道（患者浏览器摄像头 → Spark）未接，现在是离线处理视频文件。
````

替换为：

````markdown
- 实时通道只在问诊结束后统计（医生端没有实时数值）；浏览器端约 5 fps，比离线视频的帧率低，眨眼这类快动作可能漏计；
  基线取开启摄像头后的前 5 秒，开启时就偏开视线会让「目光偏离」偏低。
````

第 4 处 · `apps/emotion/face_body/README.md`

查找：

````markdown
windows.py    时间窗聚合、本人基线、unknown 判定、报告（纯 numpy）
````

替换为：

````markdown
windows.py    时间窗聚合、本人基线、unknown 判定、报告（纯 numpy）
live.py       实时通道：浏览器打点的逐帧数值 + 问诊记录 → 按每条回答切段的同期观察（纯 numpy）
````

- [ ] **Step 4: `docs/实机测试操作手册.md`**

第 1 处 · `docs/实机测试操作手册.md`

查找：

````markdown
8. **等待时间**：首轮回复约 4 秒（部署文档实测），之后每轮约 1 秒；服务繁忙时会更久。超过约 2 秒还没开口时，数字人会先说"嗯，我看看"之类的垫话。右侧文字会在数字人开口时同步出现。
````

替换为：

````markdown
8. **等待时间**：首轮回复约 4 秒（部署文档实测），之后每轮约 1 秒；服务繁忙时会更久。超过约 2 秒还没开口时，数字人会先说"嗯，我看看"之类的垫话。右侧文字会在数字人开口时同步出现。
9. **摄像头观察（可选，默认关闭）**：连上数字人后，左下麦克风条右侧的「摄像头观察：关」变为可点。点它会先弹出一次说明，确定后浏览器请求摄像头权限，选"允许"。
   - 画面右下角出现 160×120 的小窗：本人的镜像预览，叠加面部稀疏点（青色）和上身骨架（黄色），上方常驻红色角标"摄像头观察中 · 画面只在本机处理"；
   - 小窗下方是实时面板：前 5 秒显示"正在建立本人基线…"，之后显示左右转头、俯仰角度，以及本次回答的眨眼次数、目光偏离、手触脸，转头、眨眼时数值跟着变；可点「收起」；
   - 每说完一句话，右侧这句话下面出现一行小字"本次回答观察：…"；帧数不够时显示"观察数据不足"；
   - 再点一次开关即关闭；点「结束问诊」时自动关闭并释放摄像头。不开摄像头时一切照旧；
   - 画面只在您的浏览器里处理，只有关键点数值经 8110 端口传到 Spark，所以隧道里必须有 `-L 8110:127.0.0.1:8110`。
````

第 2 处 · `docs/实机测试操作手册.md`

查找：

````markdown
- **页签上的小圆点**：绿点表示该页已有内容（总结已生成，或重点已有命中）；「重点」上的红点表示含疑似风险线索。
````

替换为：

````markdown
- **同期观察**（患者开了摄像头时）：问诊结束后约半分钟内，「对话记录」每条患者回答下方、「重点」每条命中下方多一行"同期观察（相对本人基线）：目光偏离 · 眨眼 · 手触脸 · 小动作"，超过本场中位数 1.5 倍的项标 ↑；数据不足显示"检出不足（unknown）"；本场没开摄像头时，对话记录最前面只显示一次"本场未开启摄像头"。这些只是动作数值，不代表情绪或健康状况。
- **页签上的小圆点**：绿点表示该页已有内容（总结已生成，或重点已有命中）；「重点」上的红点表示含疑似风险线索。
````

第 3 处 · `docs/实机测试操作手册.md`

查找：

````markdown
- **face_body 目前只离线处理事先录好的视频，实时问诊不采集摄像头画面。** 团队运行 `analyze` / `annotate` 的方法见 [`apps/emotion/deploy/README.md`](../apps/emotion/deploy/README.md) 的「三、在 Spark 上跑」。
````

替换为：

````markdown
- `judge/consult/<会话>.observe.json`：开了摄像头观察的问诊，每条患者回答的同期观察数值（问诊结束后生成）。
- face_body 离线分析视频（`analyze` / `annotate`）的方法见 [`apps/emotion/deploy/README.md`](../apps/emotion/deploy/README.md) 的「三、在 Spark 上跑」。
````

第 4 处 · `docs/实机测试操作手册.md`

查找：

````markdown
| 「重点」一直不出现 | 患者页是否已「确认无误」或已关闭；是否点过结束按钮；是否还有其他人在问诊（见第 4 节的时间表）；页签显示"对话有更新，正在重新生成"时稍等即可 |
````

替换为：

````markdown
| 「重点」一直不出现 | 患者页是否已「确认无误」或已关闭；是否点过结束按钮；是否还有其他人在问诊（见第 4 节的时间表）；页签显示"对话有更新，正在重新生成"时稍等即可 |
| 「摄像头观察」是灰的，点不了 | 先点「开始问诊」连上数字人；显示"摄像头观察不可用"说明 Spark 上没装网页端打点资源（`15_setup_camera_assets.sh`），请联系负责人。问诊不受影响 |
| 摄像头被拒绝，或提示"未获得摄像头权限" | 地址栏左侧的网站设置里把摄像头改为允许，再刷新页面；检查系统隐私设置是否允许浏览器使用摄像头；会议软件占着摄像头时先关掉它 |
| 小窗黑屏或没有打点 | 摄像头被其他程序占用或镜头被遮住；关掉开关再打开；光线太暗时检不出人脸，面板对应项显示"—" |
| 提示"观察数据未能上传" | 隧道里是否有 `-L 8110:127.0.0.1:8110`；问诊不受影响，只是医生端不会有同期观察 |
| 医生端同期观察显示"检出不足（unknown）" | 这句回答期间帧数不够（摄像头中途关了、人离开画面、侧脸太多）；这是保守输出，不是故障 |
````

第 5 处 · `docs/实机测试操作手册.md`

查找：

````markdown
   - 「重点」判断结果；
````

替换为：

````markdown
   - 「重点」判断结果；
   - 开了摄像头观察时：关键点数值（`~/livetalking-logs/observations/<会话>.frames.jsonl`，只有数值、没有图像）和统计结果 `<会话>.observe.json`；
````

第 6 处 · `docs/实机测试操作手册.md`

查找：

````markdown
   原始录音只在内存中用于识别，不落盘；实时问诊不采集摄像头画面。需要删除测试记录时，请联系负责人。详见 [`safety-and-privacy.md`](safety-and-privacy.md)。
````

替换为：

````markdown
   原始录音只在内存中用于识别，不落盘；摄像头画面只在您的浏览器里处理，不录像、不上传。需要删除测试记录时，请联系负责人。详见 [`safety-and-privacy.md`](safety-and-privacy.md)。
````

- [ ] **Step 5: `THIRD_PARTY_NOTICES.md` 与 `apps/multimodal/README.md`**

`THIRD_PARTY_NOTICES.md`

查找：

````markdown
| [MediaPipe](https://github.com/google-ai-edge/mediapipe) | 面部与姿态关键点（阶段三 `face_body`） | Apache-2.0 |
````

替换为：

````markdown
| [MediaPipe](https://github.com/google-ai-edge/mediapipe) | 面部与姿态关键点（阶段三 `face_body`） | Apache-2.0 |
| [@mediapipe/tasks-vision](https://www.npmjs.com/package/@mediapipe/tasks-vision)（MediaPipe Tasks Vision 网页版 1.0.1） | 患者页摄像头观察的浏览器端打点；`15_setup_camera_assets.sh` 部署时从 npm 下载（校验 sha512）到 LiveTalking 静态目录，模型复用上一行的 MediaPipe 模型 | Apache-2.0（npm 包的 `package.json`） |
````

`apps/multimodal/README.md`

查找：

````markdown
| `web/doctor.js` | 会话列表轮询、详情渲染、总结与复制；`?demo=1` 可离线预览 |
````

替换为：

````markdown
| `web/doctor.js` | 会话列表轮询、详情渲染、总结与复制；`?demo=1` 可离线预览 |
| `web/camera-observe.js` | 患者页「摄像头观察」（可选，默认关闭）：本机打点、小窗与实时面板、每 2 秒上传关键点数值到 `:8110/api/observe/<会话>` |
| `web/camera-metrics.js` | 摄像头观察的逐帧换算与统计（纯函数，口径照搬 `face_body`，node 可测） |
| `web/tests/` | node 单元测试与一致性测试、无头 Chrome 冒烟脚本（不部署） |
| `web/vendor/mediapipe/` | MediaPipe 网页版与模型：`15_setup_camera_assets.sh` 部署时放进 LiveTalking 静态目录，**不进仓库** |
````

- [ ] **Step 6: 部署说明（阶段二、阶段三）**

第 1 处 · `apps/multimodal/deploy/livetalking/README.md`

查找：

````markdown
| 9 | `13_deploy_web.sh` | 部署阶段二预问诊页面（`triage.html/css/js` + `mic-asr.js`，同时带上 `doctor.html/css/js` 作为入口） | <1min | 自检录音依赖 `web/asr/recorder-core.js` |
| 10 | `14_setup_doctor_console.sh` | 医生端控制台：独立 venv 起 `doctor_service.py`（`0.0.0.0:8110`），静态托管 `doctor.*` 并提供 `/api/doctor/*` | 1–3min | 轮询 `/health`，输出访问地址 |
````

替换为：

````markdown
| 9 | `13_deploy_web.sh` | 部署阶段二预问诊页面（`triage.html/css/js` + `mic-asr.js` + `camera-*.js`，同时带上 `doctor.html/css/js` 作为入口） | <1min | 自检录音依赖 `web/asr/recorder-core.js` 与 `web/vendor/mediapipe` |
| 10 | `14_setup_doctor_console.sh` | 医生端控制台：独立 venv 起 `doctor_service.py`（`0.0.0.0:8110`），静态托管 `doctor.*` 并提供 `/api/doctor/*`，并接收患者页摄像头观察的关键点数值（`POST /api/observe/<会话>`） | 1–3min | 轮询 `/health`，输出访问地址 |
| 11 | `15_setup_camera_assets.sh` | 患者页「摄像头观察」的静态资源：MediaPipe 网页版（npm `@mediapipe/tasks-vision`，校验 sha512）+ 两个模型（从 `~/emotion-models/mediapipe` 复制，校验 sha256）→ `$APP_DIR/web/vendor/mediapipe/`；不进仓库；npm 不通时用 `CAM_ASSETS_TGZ` 离线装 | 1–2min | curl 自检 4 个文件返回 200，打印 Content-Type |
````

第 2 处 · `apps/multimodal/deploy/livetalking/README.md`

查找：

````markdown
| `DOCTOR_RECORD` | `1` | 置 `0` 暂停问诊记录落盘（隐私演练/排障用） |
````

替换为：

````markdown
| `DOCTOR_RECORD` | `1` | 置 `0` 暂停问诊记录落盘（隐私演练/排障用） |
| `DOCTOR_OBS_DIR` | `~/livetalking-logs/observations` | 摄像头观察的关键点数值落盘目录（目录 700、文件 600），与阶段三 `spark.env` 的 `EMOTION_OBS_DIR` **必须相同** |
| `DOCTOR_OBSERVE` | `1` | 置 `0` 不收摄像头观察数据（`/api/observe` 返回 404，患者页照常问诊） |
| `CAM_TASKS_VISION_VERSION` / `CAM_TASKS_VISION_INTEGRITY` | `1.0.1` / npm 登记的 sha512 | `15` 装的网页版版本与校验值，换版本时两个一起改 |
| `CAM_NPM_REGISTRY` | `https://registry.npmmirror.com` | `15` 先走的 npm 镜像（直连），不通再走官方源 + `PROXY` |
````

第 3 处 · `apps/multimodal/deploy/livetalking/README.md`

查找：

````markdown
| `8110` TCP | 医生端控制台（页面 + 只读接口） | 医生不在同机时才放通 |
````

替换为：

````markdown
| `8110` TCP | 医生端控制台（页面 + 只读接口）；患者页摄像头观察上传关键点数值（`POST /api/observe`） | 医生不在同机时才放通；经 SSH 隧道使用时患者端也要转发 8110 |
````

第 4 处 · `apps/multimodal/deploy/livetalking/README.md`

查找：

````markdown
右侧气泡文本随流式事件增长。真实麦克风需在有图形界面的浏览器里人工确认。
````

替换为：

````markdown
右侧气泡文本随流式事件增长。真实麦克风需在有图形界面的浏览器里人工确认。

**摄像头观察（可选）**：页面多了 `camera-observe.js`、`camera-metrics.js` 两个文件，打点资源在 `web/vendor/mediapipe/`
（先跑 `15_setup_camera_assets.sh`；没有它时开关显示"摄像头观察不可用"，问诊不受影响）。本机冒烟（不连 Spark，无头 Chrome + 假摄像头）：
`node apps/multimodal/web/tests/smoke-camera.mjs`；端到端：`node apps/multimodal/web/tests/smoke-e2e.mjs`。
````

第 5 处 · `apps/multimodal/deploy/livetalking/README.md`

查找：

````markdown
- 原始录音依然不落盘，这里只有文字（与第 13 节的隐私约束一致）。
````

替换为：

````markdown
- 原始录音依然不落盘，这里只有文字（与第 13 节的隐私约束一致）。
- **唯一的写接口** `POST /api/observe/<会话>`：患者页摄像头观察每 2 秒一批关键点数值，整批校验（请求体 ≤ 64 KB、≤ 50 帧、
  字段白名单、数值有限、会话编号 `[A-Za-z0-9_-]{8,64}`），时间换成服务器时间后追加写 `$DOCTOR_OBS_DIR/<会话>.frames.jsonl`
  （单文件 ≤ 20 MB，超过返回 413），`DOCTOR_OBSERVE=0` 关闭；`/highlights` 同时返回阶段三生成的 `observe_segments`、
  `observe_medians`、`camera`、`observe_ready`，`/health` 多了 `obs_dir`、`obs_dir_exists`、`observe_enabled`。
````

`apps/emotion/deploy/README.md`

查找：

````markdown
- 只用本地模型；日志只有会话编号前 8 位和命中数：`journalctl --user -u emotion-judge-watch -f`。
````

替换为：

````markdown
- 只用本地模型；日志只有会话编号前 8 位和命中数：`journalctl --user -u emotion-judge-watch -f`。
- 同一个服务还做**同期观察**：患者开了摄像头观察的会话（`EMOTION_OBS_DIR`，默认 `~/livetalking-logs/observations/<会话>.frames.jsonl`，
  由阶段二医生端服务写入，与阶段二 `env.sh` 的 `DOCTOR_OBS_DIR` 必须相同），结束后先用 `face_body/live.py` 生成
  `outputs/judge/consult/<会话>.observe.json`——只算数值，不用大模型、不等模型空闲；frames 或问诊记录更新了会重算；
  出错只记异常类名，不影响 judge。
````

- [ ] **Step 7: 仓库状态说明里的旧说法**

第 1 处 · `AGENTS.md`

查找：

````markdown
face_body 目前离线处理视频。部署见
````

替换为：

````markdown
face_body 既离线处理视频，也在问诊结束后统计患者页可选摄像头观察的关键点数值（`live.py`，给医生工作台「对话记录」「重点」的同期观察）。部署见
````

第 2 处 · `apps/emotion/README.md`

查找：

````markdown
目前离线处理视频文件，尚未接入实时问诊；
````

替换为：

````markdown
既离线处理视频文件，也统计患者页可选「摄像头观察」上传的关键点数值（`live.py`，问诊结束后按每条回答切段）；
````

第 3 处 · `docs/architecture/overview.md`

查找：

````markdown
`face_body/` 用 MediaPipe 离线处理视频。
````

替换为：

````markdown
`face_body/` 用 MediaPipe 离线处理视频，并在问诊结束后统计患者页可选摄像头观察的关键点数值（浏览器端打点，画面不出浏览器），给医生工作台的同期观察。
````

第 4 处 · `docs/product.md`

查找：

````markdown
面部与身体观察 `face_body/` 目前离线处理视频文件。
````

替换为：

````markdown
面部与身体观察 `face_body/` 离线处理视频文件，也统计患者页可选摄像头观察的关键点数值（问诊结束后给医生工作台逐条回答的同期观察）。
````

- [ ] **Step 8: 公开安全检查与一致性检查**

Run（Git Bash）：
```bash
git fetch origin main
git diff --name-only origin/main...HEAD            # 本 PR 会带上的全部文件（含手册、spec、计划）
git diff --name-only origin/main...HEAD | grep -v 'docs/superpowers/plans/2026-09-29-live-camera-observation.md' \
  | xargs grep -nE '[A-Za-z]:[\\/]Users|/home/[a-z]|192\.168\.|10\.[0-9]+\.[0-9]+\.[0-9]+|qq\.com|BEGIN [A-Z ]*PRIVATE KEY' || echo "公开安全检查：没有命中"
# （计划文件本身含这条检查的正则，排除在外。）再用会话私有记忆 public-repo-snapshot 里的敏感词清单对同一批文件跑一遍——
# 那份清单本身含主机、端口等信息，只在本机用，绝不写进仓库、提交说明或 PR。
git ls-files apps/multimodal/web/vendor | wc -l
grep -rn "尚未接入实时问诊\|不采集摄像头画面\|目前离线处理视频\|未接，现在是离线" --include=*.md . | grep -v "docs/superpowers" || echo "旧说法已清理"
```
Expected: 文件列表里没有 `vendor/`；`公开安全检查：没有命中`；`0`；`旧说法已清理`。有命中就改掉再跑。

- [ ] **Step 9: Commit**

```bash
git add README.md AGENTS.md docs/safety-and-privacy.md docs/实机测试操作手册.md docs/architecture/overview.md docs/product.md THIRD_PARTY_NOTICES.md apps/emotion/README.md apps/emotion/face_body/README.md apps/multimodal/README.md apps/multimodal/deploy/livetalking/README.md apps/emotion/deploy/README.md
git commit -m "docs(camera): 实时摄像头观察的说明、隐私边界、实机测试步骤与第三方声明 (#8)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: 推送、部署到 Spark、实机核对、PR

**所有远程动作（`git push`、SSH / SFTP 到 Spark、重启服务、`gh pr create`、合并）都要先请用户批准。** 连接方式与凭据按会话私有记忆里的 Spark 访问说明（`spark-machine-access`）：凭据只从本机文件读、不打印、不写进任何文件或日志；不要打开或引用 `localfile/` 的内容到仓库里。Spark 是多人共用的机器：动服务前先看有没有人在问诊。

**Files:** 无代码改动（只部署与核对）。

**Interfaces:**
- Consumes：Task 1–10 的全部提交；Spark 上的 `~/livetalking-deploy/`（阶段二平铺部署目录，含 `web/` 与本机的 `env.local.sh`）、`~/LiveTalking/`（`$APP_DIR`）、`~/spark-Hackson/`（阶段三）、`~/emotion-models/mediapipe/`。
- Produces：Spark 上跑着新版 doctor_service、患者页、vendor 资源与 `emotion-judge-watch`；一个指向 `main` 的 PR。

- [ ] **Step 1: 推送分支（需批准）**

Run: `git push origin feat/live-camera-observation`
Expected: 推送成功，`git status` 显示与 `origin/feat/live-camera-observation` 一致。

- [ ] **Step 2: 打阶段二部署包（LF 行尾，只取已提交内容）**

Run（Git Bash，仓库根目录）：
```bash
stage="$(mktemp -d)"
git -c core.autocrlf=false archive HEAD apps/multimodal/deploy/livetalking apps/multimodal/web | tar -x -C "$stage"
grep -rlI $'\r' "$stage" && echo "!! 有 CRLF，停下排查" || echo "LF OK"
ls "$stage/apps/multimodal/deploy/livetalking" "$stage/apps/multimodal/web"
```
Expected: `LF OK`；两个目录里能看到 `15_setup_camera_assets.sh`、`doctor_service.py`、`camera-observe.js`、`camera-metrics.js`；**没有** `vendor/`。

要上传的文件（Spark 上是平铺布局）：

| 本地（`$stage/…`） | Spark 目标 |
|---|---|
| `apps/multimodal/deploy/livetalking/doctor_service.py`、`env.sh`、`13_deploy_web.sh`、`14_setup_doctor_console.sh`、`15_setup_camera_assets.sh`、`README.md` | `~/livetalking-deploy/` |
| `apps/multimodal/web/triage.html`、`triage.css`、`triage.js`、`mic-asr.js`、`camera-metrics.js`、`camera-observe.js`、`doctor.html`、`doctor.css`、`doctor.js` | `~/livetalking-deploy/web/` |

不上传 `tests/`、`patches/`（本次没改）；**不覆盖** `~/livetalking-deploy/env.local.sh`。上传后 `chmod +x ~/livetalking-deploy/15_setup_camera_assets.sh`。

- [ ] **Step 3: 上传前检查有没有人在问诊（需批准 SSH）**

在 Spark 上：`curl -s --noproxy '*' http://127.0.0.1:8010/api/admin/sessions`
Expected: `sessions` 为空。不为空就告诉用户、等对方结束（14 号脚本会重启医生端服务，阶段三部署会重启 `emotion-judge-watch`；LiveTalking 本身**不需要重启**）。

- [ ] **Step 4: 上传并在 Spark 上跑 15 → 13 → 14（需批准）**

先 `cat ~/livetalking-deploy/DEPLOYED_REF` 看记录格式，上传 Step 2 的文件后：
```bash
cd ~/livetalking-deploy
bash 15_setup_camera_assets.sh
bash 13_deploy_web.sh
bash 14_setup_doctor_console.sh
```
Expected：
- 15：`[1/4]` 装好 1.0.1（镜像不通会自动改走官方源 + PROXY；两条都不通时，在开发机 `npm pack @mediapipe/tasks-vision@1.0.1` 后把 tgz 传上去，`CAM_ASSETS_TGZ=<tgz 路径> bash 15_setup_camera_assets.sh`）；`[2/4]` 两个 `OK`；`[3/4]` 四个 `HTTP 200`，并打印两行 Content-Type（`.wasm` 不是 `application/wasm` 也能用，记下来即可）；
- 13：文件列表含 `camera-metrics.js`、`camera-observe.js`，自检 `OK   asr/recorder-core.js`、`OK   asr/pcm.js`、`OK   vendor/mediapipe（摄像头观察，版本 1.0.1）`；
- 14：`[3/5]` 提到观察目录，`/health HTTP 200`（返回内容含本机路径，只看不外传：有 `"obs_dir"`、`"obs_dir_exists": true`、`"observe_enabled": true`）。
然后按原格式更新 `~/livetalking-deploy/DEPLOYED_REF`（本次提交号、时间、分支 `feat/live-camera-observation`）。

- [ ] **Step 5: 部署阶段三（需批准）**

用以往阶段三的方式：能免密 SSH 时 `SPARK_SSH="<用户>@<主机> -p <端口>" bash apps/emotion/deploy/deploy_spark.sh`；否则照它的做法手动完成——本地 `git -c core.autocrlf=false archive HEAD apps/emotion/judge apps/emotion/face_body apps/emotion/deploy` 打包、连同写好「模块 提交号 ref」三行的 `DEPLOYED_REFS.pending` 传到 `~/spark-Hackson/.incoming/`，在 Spark 上 `bash ~/spark-Hackson/.incoming/apps/emotion/deploy/setup_spark.sh --install-from ~/spark-Hackson/.incoming`。
Expected: `[3/6]` 打印 `judge      88 passed …`、`face_body  62 passed …`；`[6/6]` `emotion-judge-watch` 在线；`journalctl --user -u emotion-judge-watch -n 5` 的启动行末尾有 `同期观察读 /…/livetalking-logs/observations`。

- [ ] **Step 6: Spark 上的只读核对**

在 Spark 上：
```bash
curl -s -o /dev/null -w '%{http_code}\n' --noproxy '*' http://127.0.0.1:8010/vendor/mediapipe/vision_bundle.js
curl -s -o /dev/null -w '%{http_code}\n' --noproxy '*' -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8110/api/observe/bad
curl -s -o /dev/null -w '%{http_code}\n' --noproxy '*' -X OPTIONS -H 'Origin: http://127.0.0.1:8010' -H 'Access-Control-Request-Method: POST' -H 'Access-Control-Request-Headers: content-type' http://127.0.0.1:8110/api/observe/abcdefgh1234
stat -c '%A %n' ~/livetalking-logs/observations
```
Expected: `200`、`400`、`200`、`drwx------ …/livetalking-logs/observations`。

- [ ] **Step 7: 实机演示核对（由用户或负责人经 SSH 隧道手测，对照 spec §1 成功标准）**

按 `docs/实机测试操作手册.md` §3.1 第 9 步与 §4：
1. 打开 `http://127.0.0.1:8010/triage.html`，开始问诊，打开摄像头观察：小窗有打点；前 5 秒「正在建立本人基线…」，之后面板数值随转头、眨眼变化；
2. 每说完一句，这句下面出现「本次回答观察：…」；
3. 点结束并确认；约半分钟内医生工作台 `http://127.0.0.1:8110/#<会话编号>` 的「对话记录」每条患者回答下有同期观察，「重点」出来后每条命中也有；再开一场不开摄像头的问诊，「对话记录」最前面只显示一次「本场未开启摄像头」；
4. 不开摄像头的问诊流程与原来完全一致。
有问题先看 `journalctl --user -u emotion-judge-watch -n 20`（只有会话编号前 8 位和类名）与 `~/livetalking-logs/doctor.log`。

- [ ] **Step 8: 开 PR（需批准；合并等用户明确同意）**

PR 从 `feat/live-camera-observation` 到 `main`。它还带着尚未合并的 `docs/test-manual` 两个提交（`c19a1ec` 实机测试操作手册、`ef6e27f` README 团队与致谢），在描述里写明。正文存成临时文件后：
```bash
gh pr create --base main --head feat/live-camera-observation --title "feat: 实时摄像头观察（最小可演示版）(#8)" --body-file <正文文件>
```
正文包括：改动摘要（患者页开关与小窗、上传接口、live.py 与 watch、医生端同期观察、15 号脚本、文档）；验证命令与结果（Task 9 Step 3 的全量回归、三个冒烟、Spark 上 Step 4–6 的输出摘要，不贴 `/health` 原文）；医疗安全与隐私影响（默认关闭、画面不出浏览器、只存数值、不出情绪标签、unknown、`DOCTOR_OBSERVE=0`、保留期限待补）；附带的两个文档提交；末尾一行 `🤖 Generated with [Claude Code](https://claude.com/claude-code)`。
合并后公开仓库**不要**自动同步——等用户明说，再按私有记忆里的公开快照流程（read-tree + 敏感词复查）。

---

## 计划自检记录（写计划时已做）

- **spec 覆盖**：§1 成功标准 1–4 → Task 6（小窗、面板、逐句）、Task 7（医生端逐条、重点、未开启）、Task 11 Step 7；§5.1 → Task 5、6；§5.2 → Task 1、8；§5.3 → Task 4；§5.4 → Task 2、3；§5.5 → Task 4、7；§5.6 → Task 10；§6 数据格式 → Task 2、4；§7 错误处理六行 → Task 6 冒烟（拒绝授权、vendor 缺失、上传失败、8110 未转发、中途关闭）与 Task 3（live.py 出错只记类名、不生成 observe，医生端显示「暂不可用」）；§8 隐私 → Global Constraints、Task 6、Task 10；§9 测试 → 各任务；§10 部署 → Task 11；§11 风险表 → 核实记录、15 号脚本自检、`CAM_ASSETS_TGZ`、一致性测试。
- **占位检查**：没有 TBD / TODO / 「类似 Task N」；每个代码步骤都有完整代码或逐字的查找替换。
- **类型一致**：`CAM_BLENDSHAPES`（live.py / doctor_service.py / camera-metrics.js，测试核对）、段字段名（live.py 输出、doctor_service `_OBS_FIELDS`、doctor.js `obsLine`、camera-metrics `summarize`）、`window.CameraObserve` 的方法名（camera-observe.js 与 triage.js 钩子、冒烟脚本）逐一对过。
- **Review Focus**：五条都有对应测试或冒烟段落（见文首）。
