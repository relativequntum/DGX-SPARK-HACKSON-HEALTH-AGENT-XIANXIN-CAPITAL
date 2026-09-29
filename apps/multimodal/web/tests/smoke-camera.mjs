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
