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
