/* ─────────────────────────────────────────────────────────────────────────
 * mic-asr.js —— 麦克风采集 + 自动断句（VAD）+ 本地 SenseVoice ASR
 *
 * 依赖 LiveTalking 自带的 web/asr/recorder-core.js、web/asr/pcm.js（Recorder 库）
 * 与本地 ASR WebSocket 端点 /api/asr（server/asr_server.py）。
 *
 * 协议要点（源自 server/asr_server.py）：
 *   1. 连接后先发 JSON 配置：{chunk_size, wav_name, is_speaking:true, chunk_interval, itn, mode}
 *   2. 之后发送 16kHz / 单声道 / PCM16 小端二进制切片
 *   3. 说完发 {"is_speaking": false} 触发整段识别，服务端回 {"text", "mode", "is_final":true}
 *   4. 同一条连接可重复多轮；每轮重新发一次 is_speaking:true 会重置服务端缓冲
 *
 * 自动断句只能在前端做：SenseVoice 是离线模型，服务端只在收到 is_speaking:false 时推理，
 * 不存在逐字返回的 partial 文本。
 * ───────────────────────────────────────────────────────────────────────── */
(function (global) {
    'use strict';

    var DEFAULTS = {
        sampleRate: 16000,
        chunkSamples: 960,        // 60ms @16k，与服务端 chunk_size [5,10,5] 对齐
        connectTimeoutMs: 8000,
        minSpeechMs: 300,         // 至少说了这么久才算一轮有效发言
        silenceMs: 1100,          // 静音超过这个时长判定“说完了”（按真实时钟计）
        maxTurnMs: 30000,         // 单轮最长录音时长，超时强制结束
        minLevel: 4,              // VAD 音量下限（Recorder 的 powerLevel 量纲 0-100）
        noiseFloorMin: 1.5,       // 噪声底下限：环境极安静时避免阈值趋零导致误触发
        noiseRatio: 2.5,          // 说话阈值 = 噪声底 × 该系数
        // 自动打断（用户插话）：数字人说话期间只监听不收音，检测到开口就打断
        bargeInMs: 350,           // 连续开口这么久才算插话（滤掉回声残响与短噪音）
        bargeInRatio: 3.0,        // 插话阈值 = 噪声底 × 该系数，比正常收音更严格
        bargeInCooldownMs: 1500,  // 打断后的冷却，避免一句话被反复触发
        prerollMs: 1200           // 打断发生时把开口前这段音频补进本轮，避免丢字
    };

    function MicASR(options) {
        this.cfg = Object.assign({}, DEFAULTS, options || {});
        this.asrUrl = this.cfg.asrUrl;
        this.rec = null;
        this.ws = null;
        this.opened = false;

        this.sending = false;     // 是否正在把音频推给 ASR
        this.turnActive = false;  // 当前是否处于一轮收听中
        this.listenArmed = false; // 上层是否允许收听（暂停时为 false）
        this.monitoring = false;  // 只监听不收音：数字人说话时检测用户插话
        this._recording = false;  // Recorder 是否已在采集（open 只授权，start 才出数据）

        this._buf = new Int16Array(0);
        this._speechMs = 0;
        this._silenceMs = 0;
        this._turnMs = 0;
        this._noiseFloor = 4;
        this._warmupFrames = 0;
        this._lastVoiceAt = 0;    // 最近一次判定为“有声”的真实时刻
        this._turnStartAt = 0;    // 本轮开始的真实时刻
        this._preBuf = new Int16Array(0);  // 监听期缓存的最近音频（打断时补进本轮）
        this._bargeMs = 0;        // 监听期已连续开口的时长
        this._bargeCooldownUntil = 0;

        this._resolveFinal = null;
        this._finalTimer = null;
    }

    /* ── 生命周期 ─────────────────────────────────────────────────────── */

    /** 打开麦克风（会触发浏览器授权）。必须在用户手势里调用。 */
    MicASR.prototype.open = function () {
        var self = this;
        if (this.opened) { return Promise.resolve(); }
        return new Promise(function (resolve, reject) {
            if (typeof Recorder === 'undefined') {
                reject(new Error('录音组件未加载：缺少 web/asr/recorder-core.js'));
                return;
            }
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                reject(new Error('浏览器禁止本页面使用麦克风：请改用 http://127.0.0.1:8010（SSH 隧道）或 https 访问'));
                return;
            }
            // Recorder 默认关闭回声消除/降噪，那样数字人的声音会被麦克风原样采回，
            // 自动打断必然被自己的回声误触发，所以默认打开；少数设备开启后采集音量被压得过低，
            // 可用 ?aec=0 关闭做对比（关闭后请用耳机，否则外放会自己打断自己）。
            var aec = !/(?:^|&)aec=0(?:&|$)/.test(location.search);
            self.rec = Recorder({
                type: 'pcm',
                bitRate: 16,
                sampleRate: self.cfg.sampleRate,
                audioTrackSet: {
                    echoCancellation: aec,
                    // 降噪不打开：它会削掉语音细节，实测明显压低电平，对识别有害；
                    // 打断只需要回声消除 + 自动增益。
                    noiseSuppression: false,
                    autoGainControl: true
                },
                onProcess: function (buffers, powerLevel, bufferDuration, bufferSampleRate, newBufferIdx) {
                    self._onProcess(buffers, powerLevel, bufferDuration, bufferSampleRate, newBufferIdx);
                }
            });
            self.rec.open(function () {
                self.opened = true;
                self._resumeCtx();
                resolve();
            }, function (msg, isUserNotAllow) {
                reject(new Error(isUserNotAllow ? '麦克风权限被拒绝，请在浏览器地址栏重新授权'
                    : ('麦克风打开失败：' + msg)));
            });
        });
    };

    MicASR.prototype.close = function () {
        this.listenArmed = false;
        this.turnActive = false;
        this.sending = false;
        this.monitoring = false;
        this._preBuf = new Int16Array(0);
        this._recording = false;
        if (this.rec) {
            try { this.rec.stop(); } catch (e) { /* 忽略 */ }
            try { this.rec.close(); } catch (e) { /* 忽略 */ }
            this.rec = null;
        }
        this.opened = false;
        this._closeSocket();
    };

    MicASR.prototype._closeSocket = function () {
        var ws = this.ws;
        this.ws = null;
        if (ws) {
            try { ws.close(); } catch (e) { /* 忽略 */ }
        }
    };

    /** 建立 /api/asr 连接（幂等）。 */
    MicASR.prototype.connect = function () {
        var self = this;
        if (this.ws && this.ws.readyState === 1) { return Promise.resolve(); }
        return new Promise(function (resolve, reject) {
            var ws;
            try {
                ws = new WebSocket(self.cfg.asrUrl);
            } catch (e) {
                reject(new Error('ASR 地址无效：' + self.cfg.asrUrl));
                return;
            }
            ws.binaryType = 'arraybuffer';
            var settled = false;
            var timer = setTimeout(function () {
                if (settled) { return; }
                settled = true;
                try { ws.close(); } catch (e) { /* 忽略 */ }
                reject(new Error('ASR 连接超时'));
            }, self.cfg.connectTimeoutMs);

            ws.onopen = function () {
                if (settled) { return; }
                settled = true;
                clearTimeout(timer);
                self.ws = ws;
                self.cfg.onAsrState && self.cfg.onAsrState('ready');
                resolve();
            };
            ws.onmessage = function (ev) { self._onMessage(ev); };
            ws.onerror = function () {
                if (settled) { return; }
                settled = true;
                clearTimeout(timer);
                reject(new Error('ASR 连接失败（服务端 /api/asr 未就绪？）'));
            };
            ws.onclose = function (ev) {
                clearTimeout(timer);
                self.ws = null;
                self.sending = false;
                self.turnActive = false;
                // 关闭码用于区分“网络中断”(1006/非 clean) 与“我们自己关闭”(1000/clean)
                var code = ev && ev.code;
                var why = (ev && ev.reason) || '';
                var clean = ev ? !!ev.wasClean : false;
                try { console.warn('[ASR] ws closed', code, why, clean); } catch (e) { /* 忽略 */ }
                self.cfg.onAsrClose && self.cfg.onAsrClose(code, why, clean);
                self.cfg.onAsrState && self.cfg.onAsrState('closed');
                if (!settled) {
                    settled = true;
                    reject(new Error('ASR 连接被关闭'));
                }
            };
        });
    };

    /* ── 一轮收听 ─────────────────────────────────────────────────────── */

    /** 开始一轮收听：重置服务端缓冲并开始推流。 */
    MicASR.prototype.startTurn = function () {
        var self = this;
        if (!this.ws || this.ws.readyState !== 1) {
            return this.connect().then(function () { self.startTurn(); });
        }
        this._buf = new Int16Array(0);
        this._speechMs = 0;
        this._silenceMs = 0;
        this._turnMs = 0;
        this._warmupFrames = 0;
        this._lastVoiceAt = Date.now();
        this._turnStartAt = Date.now();
        this.sending = true;
        this.turnActive = true;
        this._bargeMs = 0;
        this._applyRecording(true);
        this._sendConfig(true);
        // 打断触发的这一轮：先把开口前缓存的音频补进去，避免丢掉开头几个字
        if (this._preBuf.length) {
            var pre = this._preBuf;
            this._preBuf = new Int16Array(0);
            this._append(pre);
        }
        this.cfg.onTurnStart && this.cfg.onTurnStart();
    };

    /** 结束一轮收听并等待识别结果。resolve(最终文本)。 */
    MicASR.prototype.endTurn = function () {
        var self = this;
        if (!this.turnActive && !this.sending) { return Promise.resolve(''); }
        this.sending = false;
        this.turnActive = false;
        var pending = this._buf;
        this._buf = new Int16Array(0);
        if (pending.length > 0) { this._sendChunk(pending); }
        this._sendConfig(false);

        return new Promise(function (resolve) {
            var done = function (text) {
                // 注意：_resolveFinal 存的是 done 自身，用它调用会递归回这里而不 resolve。
                // 必须直接 resolve 原始 promise，否则识别结果到达时本轮永远不会结束。
                if (self._resolveFinal !== done) { return; }
                self._resolveFinal = null;
                clearTimeout(self._finalTimer);
                self._finalTimer = null;
                resolve(text || '');
            };
            self._resolveFinal = done;
            // 离线推理很慢也留足余量：12s 内没结果就当本轮空转
            self._finalTimer = setTimeout(function () { done(''); }, 12000);
        });
    };

    /** 暂停/恢复收听（数字人说话时暂停，避免自激与误识别）。 */
    MicASR.prototype.arm = function (on) {
        this.listenArmed = !!on;
        if (!on) {
            this.sending = false;
            this.turnActive = false;
        }
        this._applyRecording(this.listenArmed || this.monitoring);
    };

    /**
     * 开启/关闭“只监听不收音”：数字人说话时保持采集，用于检测用户插话（自动打断），
     * 但不把音频推给 ASR，避免把自己的回声也识别进去。
     */
    MicASR.prototype.setMonitor = function (on) {
        this.monitoring = !!on;
        this._bargeMs = 0;
        if (!on) { this._preBuf = new Int16Array(0); }
        this._applyRecording(this.listenArmed || this.monitoring);
    };

    /**
     * 启停底层采集。Recorder 的 open() 只做授权，必须 start() 才会有 onProcess 回调；
     * 数字人说话时 stop()，避免扬声器声音被采集形成回声。
     */
    /**
     * 恢复全局 AudioContext。Recorder 在“开始录音前没有用户交互”时会让 AudioContext 停在
     * suspended，采集永远不出数据——现象就是：要点一下暂停再恢复，麦克风才有声音。
     */
    MicASR.prototype._resumeCtx = function () {
        try {
            var ctx = (typeof Recorder !== 'undefined') && Recorder.Ctx;
            if (ctx && ctx.state !== 'running' && ctx.resume) { ctx.resume(); }
        } catch (e) { /* 忽略 */ }
    };

    MicASR.prototype._applyRecording = function (on) {
        if (!this.rec || !this.opened) { return; }
        var self = this;
        if (on) {
            clearTimeout(this._stopTimer);
            this._stopTimer = null;
            if (!this._recording) {
                this._resumeCtx();
                try { this.rec.start(); this._recording = true; } catch (e) { /* 下一轮重试 */ }
            }
            return;
        }
        // 停止要延迟一拍：数字人说完→立刻恢复收音是“stop 后紧跟 start”，
        // 而 Recorder 的 stop 是异步的，会被这次抖动吞掉，表现为麦克风静默失效。
        if (!this._recording || this._stopTimer) { return; }
        this._stopTimer = setTimeout(function () {
            self._stopTimer = null;
            if (self.listenArmed || self.monitoring || !self._recording) { return; }
            try { self.rec.stop(); self._recording = false; } catch (e) { /* 忽略 */ }
        }, 0);
    };

    MicASR.prototype._sendConfig = function (isSpeaking) {
        if (!this.ws || this.ws.readyState !== 1) { return; }
        this.ws.send(JSON.stringify({
            chunk_size: [5, 10, 5],
            wav_name: 'h5',
            is_speaking: !!isSpeaking,
            chunk_interval: 10,
            itn: false,
            mode: 'offline'
        }));
    };

    /* ── 音频采集与 VAD ───────────────────────────────────────────────── */

    MicASR.prototype._onProcess = function (buffers, powerLevel, bufferDuration, bufferSampleRate, newBufferIdx) {
        var cfg = this.cfg;
        cfg.onLevel && cfg.onLevel(powerLevel, this.listenArmed || this.monitoring);

        if (!this.sending && !this.monitoring) { return; }

        if (!buffers || !buffers.length) { return; }

        // Recorder 的 buffers 是累积数组（每次回调都带上历史），必须只取本次新增的部分，
        // 否则会把同一段音频反复送给 ASR（实测 29s 内推出 5300s 音频）。
        var fresh = (typeof newBufferIdx === 'number' && newBufferIdx >= 0 && newBufferIdx < buffers.length)
            ? buffers.slice(newBufferIdx)
            : [buffers[buffers.length - 1]];

        var resampled;
        try {
            resampled = Recorder.SampleData(fresh, bufferSampleRate, cfg.sampleRate).data;
        } catch (e) {
            return;
        }
        if (!resampled || !resampled.length) { return; }

        var durMs = resampled.length * 1000 / cfg.sampleRate;
        var now = Date.now();

        // 只监听不收音（数字人正在说话）：检测用户插话 → 自动打断
        if (!this.sending) {
            this._pushPreBuf(resampled);
            var bargeTh = Math.max(cfg.minLevel * 2, this._noiseFloor * cfg.bargeInRatio);
            if (powerLevel > bargeTh) {
                this._bargeMs += durMs;
            } else {
                this._bargeMs = 0;
            }
            if (this._bargeMs >= cfg.bargeInMs && now >= this._bargeCooldownUntil) {
                this._bargeMs = 0;
                this._bargeCooldownUntil = now + cfg.bargeInCooldownMs;
                this.cfg.onBargeIn && this.cfg.onBargeIn();
            }
            return;
        }

        if (!this.listenArmed) { return; }
        this._turnMs += durMs;   // 统计已采集音频时长（不上报给服务端，仅用于展示与兜底）

        // 噪声底：仅在“还没开口”的阶段缓慢跟随环境音
        var floor = Math.max(this._noiseFloor, cfg.noiseFloorMin);
        var threshold = Math.max(cfg.minLevel, floor * cfg.noiseRatio);
        if (powerLevel > threshold) {
            this._speechMs += durMs;
            this._lastVoiceAt = now;
        } else if (this._speechMs === 0) {
            this._warmupFrames += 1;
            this._noiseFloor = this._noiseFloor * 0.92 + powerLevel * 0.08;
        }

        this._append(resampled);

        // 静音时长按真实时钟算：浏览器把缓冲批量回调时，用音频时长会严重失真
        var enoughSpeech = this._speechMs >= cfg.minSpeechMs;
        if (enoughSpeech && (now - this._lastVoiceAt) >= cfg.silenceMs) {
            this.cfg.onTurnEnd && this.cfg.onTurnEnd('silence', this.turnText());
            return;
        }
        if ((now - this._turnStartAt) >= cfg.maxTurnMs) {
            this.cfg.onTurnEnd && this.cfg.onTurnEnd('timeout', this.turnText());
        }
    };

    /** 已采集的语音时长（ms），供 UI 展示。 */
    MicASR.prototype.turnText = function () {
        return { speechMs: Math.round(this._speechMs), turnMs: Math.round(this._turnMs) };
    };

    /** 监听期缓存最近 prerollMs 的音频，打断发生时补进新一轮（避免丢掉开口的第一个字）。 */
    MicASR.prototype._pushPreBuf = function (int16) {
        var max = Math.floor(this.cfg.prerollMs * this.cfg.sampleRate / 1000);
        var merged = new Int16Array(this._preBuf.length + int16.length);
        merged.set(this._preBuf, 0);
        merged.set(int16, this._preBuf.length);
        this._preBuf = merged.length > max ? merged.slice(merged.length - max) : merged;
    };

    MicASR.prototype._append = function (int16) {
        var merged = new Int16Array(this._buf.length + int16.length);
        merged.set(this._buf, 0);
        merged.set(int16, this._buf.length);
        this._buf = merged;

        var n = this.cfg.chunkSamples;
        while (this._buf.length >= n) {
            this._sendChunk(this._buf.subarray(0, n));
            this._buf = this._buf.slice(n);
        }
    };

    MicASR.prototype._sendChunk = function (int16) {
        if (!this.ws || this.ws.readyState !== 1) { return; }
        // 复制成独立 ArrayBuffer，避免子视图与后续写入互相影响
        var copy = new Int16Array(int16.length);
        copy.set(int16);
        this.ws.send(copy.buffer);
    };

    /* ── 识别结果 ─────────────────────────────────────────────────────── */

    MicASR.prototype._onMessage = function (ev) {
        var data;
        try { data = JSON.parse(ev.data); } catch (e) { return; }
        if (!data || !data.is_final) { return; }

        var text = String(data.text || '').replace(/\s+/g, ' ').trim();
        this.cfg.onPartial && this.cfg.onPartial(text);
        if (this._resolveFinal) { this._resolveFinal(text); }
        this.cfg.onFinal && this.cfg.onFinal(text);
    };

    global.MicASR = MicASR;
})(window);
