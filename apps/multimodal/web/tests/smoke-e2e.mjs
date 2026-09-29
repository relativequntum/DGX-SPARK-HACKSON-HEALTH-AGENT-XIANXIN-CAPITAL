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
