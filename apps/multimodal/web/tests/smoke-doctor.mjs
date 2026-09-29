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
