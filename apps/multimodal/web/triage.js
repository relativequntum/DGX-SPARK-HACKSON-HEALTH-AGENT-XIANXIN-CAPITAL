/* ─────────────────────────────────────────────────────────────────────────
 * triage.js —— 数字人预问诊页面主逻辑
 *
 * 链路（全部在本机 DGX Spark 内）：
 *   麦克风 → /api/asr（SenseVoice，WebSocket）→ ASR 文本
 *        → POST /human {type:'chat'} → OpenClaw agent → TTS → wav2lip
 *   文本回流：GET /sse?sessionid=… ← 服务端 notify（LLM 文本 / TTS 起止）
 *
 * 后端依赖：
 *   - /offer、/human、/interrupt_talk、/api/ping、/api/turn（已在上游实现）
 *   - /sse 事件 `status:"llm_text"` / `status:"llm_done"`：需要 llm.py 补丁
 *     （见 deploy/livetalking/patches/llm.py）。缺失时右侧只显示用户发言，
 *     数字人仍然正常语音作答。
 * ───────────────────────────────────────────────────────────────────────── */
(function () {
    'use strict';

    var CFG = {
        // 开场白：直接朗读，不进入 agent 会话历史
        greeting: '您好，我是预问诊助手。接下来我会问您几个问题，帮助医生提前了解您的情况。您直接说话就好。请问您哪里不舒服？',
        // 触发 agent 输出预问诊记录的指令（由 agent 的 Skill 识别）
        endPrompt: '问诊结束，请生成预问诊记录。',
        heartbeatMs: 30000,
        listenTailMs: 700,          // 数字人说完后稍等再收音，避免尾音被录进去
        // 推理服务与视频渲染共用一块 GPU，Agent 首句常常要等十几秒。
        // 这段完全无声的等待是体感最差的地方，所以先垫一句，让对话不断线。
        fillerDelayMs: 2200,
        fillers: ['嗯，我看看。', '好的，让我想想。', '稍等，我梳理一下。'],
        iceWaitMs: 2500,
        replyTimeoutMs: 45000,      // 等一轮 chat 回复的兜底超时（llm_done 丢失时不至于卡死）
        greetingTimeoutMs: 20000,   // 开场白是 echo 播报，本身没有 llm_done（多念一句要更久）
        summaryTimeoutMs: 150000,   // 小结文本长，给足时间；需小于服务端 LLM_TIMEOUT(180s)
        demo: /[?&]demo=1/.test(window.location.search)
    };

    var PHASE_TEXT = {
        idle: '未开始',
        connecting: '连接中',
        listening: '正在聆听',
        thinking: '思考中',
        speaking: '数字人在说话',
        paused: '已暂停收音',
        error: '连接异常'
    };

    var el = {};
    var state = {
        phase: 'idle',
        sessionid: '',
        consultId: '',      // 本次问诊的固定会话 ID：断线重连后沿用，只有新一轮问诊才换新
        pc: null,
        es: null,
        heartbeat: null,
        mic: null,
        micReady: false,
        asrReady: false,
        asrCloseInfo: '',   // 上一次 ASR 通道的关闭码（clean/code=1000 为主动关闭，dirty/1006 多为网络中断）
        retryTimer: null,   // 自动重连定时器
        retryCount: 0,      // 已自动重连次数（连续失败到上限后改为手动）
        micEpoch: 0,        // 会话代际：重连后旧实例的异步回调一律忽略，避免重连被重复触发
        turn: 0,
        speakingDepth: 0,
        // 正在等待数字人这一轮响应结束：'chat' 等 llm_done，'echo' 等最后一段语音结束
        waitingKind: null,
        watchdogTimer: null,
        llmBubble: null,
        // 回复正文的“同步显示”：LLM 生成完比数字人真正开口早好几秒（还要合成语音 + 排队渲染），
        // 直接显示就会出现“字念完了、数字人还在说上一句”。这里先攒着，等语音段开始播再逐段显示。
        replyText: '',        // 本轮已生成但还没播出去的正文
        replyShown: 0,        // 已随语音显示的字符数
        replyBubble: null,    // 本轮助手气泡
        replyTurn: -1,        // 气泡属于哪一轮：轮次变了才另起新气泡
        replyFlushTimer: null,
        replyTailTimer: null,
        replySafeTimer: null,
        fillerTimer: null,
        fillerText: '',
        fillerPlaying: false,   // 垫词已发出、还没开口
        fillerPending: false,   // 垫词正在播（等它播完再恢复常态）
        segLast: false,       // 当前这段是不是本轮最后一段（服务端 _seg_last）
        replyDone: false,     // 本轮 LLM 是否已生成完毕（llm_done）——没生成完就不能收尾，否则正文会被截断
        summary: null,        // {card, body, pending}
        summaryRenderTimer: null,
        userPaused: false,
        active: false,
        turnPending: false,
        resumeTimer: null,
        summaryTimer: null,
        ended: false        // 本次问诊已收尾：此后不再自动重连，免得数字人自己又冒出来
    };

    /* ── 工具 ─────────────────────────────────────────────────────────── */

    function $(id) { return document.getElementById(id); }

    function esc(text) {
        return String(text)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    /**
     * 问诊会话 ID：一次问诊固定一个，WebRTC/ASR 断线重连后继续沿用。
     * 服务端用它做 LiveTalking 会话键、OpenClaw agent 会话键和医生端记录文件名——
     * 不固定的话，每次重连都会拆出新会话：医生端记录碎成多条，agent 上下文也丢了。
     * 格式约束与服务端校验一致：[A-Za-z0-9_-]{8,64}。
     */
    function newConsultId() {
        var id = '';
        if (window.crypto && window.crypto.randomUUID) { id = window.crypto.randomUUID(); }
        else {
            id = 'consult-' + String(Date.now()) + '-';
            var abc = 'abcdefghijklmnopqrstuvwxyz0123456789';
            for (var i = 0; i < 12; i += 1) { id += abc[Math.floor(Math.random() * abc.length)]; }
        }
        return id.replace(/[^A-Za-z0-9_-]/g, '').slice(0, 64);
    }

    /** 极简 Markdown 渲染（先转义再替换，避免 XSS）。 */
    function renderRich(text) {
        return esc(text)
            .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
            .replace(/^#{1,6}\s*(.+)$/gm, '<span class="md-h">$1</span>')
            .replace(/^\s*[-*·]\s+(.+)$/gm, '<span class="md-li">$1</span>');
    }

    function showToast(msg, kind, ms) {
        if (!el.toast) { return; }
        el.toast.textContent = msg;
        el.toast.dataset.kind = kind || 'warn';
        el.toast.hidden = false;
        clearTimeout(el.toast._timer);
        el.toast._timer = setTimeout(function () { el.toast.hidden = true; }, ms || 4200);
    }

    /** 进入“等待数字人这一轮响应”的状态；超时兜底避免 llm_done 丢失时永久卡住。 */
    function waitForReply(kind, timeoutMs) {
        state.waitingKind = kind;
        clearTimeout(state.watchdogTimer);
        state.watchdogTimer = setTimeout(function () {
            if (!state.waitingKind) { return; }
            state.waitingKind = null;
            showToast('未收到本轮完整回复，已恢复收音', 'warn', 6000);
            maybeResumeListening();
        }, timeoutMs || CFG.replyTimeoutMs);
    }

    /** 本轮响应已结束（收到 llm_done / 语音播完 / 被打断）。 */
    function replySettled() {
        state.waitingKind = null;
        clearTimeout(state.watchdogTimer);
        state.watchdogTimer = null;
    }

    function setPhase(phase, detail) {
        state.phase = phase;
        if (el.phaseBadge) { el.phaseBadge.dataset.phase = phase; }
        if (el.phaseText) { el.phaseText.textContent = PHASE_TEXT[phase] || phase; }
        if (el.micBtn) { el.micBtn.dataset.state = phase; }
        if (el.micSub && detail) { el.micSub.textContent = detail; }
        if (el.micTitle) { el.micTitle.textContent = micTitleFor(phase); }
        if (el.micBtnLabel) { el.micBtnLabel.textContent = micLabelFor(phase); }
    }

    function micTitleFor(phase) {
        switch (phase) {
            case 'listening': return '正在聆听，请说话';
            case 'thinking': return '正在处理';
            case 'speaking': return '数字人正在回答';
            case 'paused': return '已暂停收音';
            case 'connecting': return '正在连接';
            case 'error': return '连接异常';
            default: return '麦克风未开启';
        }
    }

    function micLabelFor(phase) {
        switch (phase) {
            case 'listening': return '暂停';
            case 'paused': return '继续';
            case 'idle': return '开始问诊';
            default: return '语音中';
        }
    }

    function setConn(text, kind) {
        if (!el.connPill) { return; }
        el.connPill.textContent = text;
        el.connPill.dataset.state = kind || 'off';
    }

    function setMeta(text) {
        if (el.chatMeta) { el.chatMeta.textContent = text; }
    }

    function setLevel(level, active) {
        if (!el.levelBar) { return; }
        var pct = active ? Math.min(100, Math.max(0, level * 1.6)) : 0;
        el.levelBar.style.width = pct + '%';
        // 显示实时电平数值：超过判定阈值才算“有效说话”，排查麦克风时看它最直接
        if (el.levelNum) {
            var lv = Math.round(level);
            var th = state.mic ? Math.round(Math.max(state.mic.cfg.minLevel, state.mic._noiseFloor * state.mic.cfg.noiseRatio)) : 4;
            el.levelNum.textContent = '电平 ' + lv + ' / 阈值 ' + th;
            el.levelNum.classList.toggle('is-live', !!active && lv > 0);
            el.levelNum.classList.toggle('is-voice', !!active && level > th);
        }
    }

    function scrollChat() {
        if (el.chatList) { el.chatList.scrollTop = el.chatList.scrollHeight; }
    }

    /* ── 对话渲染 ─────────────────────────────────────────────────────── */

    function addSystemMessage(text) {
        var node = document.createElement('div');
        node.className = 'msg-system';
        node.textContent = text;
        el.chatList.appendChild(node);
        scrollChat();
        return node;
    }

    function addUserMessage(text, source) {
        var wrap = document.createElement('div');
        wrap.className = 'msg msg-user';
        wrap.innerHTML =
            '<div class="msg-head"><span class="msg-tag">' + (source === 'voice' ? '语音' : '文字') + '</span></div>' +
            '<div class="msg-bubble"></div>';
        wrap.querySelector('.msg-bubble').textContent = text;
        el.chatList.appendChild(wrap);
        scrollChat();
    }

    function addAssistantMessage(text) {
        var wrap = document.createElement('div');
        wrap.className = 'msg msg-assistant';
        wrap.innerHTML = '<div class="msg-head"><span class="msg-tag">数字人</span></div><div class="msg-bubble"></div>';
        wrap.querySelector('.msg-bubble').textContent = text || '';
        el.chatList.appendChild(wrap);
        scrollChat();
        return wrap.querySelector('.msg-bubble');
    }

    /* ── WebRTC ───────────────────────────────────────────────────────── */

    function fetchTurnCreds() {
        return fetch('/api/turn', { cache: 'no-store' })
            .then(function (r) { return r.json(); })
            .then(function (j) {
                if (j && j.code === 0 && j.data && j.data.iceServers && j.data.iceServers.length) { return j.data; }
                return null;
            })
            .catch(function () { return null; });
    }

    function waitIceGathering(pc) {
        return new Promise(function (resolve) {
            if (pc.iceGatheringState === 'complete') { resolve(); return; }
            var timer = setTimeout(resolve, CFG.iceWaitMs);
            var check = function () {
                if (pc.iceGatheringState === 'complete') {
                    clearTimeout(timer);
                    pc.removeEventListener('icegatheringstatechange', check);
                    resolve();
                }
            };
            pc.addEventListener('icegatheringstatechange', check);
        });
    }

    function connectWebRTC() {
        return fetchTurnCreds().then(function (turn) {
            var cfg = { sdpSemantics: 'unified-plan' };
            if (turn) {
                // 公网只放通 TCP 时，必须无条件走 TURN 中继
                cfg.iceServers = turn.iceServers;
                cfg.iceTransportPolicy = 'relay';
            }
            var pc = new RTCPeerConnection(cfg);
            state.pc = pc;

            pc.addEventListener('track', function (evt) {
                if (evt.track.kind === 'video') {
                    el.video.srcObject = evt.streams[0];
                } else {
                    el.audio.srcObject = evt.streams[0];
                }
            });
            pc.addEventListener('iceconnectionstatechange', function () {
                if (state.pc !== pc) { return; }   // 已被重连替换的旧连接，忽略
                var s = pc.iceConnectionState;
                if (s === 'failed' || s === 'disconnected' || s === 'closed') {
                    setConn('连接中断', 'error');
                    scheduleAutoReconnect();
                } else if (s === 'connected') {
                    state.retryCount = 0;
                    setConn('已连接', 'on');
                    setTimeout(function () { if (state.pc === pc) { checkMediaPath(pc); } }, 2500);
                }
            });

            pc.addTransceiver('video', { direction: 'recvonly' });
            pc.addTransceiver('audio', { direction: 'recvonly' });

            return pc.createOffer()
                .then(function (offer) { return pc.setLocalDescription(offer); })
                .then(function () { return waitIceGathering(pc); })
                .then(function () {
                    return fetch('/offer', {
                        // 带上固定会话 ID：服务端会用它建会话（需 07 补丁支持，
                        // 旧版服务端会忽略此字段并返回随机 ID，行为退回原样但不会出错）
                        body: JSON.stringify({
                            sdp: pc.localDescription.sdp,
                            type: pc.localDescription.type,
                            sessionid: state.consultId
                        }),
                        headers: { 'Content-Type': 'application/json' },
                        method: 'POST'
                    });
                })
                .then(function (r) { return r.json(); })
                .then(function (answer) {
                    state.sessionid = String(answer.sessionid || state.consultId);
                    return pc.setRemoteDescription(answer);
                })
                .then(function () {
                    startHeartbeat(state.sessionid);
                });
        });
    }

    function startHeartbeat(sessionid) {
        stopHeartbeat();
        state.heartbeat = setInterval(function () {
            fetch('/api/ping?sessionid=' + encodeURIComponent(sessionid)).catch(function () { /* 忽略 */ });
        }, CFG.heartbeatMs);
    }

    function stopHeartbeat() {
        if (state.heartbeat) { clearInterval(state.heartbeat); state.heartbeat = null; }
    }

    /* ── SSE：服务端事件（LLM 文本、TTS 起止）───────────────────────── */

    /**
     * 连通后自检媒体通道是不是走了 TURN 中继。
     * 直连（host/srflx）在跨网环境下往往“连得上但很快断”，因为保活包到不了对端；
     * 没有中继时给用户明确提示（最常见原因：SSH 隧道只转发了 8010，没转发 3478）。
     */
    function checkMediaPath(pc) {
        if (!pc || !pc.getStats) { return; }
        pc.getStats().then(function (st) {
            var detail = '未知', relayed = false;
            st.forEach(function (r) {
                if (r.type !== 'candidate-pair') { return; }
                if (!r.nominated && r.state !== 'succeeded') { return; }
                var l = st.get(r.localCandidateId);
                var rm = st.get(r.remoteCandidateId);
                relayed = !!(l && l.candidateType === 'relay');
                detail = (l ? l.candidateType + '/' + (l.protocol || '?') : '?')
                    + ' → ' + (rm ? rm.candidateType + '/' + (rm.protocol || '?') : '?');
            });
            state.mediaPath = (relayed ? '中继 ' : '直连 ') + detail;
            if (!relayed) {
                showToast('媒体通道没走中继（' + detail + '），这种直连通常会几十秒后掉线。'
                    + '走 SSH 隧道访问时请同时转发 3478：ssh -L 8010:127.0.0.1:8010 -L 3478:127.0.0.1:3478',
                    'warn', 9000);
            }
        }).catch(function () { /* 统计不可用就跳过 */ });
    }

    function openSSE() {
        if (state.es) { state.es.close(); }
        var es = new EventSource('/sse?sessionid=' + encodeURIComponent(state.sessionid));
        state.es = es;
        es.onmessage = function (ev) {
            var data;
            try { data = JSON.parse(ev.data); } catch (e) { return; }
            handleServerEvent(data);
        };
        es.onerror = function () { /* 浏览器会自动重连；会话被回收时重连也静默失败 */ };
    }

    function handleServerEvent(ev) {
        if (!ev || typeof ev !== 'object') { return; }
        switch (ev.status) {
            case 'llm_text':
                onLLMText(String(ev.text || ''));
                break;
            case 'llm_done':
                onLLMDone();
                break;
            case 'start':
                onSpeechSegmentStart(ev.text, ev);
                break;
            case 'end':
                onSpeechSegmentEnd();
                break;
            default:
                break;   // 其它事件（任务、自定义动作）与对话无关
        }
    }

    function onLLMText(text) {
        // 模型偶尔会把提示词模板标记（{{SKILL:START}} 之类）带进正文，患者不该看到
        text = String(text || '').replace(/\{\{[A-Z_]+:[^}]*\}\}/g, '');
        if (!text) { return; }
        if (state.summary && state.summary.pending) {
            state.summary.text += text;
            // 不能每个字都重渲染整篇：小结几百字 × 上百次 token 会把主线程卡死
            scheduleSummaryRender();
            return;
        }
        // 正文不在这里显示：要等这段语音真正开始播（start 事件）时才出现，见 speakSegment()
        cancelFiller();     // 模型已经吐字了，不必再垫词
        state.replyText += text;
        if (state.phase !== 'speaking') { setPhase('thinking', '正在组织回答…'); }
    }

    /**
     * 小结原文是 agent 输出的一整篇 Markdown，里面同时有「医生参考版」和「患者核对版」。
     * 患者只需要核对自己的那一段，医生版不该出现在对话里，所以按标题拆开。
     */
    function splitSummary(text) {
        var lines = String(text || '').split('\n');
        var cur = 'pre';
        var doctor = [];
        var patient = [];
        for (var i = 0; i < lines.length; i += 1) {
            var line = lines[i];
            if (/^\s*#{1,6}\s*患者核对版/.test(line)) { cur = 'patient'; continue; }
            if (/^\s*#{1,6}\s*医生(参考|版)/.test(line)) { cur = 'doctor'; continue; }
            // 「保存位置」那一行（可能带 Markdown 加粗、也可能只是纯文本）开始就不再属于患者版
            if (/^\s*#{1,6}\s+\S/.test(line) || /^\s*\*{0,2}\s*保存位置\s*[:：]/.test(line)) { cur = 'other'; }
            if (cur === 'patient') { patient.push(line); }
            else if (cur === 'doctor') { doctor.push(line); }
        }
        return { doctor: doctor.join('\n').trim(), patient: patient.join('\n').trim() };
    }

    /** 小结流式渲染节流：攒 200ms 的增量再整体渲染一次。只渲染患者核对版。 */
    function scheduleSummaryRender() {
        if (state.summaryRenderTimer) { return; }
        state.summaryRenderTimer = setTimeout(function () {
            state.summaryRenderTimer = null;
            if (!state.summary || !state.summary.pending) { return; }
            var patient = splitSummary(state.summary.text).patient;
            // 患者版还没生成到就先保持"整理中"的提示，避免把医生版闪出来
            if (!patient) { return; }
            state.summary.body.innerHTML = renderRich(patient);
            state.summary.body.scrollTop = state.summary.body.scrollHeight;
        }, 200);
    }

    /**
     * 等待期的垫词。链路特殊性：推理服务和视频渲染抢同一块 GPU，Agent 首句
     * 经常要等十几秒才出来——这段时间数字人完全不吭声，用户会以为卡住了。
     * 所以超过阈值先垫一句，真正的回答随后接上。
     */
    function armFiller() {
        clearTimeout(state.fillerTimer);
        state.fillerTimer = null;
        state.fillerText = CFG.fillers[Math.floor(Math.random() * CFG.fillers.length)];
        state.fillerTimer = setTimeout(function () {
            state.fillerTimer = null;
            if (!state.active || !state.sessionid || state.waitingKind !== 'chat') { return; }
            if (state.speakingDepth > 0 || state.fillerPlaying || state.fillerPending) { return; }
            state.fillerPlaying = true;
            fetch('/human', {
                body: JSON.stringify({ text: state.fillerText, type: 'echo', sessionid: state.sessionid }),
                headers: { 'Content-Type': 'application/json' },
                method: 'POST'
            }).catch(function () { state.fillerPlaying = false; });   // 垫词失败就当没发生
        }, CFG.fillerDelayMs);
    }

    /** 真实回复已经到了（或开启新一轮）：取消还没触发的垫词；已经在播的让它说完。 */
    function cancelFiller() {
        clearTimeout(state.fillerTimer);
        state.fillerTimer = null;
    }

    /**
     * 数字人开口说这一段的时刻：把本轮已收到的正文一次性整段显示出来。
     * 不再逐段追语音——那样文字会被切成碎片往外蹦，且与口型对不齐（播报文本经服务端清洗过）。
     */
    function speakSegment(text) {
        if (!text) { return; }
        if (state.summary && state.summary.pending) { return; }   // 小结有独立卡片，不重复显示
        if (!state.replyBubble || state.replyTurn !== state.turn) {
            state.replyBubble = addAssistantMessage('');
            state.replyBubble.classList.add('is-streaming');
            state.replyTurn = state.turn;
        }
        // 整篇覆盖而不是追加：LLM 可能还在流式生成，后面几段开口时会刷新成最新全文
        state.replyBubble.textContent = state.replyText;
        state.replyShown = state.replyText.length;
        scrollChat();
    }

    /**
     * 收尾本轮文字：把"已生成但没随语音播出去"的部分补进气泡，保证正文不丢。
     * 常见场景：回复超过单轮朗读字数（只念了前一部分）、TTS 没出声、被打断。
     */
    function flushReplyTail(force) {
        clearTimeout(state.replyFlushTimer);
        clearTimeout(state.replyTailTimer);
        clearTimeout(state.replySafeTimer);
        state.replyFlushTimer = null;
        var bubble = state.replyBubble;
        // 用完整正文覆盖：播报文本被服务端清洗过（去 markdown/emoji、换行变空格），
        // 和原始正文逐字对不上，按片段追加必然重复或错位；整篇覆盖既能补齐又不会重复。
        if (state.replyText && (force || state.speakingDepth === 0)) {
            if (!bubble || state.replyTurn !== state.turn) {
                bubble = addAssistantMessage('');
                bubble.classList.add('is-streaming');
                state.replyBubble = bubble;
                state.replyTurn = state.turn;
            }
            bubble.textContent = state.replyText;
            scrollChat();
        }
        if (bubble) { bubble.classList.remove('is-streaming'); }
        if (force) {
            // 只有本轮真的结束（新一轮开始 / 被打断）才清空缓冲。
            // 不清空的原因：长回复要先合成完才开口，兜底若提前清空，开口时就没内容可显示了。
            state.replyText = '';
            state.replyShown = 0;
        } else {
            state.replyShown = state.replyText.length;
        }
        // 不清空 replyBubble：一轮回答常切成多段播报，后续段落要往同一个气泡里追加。
        // 新一轮开始时由 onUserText 负责另起气泡。
        state.replyDone = false;
    }

    /**
     * 一轮回答常被切成多段播报，段与段之间 speakingDepth 会瞬时归零，
     * 而段间间隔取决于 TTS 合成速度（可能好几秒），靠固定时间防抖必然误判。
     * 所以只在"服务端标出的最后一段播完"后才收尾，避免后续段落被重复写进气泡。
     */
    function maybeFlushReply(delay) {
        clearTimeout(state.replyFlushTimer);
        state.replyFlushTimer = setTimeout(function () {
            state.replyFlushTimer = null;
            if (state.speakingDepth === 0 && (state.replyDone || state.waitingKind === 'echo')) {
                flushReplyTail();
            }
        }, delay || 800);
    }

    function onLLMDone() {
        replySettled();
        state.replyDone = true;
        // 兜底一：llm_done 后迟迟没有语音播出（TTS 失败/被静音），6s 后补上正文
        clearTimeout(state.replyTailTimer);
        state.replyTailTimer = setTimeout(function () {
            if (state.replyShown === 0) { flushReplyTail(); }
        }, 6000);
        // 兜底二：万一最后一段的标记没到（旧服务端/TTS 换路径），12s 后无条件收尾。
        // 收尾后正文缓冲已清空，重复调用没有副作用。
        clearTimeout(state.replySafeTimer);
        state.replySafeTimer = setTimeout(function () { flushReplyTail(); }, 12000);
        if (state.summary && state.summary.pending) {
            completeSummary();
            return;
        }
        maybeResumeListening();
    }

    function onSpeechSegmentStart(text, ev) {
        state.speakingDepth += 1;
        state.segLast = !!(ev && ev._seg_last);   // 服务端标出：这是本轮最后一段
        stopListening(false);
        setPhase('speaking', '数字人正在回答…');
        // 垫词只是"还在为您处理"的信号，不是问诊内容：不写进对话气泡
        if (state.fillerPlaying && text === state.fillerText) {
            state.fillerPlaying = false;
            state.fillerPending = true;
            return;
        }
        speakSegment(text);
        if (el.caption && text) {
            el.caption.textContent = text;
            el.caption.hidden = false;
        }
    }

    function onSpeechSegmentEnd() {
        state.speakingDepth = Math.max(0, state.speakingDepth - 1);
        if (state.fillerPending) { state.fillerPending = false; }
        if (state.speakingDepth === 0) {
            // 只有最后一段播完才收尾；echo 播报没有分段标记，按轮次结束处理
            if (state.segLast || state.waitingKind === 'echo') {
                maybeFlushReply(800);   // 把没播到的正文补上（例如超出朗读字数的尾部）
            }
            // echo 类播报（开场白/固定话术）没有 llm_done，语音播完即视为本轮结束
            if (state.waitingKind === 'echo') { replySettled(); }
            if (el.caption) { setTimeout(function () { el.caption.hidden = true; }, 900); }
            maybeResumeListening();
        }
    }

    /* ── 语音交互循环 ─────────────────────────────────────────────────── */

    function createMicDelegates(epoch) {
        return {
            asrUrl: (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/api/asr',
            onLevel: setLevel,
            onAsrState: function (s) {
                state.asrReady = (s === 'ready');
                // ASR 通道断开时服务端会连坐拆掉数字人会话，所以走整会话重建。
                // 只认当前这一代实例：旧实例的异步 onclose 不该再触发重连。
                if (s === 'closed' && state.active && state.micEpoch === epoch) { scheduleAutoReconnect(); }
            },
            onAsrClose: function (code, reason, clean) {
                state.asrCloseInfo = (clean ? 'clean' : 'dirty') + '/code=' + code;
            },
            onTurnEnd: function () { completeTurn(); },
            onBargeIn: function () { autoInterrupt(); }
        };
    }

    function beginListening(detail) {
        if (!state.active || state.userPaused) { return; }
        if (state.waitingKind || state.speakingDepth > 0) { return; }
        if (!state.micReady || !state.asrReady) { return; }
        clearTimeout(state.resumeTimer);
        state.mic.arm(true);
        state.mic.setMonitor(false);
        state.mic.startTurn();
        setPhase('listening', detail || '正在聆听，请直接说话');
        watchMicInput();
    }

    /** 开始收听后若长时间没有任何电平，提示检查授权/输入设备（自助排障用）。 */
    function watchMicInput() {
        clearTimeout(state.micInputTimer);
        state.micInputTimer = setTimeout(function () {
            if (!state.active || !state.mic || !state.mic.turnActive) { return; }
            if (state.mic._speechMs > 0) { return; }
            showToast('几乎没有检测到麦克风输入：请确认浏览器已授权麦克风，且系统选择了正确的输入设备', 'warn', 8000);
        }, 6000);
    }

    function stopListening(markPaused) {
        clearTimeout(state.resumeTimer);
        if (state.mic) {
            // 顺序重要：先决定要不要继续采集（监听），再收起收音开关，避免多余的 stop/start
            state.mic.setMonitor(!markPaused);
            state.mic.arm(false);
        }
        if (markPaused) { setPhase('paused', '已暂停收音，点击麦克风按钮继续'); }
    }

    function maybeResumeListening() {
        if (!state.active || state.userPaused || state.waitingKind) { return; }
        if (state.speakingDepth > 0) { return; }
        clearTimeout(state.resumeTimer);
        state.resumeTimer = setTimeout(function () {
            if (!state.active || state.userPaused || state.waitingKind || state.speakingDepth > 0) { return; }
            // 每轮开始前确保 ASR 连接可用（服务端重启/空闲断开时自动重连）
            state.mic.connect()
                .then(function () { beginListening('请继续，我在听'); })
                .catch(function (err) { showToast(err.message, 'error'); });
        }, CFG.listenTailMs);
    }

    function completeTurn() {
        if (state.turnPending) { return; }
        state.turnPending = true;
        var info = state.mic.turnText ? state.mic.turnText() : null;
        setPhase('thinking', '正在识别语音…');
        state.mic.endTurn()
            .then(function (text) {
                state.turnPending = false;
                if (!text) {
                    if (info && info.speechMs < 300) {
                        showToast('没有听清，请靠近麦克风再说一次');
                    } else {
                        showToast('没有识别到内容，请再说一次');
                    }
                    replySettled();
                    beginListening();
                    return;
                }
                onUserText(text, 'voice');
            })
            .catch(function (err) {
                state.turnPending = false;
                showToast('语音识别失败：' + err.message, 'error');
                beginListening();
            });
    }

    function onUserText(text, source) {
        cancelFiller();             // 新一轮开始：撤掉上一轮可能还挂着的垫词
        flushReplyTail(true);   // 新一轮开始：无条件先结掉上一轮没显示完的正文
        addUserMessage(text, source);
        state.turn += 1;
        setMeta('第 ' + state.turn + ' 轮 · ' + (source === 'voice' ? '语音' : '文字'));
        return sendChat(text, {});
    }

    function sendChat(text, opts) {
        waitForReply('chat', (opts && opts.silent) ? CFG.summaryTimeoutMs : CFG.replyTimeoutMs);
        setPhase('thinking', '数字人正在思考…');
        armFiller();   // 首句迟迟不来时先垫一句，避免长时间无回应
        var body = {
            text: text,
            type: 'chat',
            interrupt: true,
            sessionid: state.sessionid
        };
        if (opts && opts.silent) { body.tts = { silent: true }; }
        return fetch('/human', {
            body: JSON.stringify(body),
            headers: { 'Content-Type': 'application/json' },
            method: 'POST'
        }).then(function (r) { return r.json(); }).then(function (j) {
            if (!j || j.code !== 0) { throw new Error((j && j.msg) || '服务端拒绝请求'); }
            return j;
        }).catch(function (err) {
            showToast('发送失败：' + err.message, 'error');
            replySettled();
            maybeResumeListening();
            throw err;
        });
    }

    /* ── 结束问诊与小结 ───────────────────────────────────────────────── */

    function beginSummary() {
        stopListening(false);
        state.userPaused = true;

        var card = document.createElement('div');
        card.className = 'msg summary-card';
        card.innerHTML =
            '<div class="summary-card-head">' +
            '  <h3>预问诊小结</h3>' +
            '  <div class="summary-tools">' +
            '    <button type="button" data-act="expand" hidden>全屏查看</button>' +
            '    <button type="button" data-act="copy" hidden>复制</button>' +
            '  </div>' +
            '</div>' +
            '<div class="summary-body"><span class="summary-loading"><i></i>正在根据本次对话整理小结…</span></div>';
        el.chatList.appendChild(card);
        scrollChat();

        var body = card.querySelector('.summary-body');
        state.summary = { card: card, body: body, text: '', pending: true };

        card.querySelector('[data-act="expand"]').addEventListener('click', openSummaryModal);
        card.querySelector('[data-act="copy"]').addEventListener('click', function () {
            copyText(splitSummary(state.summary.text).patient || state.summary.text);
        });

        setPhase('thinking', '正在整理小结…');
        setConn('生成小结中', 'busy');

        sendChat(CFG.endPrompt, { silent: true }).catch(function () {
            finishSummaryFallback('小结生成失败，请点击右下角按钮重试。');
        });

        state.summaryTimer = setTimeout(function () {
            if (state.summary && state.summary.pending) {
                finishSummaryFallback('小结生成超时。可稍后在对话记录中查看，或点击按钮重试。');
            }
        }, CFG.summaryTimeoutMs);
    }

    function finishSummaryFallback(message) {
        if (!state.summary) { return; }
        completeSummary(message);
    }

    /**
     * 点「结束问诊」后立刻收起数字人：停收音、停心跳、暂停画面，左栏回到开始问诊前的遮罩。
     * 这里故意不动 WebRTC / SSE——小结还得靠这条链路回来，真正断开在 closeAvatar()。
     */
    function hideAvatarToStart() {
        state.ended = true;   // 收尾阶段链路断了也不要自动重连，否则数字人会自己回来
        stopListening(false);
        stopHeartbeat();
        if (state.mic) { try { state.mic.close(); } catch (e) { /* 忽略 */ } state.mic = null; }
        state.micReady = false;
        state.asrReady = false;
        try { if (el.video) { el.video.pause(); } } catch (e) { /* 忽略 */ }
        try { if (el.audio) { el.audio.pause(); } } catch (e) { /* 忽略 */ }
        if (el.micBtn) { el.micBtn.disabled = true; }
        if (el.chatInput) { el.chatInput.disabled = true; }
        if (el.sendBtn) { el.sendBtn.disabled = true; }
        if (el.overlay) { el.overlay.hidden = false; }
        if (el.overlayNote) { el.overlayNote.textContent = '问诊已结束，正在整理小结，请在右侧核对。'; }
        setPhase('paused', '本次问诊已结束');
    }

    /**
     * 真正结束会话：断开数字人的 WebRTC / ASR / SSE，让服务端回收会话（停止渲染与语音合成）。
     * 左栏回到开始问诊前的样子，只保留右侧对话记录与小结。
     */
    function closeAvatar() {
        stopListening(false);
        stopHeartbeat();
        clearTimeout(state.retryTimer);
        clearTimeout(state.fillerTimer);
        clearTimeout(state.watchdogTimer);
        state.retryTimer = null;
        state.fillerTimer = null;
        state.watchdogTimer = null;

        if (state.pc) { try { state.pc.close(); } catch (e) { /* 忽略 */ } state.pc = null; }
        if (el.video) { el.video.srcObject = null; }
        if (el.audio) { el.audio.srcObject = null; }
        if (state.mic) { try { state.mic.close(); } catch (e) { /* 忽略 */ } state.mic = null; }
        state.micReady = false;
        state.asrReady = false;
        if (state.es) { try { state.es.close(); } catch (e) { /* 忽略 */ } state.es = null; }

        state.active = false;
        state.speakingDepth = 0;
        // 问诊已收尾：清掉会话 ID，下次点「开始问诊」才是真正的新问诊
        state.consultId = '';
        state.waitingKind = null;

        // 会话已经断开，输入不再可用；左栏回到开始前，可以点「开始问诊」重新来一次
        if (el.chatInput) { el.chatInput.disabled = true; }
        if (el.sendBtn) { el.sendBtn.disabled = true; }
        if (el.micBtn) { el.micBtn.disabled = true; }
        if (el.startBtn) { el.startBtn.disabled = false; }
        if (el.overlay) { el.overlay.hidden = false; }
        if (el.overlayNote) { el.overlayNote.textContent = '本次问诊已结束。需要新的问诊请点击「开始问诊」。'; }
        setPhase('idle', '未开始');
        setConn('问诊已结束', 'off');
    }

    function completeSummary(fallbackMessage) {
        clearTimeout(state.summaryTimer);
        clearTimeout(state.summaryRenderTimer);
        if (!state.summary || !state.summary.pending) { return; }
        state.summary.pending = false;

        var text = state.summary.text.trim();
        // agent 偶尔会把结束指令当普通对话接（回一句追问就收尾），这种内容不能当小结给患者看
        if (!hasPatientVersion(text)) {
            failSummary(fallbackMessage);
            return;
        }

        // 对话里只给患者看自己要核对的那一段；医生参考版留在"全屏查看"里
        state.summary.body.innerHTML = renderRich(splitSummary(text).patient || text);
        showSummaryConfirm();
        var tools = state.summary.card.querySelectorAll('.summary-tools button');
        for (var i = 0; i < tools.length; i += 1) { tools[i].hidden = false; }

        replySettled();
        setConn('小结已生成', 'on');
        setPhase('paused', '本次问诊已结束');
        addSystemMessage('请核对小结内容，确认无误后本次问诊即结束。');
        el.finishBtn.disabled = true;
        scrollChat();
        // 会话这会儿还留着：患者可能要补充，点「确认无误」时才真正断开数字人
    }

    /** 真正的预问诊记录一定带「患者核对版」这一段，没有就说明这次没总结出来。 */
    function hasPatientVersion(text) {
        return /患者核对版/.test(String(text || ''));
    }

    /**
     * 小结没生成成功：不当小结展示，也不结束会话——提示重试，并把问诊恢复出来继续。
     */
    function failSummary(fallbackMessage) {
        var card = state.summary.card;
        var tip = fallbackMessage ? ('小结未生成：' + fallbackMessage) : '小结未生成，请重试。';
        state.summary.body.innerHTML = '<span class="summary-error">' + esc(tip) + '</span>';
        var tools = card.querySelectorAll('.summary-tools button');
        for (var i = 0; i < tools.length; i += 1) { tools[i].hidden = true; }
        showSummaryRetry(card);
        state.summary = null;      // 这次不算数，重试时重新建卡片

        replySettled();
        setConn('小结未生成', 'warn');
        addSystemMessage('小结未生成，本次问诊尚未结束。您可以重试生成，或继续问诊后再结束。');
        scrollChat();
        resumeConsultation();      // 没总结成功 = 还没结束，数字人与输入都恢复
    }

    /** 未生成小结时的两个出口：重新生成 / 继续问诊。 */
    function showSummaryRetry(card) {
        if (card.querySelector('.summary-confirm')) { return; }
        var bar = document.createElement('div');
        bar.className = 'summary-confirm';
        bar.innerHTML =
            '<p class="summary-confirm-tip">这次没有收到预问诊记录，问诊尚未结束。</p>' +
            '<div class="summary-confirm-actions">' +
            '  <button type="button" class="primary-btn" data-act="retry">重新生成小结</button>' +
            '  <button type="button" data-act="continue">继续问诊</button>' +
            '</div>';
        card.appendChild(bar);
        bar.querySelector('[data-act="retry"]').addEventListener('click', function () {
            card.remove();
            hideAvatarToStart();
            beginSummary();
        });
        bar.querySelector('[data-act="continue"]').addEventListener('click', function () {
            bar.remove();
            resumeConsultation();
        });
        scrollChat();
    }

    /** 把问诊恢复出来：画面、语音、输入都回到可以继续对话的状态。 */
    function resumeConsultation() {
        if (el.overlay) { el.overlay.hidden = true; }
        try { if (el.video) { el.video.play(); } } catch (e) { /* 忽略 */ }
        try { if (el.audio) { el.audio.play(); } } catch (e) { /* 忽略 */ }
        if (el.finishBtn) { el.finishBtn.disabled = false; }
        if (el.chatInput) { el.chatInput.disabled = false; }
        if (el.sendBtn) { el.sendBtn.disabled = false; }
        state.userPaused = false;
        state.ended = false;      // 恢复自动重连能力
        setPhase('listening', '请继续');
        ensureMic().then(function () {
            if (el.micBtn) { el.micBtn.disabled = false; }
            maybeResumeListening();
        }).catch(function (err) {
            showToast('麦克风恢复失败：' + err.message + '，可改用文字输入', 'warn', 6000);
        });
    }

    /** 收尾时麦克风被关掉了，要继续问诊就重新接上。 */
    function ensureMic() {
        if (state.micReady && state.asrReady) { return Promise.resolve(); }
        state.micEpoch += 1;
        state.mic = new MicASR(createMicDelegates(state.micEpoch));
        return state.mic.open().then(function () {
            state.micReady = true;
            return state.mic.connect();
        }).then(function () {
            state.asrReady = true;
        });
    }

    /** 小结出来后给患者一个核对入口：确认无误即结束，需要补充就回到对话。 */
    function showSummaryConfirm() {
        var card = state.summary.card;
        if (card.querySelector('.summary-confirm')) { return; }
        var bar = document.createElement('div');
        bar.className = 'summary-confirm';
        bar.innerHTML =
            '<p class="summary-confirm-tip">请核对以上信息是否与您的实际情况一致。确认无误即可结束本次问诊；如有出入，点「我要补充」继续说明。</p>' +
            '<div class="summary-confirm-actions">' +
            '  <button type="button" class="primary-btn" data-act="confirm">确认无误</button>' +
            '  <button type="button" data-act="amend">我要补充</button>' +
            '</div>';
        card.appendChild(bar);
        bar.querySelector('[data-act="confirm"]').addEventListener('click', confirmSummary);
        bar.querySelector('[data-act="amend"]').addEventListener('click', amendSummary);
        scrollChat();
    }

    /** 患者确认无误：收起核对区、锁定为最终版，并断开数字人结束本次问诊。 */
    function confirmSummary() {
        if (!state.summary) { return; }
        var bar = state.summary.card.querySelector('.summary-confirm');
        if (bar) { bar.remove(); }
        var head = state.summary.card.querySelector('.summary-card-head h3');
        if (head) { head.textContent = '预问诊小结（患者核对版 · 已确认）'; }
        addSystemMessage('您已确认小结无误，本次问诊结束。');
        scrollChat();
        closeAvatar();
    }

    /** 患者还要补充：恢复数字人与输入，继续问诊（会话一直保留着，可以直接接着说）。 */
    function amendSummary() {
        if (!state.summary) { return; }
        var bar = state.summary.card.querySelector('.summary-confirm');
        if (bar) { bar.remove(); }
        showToast('请补充说明，之后可再次点击「结束问诊」重新生成小结');
        resumeConsultation();
    }

    function openSummaryModal() {
        if (!state.summary) { return; }
        el.summaryModalBody.innerHTML = renderRich(state.summary.text);
        el.summaryModal.hidden = false;
    }

    function copyText(text) {
        if (!text) { return; }
        var done = function () { showToast('小结已复制到剪贴板'); };
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(done, function () { showToast('复制失败', 'error'); });
        } else {
            showToast('当前浏览器不支持自动复制', 'error');
        }
    }

    /* ── 启动 / 交互绑定 ─────────────────────────────────────────────── */

    function startSession() {
        if (state.active) { return; }
        state.active = true;
        state.ended = false;   // 新一轮开始，恢复自动重连能力
        // 断线自动重连也会走到这里：此时 consultId 已存在，保持不变，
        // 服务端才能把重连后的流量接回同一条问诊记录和同一个 agent 上下文
        if (!state.consultId) { state.consultId = newConsultId(); }
        el.startBtn.disabled = true;
        el.overlay.hidden = true;
        setConn('连接中', 'warn');
        setPhase('connecting', '正在连接数字人…');

        connectWebRTC()
            .then(function () {
                setConn('已连接', 'on');
                setPhase('connecting', '正在开启麦克风…');
                state.micEpoch += 1;
                state.mic = new MicASR(createMicDelegates(state.micEpoch));
                return state.mic.open();
            })
            .then(function () {
                state.micReady = true;
                setPhase('connecting', '正在连接语音识别…');
                return state.mic.connect();
            })
            .then(function () {
                state.asrReady = true;
                enableSessionUI();
                openSSE();
                addSystemMessage('已连接数字人，语音交互已开启');
                setMeta('等待第一轮');
                playGreeting();
            })
            .catch(function (err) {
                setPhase('error', err.message);
                setConn('连接失败', 'error');
                showToast(err.message, 'error', 8000);
                state.active = false;
                el.startBtn.disabled = false;
                el.overlay.hidden = false;
                if (el.overlayNote) { el.overlayNote.textContent = '连接失败：' + err.message; }
            });
    }

    function enableSessionUI() {
        el.micBtn.disabled = false;
        el.chatInput.disabled = false;
        el.sendBtn.disabled = false;
        el.finishBtn.disabled = false;

    }

    function playGreeting() {
        // echo 只做语音播报，不进 agent 会话历史，保证第一轮问题干净。
        // 文字不在这里直接显示：交给 start 事件（数字人真正开口时）显示，否则文字会先于语音出现。
        // 先存进 replyText，万一语音没播出来也能兜底补上。
        state.replyText = CFG.greeting;
        state.replyShown = 0;
        setPhase('thinking', '数字人正在打招呼…');
        waitForReply('echo', CFG.greetingTimeoutMs);
        fetch('/human', {
            body: JSON.stringify({ text: CFG.greeting, type: 'echo', interrupt: true, sessionid: state.sessionid }),
            headers: { 'Content-Type': 'application/json' },
            method: 'POST'
        }).catch(function () { /* 问候失败不阻塞流程 */ });
    }

    function toggleMic() {
        if (!state.active) { startSession(); return; }
        if (state.userPaused) {
            state.userPaused = false;
            beginListening('请继续，我在听');
            return;
        }
        if (state.phase === 'listening') {
            state.userPaused = true;
            stopListening(true);
            return;
        }
        if (state.phase === 'paused') {
            beginListening('请继续，我在听');
            return;
        }
        showToast('数字人正在回答，稍后可继续说话');
    }

    function sendTypedText() {
        var text = (el.chatInput.value || '').trim();
        if (!text || !state.active) { return; }
        el.chatInput.value = '';
        el.chatInput.style.height = 'auto';
        // 正在收听的这一轮作废，避免同一句话被识别两次
        if (state.mic && state.mic.turnActive) {
            state.mic.arm(false);
            state.mic.endTurn().catch(function () { /* 忽略 */ });
        }
        onUserText(text, 'text').catch(function () { /* 已提示 */ });
    }

    /** 自动打断：用户在数字人说话期间开口（mic-asr 的 onBargeIn）时调用。 */
    function autoInterrupt() {
        if (!state.active || !state.sessionid) { return; }
        if (state.speakingDepth === 0 && !state.waitingKind) { return; }
        fetch('/interrupt_talk', {
            body: JSON.stringify({ sessionid: state.sessionid }),
            headers: { 'Content-Type': 'application/json' },
            method: 'POST'
        }).then(function () {
            cancelFiller();
            state.speakingDepth = 0;
            state.fillerPlaying = false;
            state.fillerPending = false;
            replySettled();
            flushReplyTail(true);   // 被打断：立刻把完整正文显示出来，不能丢内容
            if (el.caption) { el.caption.hidden = true; }
            // 打断时正在播的那一段还会播完，它的 end 事件会再把深度加回来，
            // 所以延迟一点再归零，避免状态一直停在"正在说话"。
            setTimeout(function () {
                if (state.speakingDepth > 0) { state.speakingDepth = 0; }
                maybeResumeListening();
            }, 1800);
            // 打断后立刻接上用户正在说的这句话（mic-asr 会补上开口前的音频）
            beginListening('已打断，请继续说');
        }).catch(function () {
            beginListening('请继续说');
        });
    }

    function finishConsultation() {
        if (!state.active || !state.summaryIsIdle()) { return; }
        if (!window.confirm('结束本次预问诊并生成小结吗？')) { return; }
        hideAvatarToStart();   // 数字人立刻收起，左栏回到开始前的样子
        beginSummary();
    }

    /**
     * 自动重连。数字人的 WebRTC 或 ASR 通道一断，服务端就会把整个会话拆掉
     * （服务端日志：HumanPlayer Stopping worker thread → Connection state is closed），
     * 所以这里重建整个会话，而不是只补一条通道。
     */
    function scheduleAutoReconnect() {
        if (state.ended) { return; }   // 已结束问诊：不再自动重连
        if (!state.active || state.retryTimer) { return; }
        if (state.retryCount >= 3) {
            showToast('连接反复中断，请点击右上角「重新连接」', 'error', 8000);
            if (el.reconnectBtn) { el.reconnectBtn.hidden = false; }
            return;
        }
        state.retryCount += 1;
        showToast('与数字人的连接中断（' + (state.asrCloseInfo || '链路断开') + '），正在自动重连（第 '
            + state.retryCount + ' 次）…', 'warn', 5000);
        state.retryTimer = setTimeout(function () {
            state.retryTimer = null;
            if (!state.active) { return; }
            reconnect();
            addSystemMessage('已自动重连，正在继续本次问诊');
            startSession();
        }, 2500);
    }

    function reconnect() {
        if (el.reconnectBtn) { el.reconnectBtn.hidden = true; }
        clearTimeout(state.retryTimer);
        state.retryTimer = null;
        if (state.pc) { try { state.pc.close(); } catch (e) { /* 忽略 */ } }
        state.pc = null;
        state.active = false;
        state.userPaused = false;
        state.speakingDepth = 0;
        replySettled();
        state.micEpoch += 1;   // 作废旧实例的异步回调
        if (state.mic) { state.mic.close(); state.mic = null; }
        state.micReady = false;
        state.asrReady = false;
        stopHeartbeat();
        if (state.es) { state.es.close(); state.es = null; }
        el.startBtn.disabled = false;
        el.chatInput.disabled = true;
        el.sendBtn.disabled = true;
        el.finishBtn.disabled = true;
        el.micBtn.disabled = true;
        el.overlay.hidden = false;
        setConn('未连接', 'off');
        setPhase('idle', '点击「开始问诊」重新连接');
        addSystemMessage('已断开，可重新开始');
    }

    function bindEvents() {
        el.startBtn.addEventListener('click', startSession);
        el.micBtn.addEventListener('click', toggleMic);
        el.finishBtn.addEventListener('click', finishConsultation);
        el.sendBtn.addEventListener('click', sendTypedText);
        if (el.reconnectBtn) { el.reconnectBtn.addEventListener('click', reconnect); }
        el.summaryCloseBtn.addEventListener('click', function () { el.summaryModal.hidden = true; });
        el.summaryModal.addEventListener('click', function (ev) {
            if (ev.target === el.summaryModal) { el.summaryModal.hidden = true; }
        });
        el.chatInput.addEventListener('keydown', function (ev) {
            if (ev.key === 'Enter' && !ev.shiftKey) {
                ev.preventDefault();
                sendTypedText();
            }
        });
        el.chatInput.addEventListener('input', function () {
            el.chatInput.style.height = 'auto';
            el.chatInput.style.height = Math.min(132, el.chatInput.scrollHeight) + 'px';
        });
        window.addEventListener('beforeunload', function () {
            if (state.pc) { try { state.pc.close(); } catch (e) { /* 忽略 */ } }
            if (state.mic) { state.mic.close(); }
        });
    }

    state.summaryIsIdle = function () {
        return !state.summary || !state.summary.pending;
    };

    // 排障钩子：控制台里 __triage.state 可直接看内部状态（只读，不参与业务逻辑）
    window.__triage = { state: state, cfg: CFG };

    /* ── 设计预览（?demo=1，不连接任何后端）──────────────────────────── */

    function renderDemo() {
        el.overlay.hidden = true;
        setConn('已连接', 'on');
        setPhase('speaking', '数字人正在回答…');
        el.micBtn.disabled = false;
        el.micBtn.dataset.state = 'speaking';
        el.chatInput.disabled = false;
        el.sendBtn.disabled = false;
        el.finishBtn.disabled = false;

        el.phaseText.textContent = '数字人在说话';
        if (el.caption) { el.caption.textContent = '这个情况持续多久了？'; el.caption.hidden = false; }
        setLevel(46, true);

        addSystemMessage('已连接数字人，语音交互已开启（设计预览）');
        addAssistantMessage(CFG.greeting);
        addUserMessage('这两天胃有点胀，吃完饭更明显', 'voice');
        addAssistantMessage('明白了。请问这种胀的感觉持续多久了？');
        addUserMessage('大概三四天', 'voice');
        addAssistantMessage('好的。除了胀，还有没有反酸、烧心，或者恶心的感觉？');
        addUserMessage('偶尔有点反酸，没有恶心', 'text');
        addAssistantMessage('好的，我记下了。最近有没有服用什么药物，或者做过胃部的检查？');

        state.summary = {
            card: addSummaryPreview(),
            body: null, text: '', pending: false
        };
        state.summary.body = state.summary.card.querySelector('.summary-body');
        setMeta('第 5 轮 · 语音');
    }

    function addSummaryPreview() {
        var card = document.createElement('div');
        card.className = 'msg summary-card';
        card.innerHTML =
            '<div class="summary-card-head"><h3>预问诊小结</h3>' +
            '<div class="summary-tools"><button type="button">全屏查看</button>' +
            '<button type="button">复制</button></div></div>' +
            '<div class="summary-body"></div>';
        el.chatList.appendChild(card);
        var body = card.querySelector('.summary-body');
        body.innerHTML = renderRich([
            '主诉：上腹部胀满 3-4 天，餐后加重，偶有反酸。',
            '伴随症状：无反酸加重、无恶心呕吐、无吞咽困难、无黑便。',
            '既往与用药：（待补充）',
            '风险提示：暂无自伤/他伤及意识障碍等红旗信号；如出现剧烈腹痛、呕血或黑便请立即就医。',
            '建议医生关注：上腹不适的进食相关性、是否需要胃镜评估。'
        ].join('\n'));
        scrollChat();
        return card;
    }

    /* ── 初始化 ───────────────────────────────────────────────────────── */

    var DOM_IDS = {
        video: 'avatar-video',
        audio: 'avatar-audio',
        phaseBadge: 'phase-badge',
        phaseText: 'phase-text',
        caption: 'caption',
        toast: 'toast',
        overlay: 'overlay',
        overlayNote: 'overlay-note',
        startBtn: 'start-btn',
        micBtn: 'mic-btn',
        micBtnLabel: 'mic-btn-label',
        micTitle: 'mic-title',
        micSub: 'mic-sub',
        levelBar: 'level-bar',
        levelNum: 'level-num',
        chatList: 'chat-list',
        chatMeta: 'chat-meta',
        chatInput: 'chat-input',
        sendBtn: 'send-btn',
        finishBtn: 'finish-btn',
        summaryModal: 'summary-modal',
        summaryModalBody: 'summary-modal-body',
        summaryCloseBtn: 'summary-close-btn',
        connPill: 'conn-pill',
        reconnectBtn: 'reconnect-btn'
    };

    function init() {
        Object.keys(DOM_IDS).forEach(function (key) { el[key] = $(DOM_IDS[key]); });

        bindEvents();
        setPhase('idle', '点击「开始问诊」后自动开启语音交互');
        setMeta('等待开始');

        if (CFG.demo) { renderDemo(); }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.__triage = state;   // 便于在浏览器控制台排查
})();

/* 说明：MicASR 由 mic-asr.js 提供；本文件不依赖 jQuery。 */
