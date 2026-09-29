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
