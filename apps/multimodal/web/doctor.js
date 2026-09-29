/* 医生工作台：会话列表 → 文字版对话 → 医生参考版总结
 *
 * 数据来源：同机的医生端服务 doctor_service.py（/api/doctor/sessions）。
 * 页面本身不连任何云端接口，也不写入任何数据。
 * `?demo=1` 打开示例数据（不请求后端），`?api=http://host:8110` 可指向其它地址的服务。
 * 「重点」页签读 /api/doctor/sessions/<id>/highlights（阶段三 judge 在问诊结束后自动标出的值得先看的回答），
 * 点一条跳回对话原句；`?tab=highlights` 打开页面时直接停在这个页签。
 * 患者开了摄像头观察时，同一个接口还带 observe_segments：「对话记录」每条患者回答、「重点」每条命中
 * 下方加一行「同期观察（相对本人基线）」；只有动作数值，不出情绪标签，数据不足显示 unknown。
 */
(function () {
    'use strict';

    var CFG = {
        pollMs: 5000,          // 自动刷新间隔：比 LiveTalking 的会话回收周期长得多，足够"看到正在问诊"
        searchDelayMs: 250
    };

    var STATUS = {
        live: { label: '正在进行', cls: 'live' },
        active: { label: '进行中', cls: 'active' },
        ended: { label: '已出总结', cls: 'ended' },
        stale: { label: '中断未结', cls: 'stale' }
    };

    var el = {};
    var state = {
        items: [],
        status: '',
        q: '',
        currentId: '',
        detail: null,
        tab: 'chat',
        auto: true,
        timer: null,
        searchTimer: null,
        lastOk: 0,
        summaryText: '',
        highlights: null,      // 当前会话的「重点」（阶段三 judge）
        hlSig: ''
    };

    var demoMode = /[?&]demo=1\b/.test(location.search);
    // 页面可能由医生端服务（默认 8110）托管，也可能被放在 LiveTalking 的静态目录（8010）
    // 由 /triage.html 跳转过来。逐个尝试接口基地址，成功即固定，省去手工配 ?api=。
    var apiBases = (function () {
        var m = location.search.match(/[?&]api=([^&]+)/);
        if (m) { return [decodeURIComponent(m[1]).replace(/\/+$/, '')]; }
        return ['', 'http://' + (location.hostname || '127.0.0.1') + ':8110'];
    })();
    var apiIndex = 0;

    /* ── 工具 ─────────────────────────────────────────────────────────── */

    function $(id) { return document.getElementById(id); }

    function esc(text) {
        return String(text == null ? '' : text)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    /** 极简 Markdown 渲染（先转义再替换，避免把模型输出当 HTML 执行）。 */
    function renderRich(text) {
        return esc(text)
            .replace(/\{\{[A-Z_]+:[^}]*\}\}/g, '')   // 模型偶尔吐出的提示词模板标记
            .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
            .replace(/^#{1,6}\s*(.+)$/gm, '<span class="md-h">$1</span>')
            .replace(/^\s*[-*·]\s+(.+)$/gm, '<span class="md-li">$1</span>');
    }

    function pad(n) { return n < 10 ? '0' + n : '' + n; }

    function fmtClock(ts) {
        if (!ts) { return '—'; }
        var d = new Date(ts * 1000);
        return pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
    }

    function fmtDuration(sec) {
        if (!sec || sec < 0) { return '—'; }
        var m = Math.floor(sec / 60);
        var s = Math.floor(sec % 60);
        return (m ? m + ' 分 ' : '') + s + ' 秒';
    }

    function fmtRel(ts) {
        if (!ts) { return '—'; }
        var diff = Date.now() / 1000 - ts;
        if (diff < 60) { return '刚刚'; }
        if (diff < 3600) { return Math.floor(diff / 60) + ' 分钟前'; }
        if (diff < 86400) { return Math.floor(diff / 3600) + ' 小时前'; }
        return fmtClock(ts).slice(0, 11);
    }

    /** 问诊记录的事件时间 → 对回原句用的键：两边来自同一份 JSON 数字，转成字符串即可直接比较。 */
    function tkey(t) { return (t === null || t === undefined || t === '') ? '' : String(t); }

    function fmtIso(text) {
        var ms = Date.parse(text || '');
        return isNaN(ms) ? '—' : fmtClock(ms / 1000);
    }

    function statusText(s) { return (STATUS[s] || STATUS.stale).label; }
    function statusCls(s) { return (STATUS[s] || STATUS.stale).cls; }

    /* ── 数据访问 ─────────────────────────────────────────────────────── */

    function getJSON(path) {
        var base = apiBases[apiIndex];
        return fetch(base + path, { headers: { 'Accept': 'application/json' } })
            .then(function (r) {
                if (!r.ok) { throw new Error('HTTP ' + r.status); }
                return r.json();
            })
            .catch(function (err) {
                // 第一个基地址不通（页面不是由医生端服务托管的常见情况）就换一个
                if (apiIndex < apiBases.length - 1) {
                    apiIndex += 1;
                    return getJSON(path);
                }
                throw err;
            });
    }

    var RemoteAPI = {
        list: function (status, q) {
            return getJSON('/api/doctor/sessions?status=' + encodeURIComponent(status) +
                '&q=' + encodeURIComponent(q)).then(function (d) { return d.items || []; });
        },
        detail: function (id) {
            return getJSON('/api/doctor/sessions/' + encodeURIComponent(id));
        },
        // 「重点」读失败只影响这一个页签：不走 getJSON，免得把接口基地址切走
        highlights: function (id) {
            return fetch(apiBases[apiIndex] + '/api/doctor/sessions/' + encodeURIComponent(id) + '/highlights',
                { headers: { 'Accept': 'application/json' } })
                .then(function (r) {
                    if (r.status === 404) { return { ready: false, hits: [], unsupported: true }; }
                    if (!r.ok) { throw new Error('HTTP ' + r.status); }
                    return r.json();
                });
        }
    };

    var DemoAPI = buildDemo();
    var API = demoMode ? DemoAPI : RemoteAPI;

    function buildDemo() {
        var now = Date.now() / 1000;
        var items = [
            {
                id: '8f21c4de-1c3b-4c2f-9a71-0f2b6e4b91aa', title: '8f21c4de',
                started_at: now - 260, updated_at: now - 12, ended_at: null,
                turns: 3, summary_ready: false, provider: 'openclaw',
                preview: '患者：这两天饭后上腹部隐隐作痛', online: true, idle: 6.2, status: 'live'
            },
            {
                id: '7507329b-74ea-4e43-b8f3-cbaeef71e0c0', title: '7507329b',
                started_at: now - 1850, updated_at: now - 1500, ended_at: now - 1500,
                turns: 5, summary_ready: true, provider: 'openclaw',
                preview: '已生成预问诊记录', online: false, idle: null, status: 'ended'
            },
            {
                id: 'c07a5e10-6d2d-4f6a-8d43-5a0e9c3f21b7', title: 'c07a5e10',
                started_at: now - 9000, updated_at: now - 8600, ended_at: null,
                turns: 2, summary_ready: false, provider: 'local',
                preview: '患者：喉咙有点疼', online: false, idle: null, status: 'stale'
            }
        ];
        var chatA = [
            { role: 'user', text: '这两天饭后上腹部隐隐作痛', t: now - 250, source: 'voice' },
            { role: 'assistant', text: '这种疼痛持续多久了？是隐痛还是绞痛？', t: now - 240, provider: 'openclaw' },
            { role: 'user', text: '两天左右，隐痛，不剧烈', t: now - 160, source: 'voice' },
            { role: 'assistant', text: '有没有反酸、恶心或者腹泻？', t: now - 150, provider: 'openclaw' },
            { role: 'user', text: '有点反酸，没有恶心', t: now - 40, source: 'voice' },
            { role: 'assistant', text: '好的，我再确认一下疼痛的严重程度，从 0 到 10 大概几分？', t: now - 12, provider: 'openclaw' }
        ];
        var chatB = [
            { role: 'user', text: '上腹部隐痛两天，饭后加重', t: now - 1800, source: 'text' },
            { role: 'assistant', text: '疼痛会向后背放射吗？', t: now - 1790, provider: 'openclaw' },
            { role: 'user', text: '没有，就是胃口那一片', t: now - 1700, source: 'voice' },
            { role: 'assistant', text: '有没有黑便、呕血或者发热？', t: now - 1690, provider: 'openclaw' },
            { role: 'user', text: '都没有', t: now - 1600, source: 'voice' },
            { role: 'assistant', text: '好的，信息已经记录下来了。', t: now - 1500, provider: 'openclaw' }
        ];
        var details = {};
        details[items[0].id] = { session: items[0], messages: chatA, summary: null };
        details[items[1].id] = {
            session: items[1], messages: chatB,
            summary: {
                doctor: '预问诊记录（待医生核实）\n\n主诉：上腹部隐痛两天，饭后加重。\n\n' +
                    '现病史：\n- 上腹部隐痛，持续两天，饭后加重\n- 无放射痛\n- 无黑便、呕血、发热\n' +
                    '\n基本信息：\n- 姓名：未采集\n- 性别：未采集\n- 年龄：未采集\n' +
                    '\n关键缺项（供医生参考）：\n1. 疼痛严重程度未明确\n2. 既往史、过敏史、用药史未采集',
                patient: '您的不适：上腹部隐痛两天，饭后加重。\n\n' +
                    '如信息有出入或需要更正，请随时告诉医生。',
                provider: 'openclaw', t: now - 1500
            }
        };
        details[items[2].id] = {
            session: items[2],
            messages: [
                { role: 'user', text: '喉咙有点疼', t: now - 8900, source: 'voice' },
                { role: 'assistant', text: '抱歉，我这边有点卡，请您再说一遍。', t: now - 8860, provider: 'fallback-line' }
            ],
            summary: null
        };

        var highlights = {};
        highlights[items[1].id] = {
            ready: true, stale: false, generated_at: new Date((now - 1440) * 1000).toISOString(),
            review_notice: '待医务人员确认：本页只标出值得先看的回答，不构成诊断，不替代确定性红旗规则。',
            hits: [
                {
                    t: now - 1800, turn_index: 0, text: '上腹部隐痛两天，饭后加重', question: '',
                    group: 'medical', group_label: '医疗信息', importance: 0.6, risk: false,
                    labels: { info_category: '主诉与病程', urgency: '紧急程度 4/9', needs_followup: '信息不完整，需追问' },
                    evidence: '隐痛两天，饭后加重', source: 'local:qwen3.6-35b-a3b'
                },
                {
                    t: now - 1600, turn_index: 4, text: '都没有', question: '有没有黑便、呕血或者发热？',
                    group: 'medical', group_label: '医疗信息', importance: 0.52, risk: false,
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

        return {
            list: function (status, q) {
                var out = items.filter(function (i) {
                    return !status || i.status === status;
                }).filter(function (i) {
                    return !q || i.id.indexOf(q) >= 0 || i.preview.indexOf(q) >= 0;
                });
                return Promise.resolve(out);
            },
            detail: function (id) {
                var d = details[id];
                return d ? Promise.resolve(d) : Promise.reject(new Error('会话不存在'));
            },
            highlights: function (id) {
                return Promise.resolve(highlights[id] || { ready: false, hits: [] });
            }
        };
    }

    /* ── 列表渲染 ─────────────────────────────────────────────────────── */

    function itemHTML(item) {
        return '<li><button type="button" class="item' +
            (item.id === state.currentId ? ' is-on' : '') + '" data-id="' + esc(item.id) + '">' +
            '<span class="item-top">' +
            '<span class="item-id">会话 ' + esc(item.title) + '</span>' +
            '<span class="item-time">' + esc(fmtRel(item.updated_at)) + '</span>' +
            '</span>' +
            '<span class="item-preview">' + esc(item.preview || '暂无内容') + '</span>' +
            '<span class="item-foot">' +
            '<span class="badge" data-status="' + esc(statusCls(item.status)) + '">' +
            esc(statusText(item.status)) + '</span>' +
            '<span class="item-turns">' + item.turns + ' 轮提问' +
            (item.summary_ready ? ' · 已出总结' : '') + '</span>' +
            '</span></button></li>';
    }

    function renderList() {
        var q = state.q;
        el.listMeta.textContent = state.items.length
            ? '共 ' + state.items.length + ' 个会话' + (q ? ' · 搜索「' + q + '」' : '')
            : '';
        if (!state.items.length) {
            el.list.innerHTML = '<li class="empty-list">' +
                (state.q || state.status ? '没有匹配的会话' : '暂无问诊会话') +
                '<br />患者端开始问诊后，会话会自动出现在这里</li>';
            return;
        }
        el.list.innerHTML = state.items.map(itemHTML).join('');
    }

    function loadList() {
        return API.list(state.status, state.q).then(function (items) {
            state.items = items;
            state.lastOk = Date.now();
            setPill(demoMode ? 'demo' : 'ok', demoMode ? '示例数据' : '已连接 · ' + fmtClock(Date.now() / 1000).slice(6));
            renderList();
            return items;
        }).catch(function (err) {
            setPill('error', '无法连接医生端服务');
            el.list.innerHTML = '<li class="empty-list">读取会话失败：' + esc(err.message) +
                '<br />请确认 doctor_service.py 已启动（默认端口 8110）</li>';
            el.listMeta.textContent = '';
        });
    }

    /* ── 详情渲染 ─────────────────────────────────────────────────────── */

    function renderMessages(messages, summary) {
        if (!messages.length && !(summary && summary.doctor)) {
            el.chat.innerHTML = '<li class="empty-list">该会话还没有对话内容<br />' +
                '患者刚开始连接或尚未开口时会是这个状态</li>';
            return;
        }
        var html = messages.map(function (m) {
            var who = m.role === 'user' ? '患者' : '预问诊助手';
            var extra = m.role === 'user'
                ? (m.source === 'text' ? '文字输入' : '语音输入')
                : (m.provider ? '来源 ' + m.provider : '');
            return '<li class="msg msg-' + (m.role === 'user' ? 'user' : 'assistant') + '" data-t="' +
                esc(tkey(m.t)) + '">' +
                '<span class="msg-head"><span>' + esc(who) + '</span>' +
                '<span>' + esc(fmtClock(m.t)) + '</span>' +
                (extra ? '<span>' + esc(extra) + '</span>' : '') + '</span>' +
                '<span class="msg-bubble">' + esc(m.text) + '</span></li>';
        }).join('');
        // 问诊结束后的收尾：把「医生参考版」总结作为对话的最后一条展示出来，
        // 医生不用切页签也能顺着对话读到结论。患者核对版只留在「总结」页签。
        if (summary && summary.doctor) {
            html += '<li class="msg msg-summary">' +
                '<span class="msg-head"><span>问诊总结 · 医生参考版</span>' +
                '<span>' + esc(fmtClock(summary.t)) + '</span>' +
                (summary.provider ? '<span>来源 ' + esc(summary.provider) + '</span>' : '') +
                '<span>详见「预问诊总结」页签</span></span>' +
                '<span class="msg-bubble msg-bubble-summary md">' + renderRich(summary.doctor) + '</span></li>';
        }
        el.chat.innerHTML = html;
        markHits();
    }

    function renderSummary(detail) {
        var summary = detail.summary;
        el.sumDot.hidden = !summary;
        if (!summary) {
            el.sumMeta.textContent = detail.session.status === 'ended'
                ? '本次问诊没有生成总结' : '问诊进行中，尚未生成总结';
            el.copyBtn.hidden = true;
            el.patientFold.hidden = true;
            el.sumBody.innerHTML = '<p class="md-wait">' +
                (detail.session.status === 'ended'
                    ? '记录里没有找到总结内容，可能生成失败或被中断。'
                    : '患者在页面上点了「结束问诊」并完成录制后，这里会自动出现给医生看的预问诊记录。') +
                '</p>';
            return;
        }
        state.summaryText = summary.doctor || '';
        el.sumMeta.textContent = '生成于 ' + fmtClock(summary.t) +
            (summary.provider ? ' · 模型来源 ' + summary.provider : '');
        el.copyBtn.hidden = !summary.doctor;
        el.sumBody.innerHTML = summary.doctor
            ? renderRich(summary.doctor)
            : '<p class="md-wait">本次返回里没有识别到「医生参考版」段落。</p>';
        el.patientFold.hidden = !summary.patient;
        el.patientBody.innerHTML = summary.patient ? renderRich(summary.patient) : '';
    }

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
        var labels = Object.keys(x.labels || {}).map(function (k) { return x.labels[k]; });
        return '<li><button type="button" class="hl-item' + (x.risk ? ' is-risk' : '') + '" data-t="' +
            esc(tkey(x.t)) + '" data-index="' + esc(x.turn_index == null ? '' : x.turn_index) + '">' +
            '<span class="hl-top">' +
            (x.risk ? '<span class="hl-tag is-risk">疑似风险线索 · 请人工核实</span>' : '') +
            '<span class="hl-tag" data-group="' + esc(x.group) + '">' + esc(x.group_label || '') + '</span>' +
            '<span class="hl-pct" title="模型自报的把握程度">' + Math.round((x.importance || 0) * 100) + '%</span>' +
            '<span class="hl-jump">跳到原句</span></span>' +
            (x.question ? '<span class="hl-q">回答「' + esc(x.question) + '」时</span>' : '') +
            '<span class="hl-text">' + esc(x.text) + '</span>' +
            (x.evidence ? '<span class="hl-ev">依据：「' + esc(x.evidence) + '」</span>' : '') +
            (obs ? '<span class="hl-obs">' + esc(obs) + '</span>' : '') +
            (labels.length ? '<span class="hl-labels">' + labels.map(function (l) {
                return '<span>' + esc(l) + '</span>';
            }).join('') + '</span>' : '') +
            '</button></li>';
    }

    function renderHighlights(h) {
        h = h || { ready: false, hits: [] };
        state.highlights = h;
        var hits = h.hits || [];
        var anyRisk = hits.some(function (x) { return x.risk; });
        el.hlDot.hidden = !(h.ready && hits.length);
        el.hlDot.classList.toggle('is-risk', anyRisk);
        var s = state.detail ? state.detail.session : null;
        if (!h.ready) {
            var why = h.unsupported ? '医生端服务还是旧版本，没有「重点」接口。'
                : h.error ? '重点结果暂时读不到（' + h.error + '），稍后会自动重试。'
                    : (s && (s.status === 'live' || s.status === 'active'))
                        ? '问诊还在进行。结束后，阶段三会在大模型空闲时自动标出值得先看的回答，一般一两分钟内出现在这里。'
                        : '这次问诊的重点还没生成。阶段三的自动判断会在大模型空闲时处理，稍后刷新即可。';
            el.hlMeta.textContent = '';
            el.hlNotice.hidden = true;
            el.hlList.innerHTML = '<li class="empty-list">' + esc(why) + '</li>';
        } else {
            el.hlMeta.textContent = '阶段三自动标出 · 生成于 ' + fmtIso(h.generated_at) + ' · ' + hits.length + ' 条' +
                (anyRisk ? ' · 含疑似风险线索' : '') + (h.stale ? ' · 对话有更新，正在重新生成' : '');
            el.hlNotice.hidden = false;
            el.hlNotice.textContent = (h.review_notice || '待医务人员确认。') +
                ' 百分比是模型自报的把握程度，不是病情或情绪评分。';
            el.hlList.innerHTML = hits.length ? hits.map(function (x) { return hitHTML(x, h); }).join('')
                : '<li class="empty-list">这次没有达到提示阈值的回答。请仍以完整对话为准，本页不替代红旗规则。</li>';
        }
        markHits();
    }

    /** 在对话记录里给命中的回答打标记（风险线索另一种颜色）。 */
    function markHits() {
        var h = state.highlights;
        var byT = {};
        ((h && h.ready && h.hits) || []).forEach(function (x) {
            var k = tkey(x.t);
            if (k) { byT[k] = Boolean(byT[k]) || Boolean(x.risk); }
        });
        var msgs = el.chat.querySelectorAll('li.msg');
        for (var i = 0; i < msgs.length; i += 1) {
            var k = msgs[i].getAttribute('data-t') || '';
            var hit = k !== '' && Object.prototype.hasOwnProperty.call(byT, k);
            msgs[i].classList.toggle('msg-hit', hit);
            msgs[i].classList.toggle('msg-hit-risk', hit && byT[k]);
        }
        markObserve();   // 对话记录每次重画后，同期观察行也跟着补上
    }

    function loadHighlights(id) {
        return API.highlights(id).then(function (h) {
            if (id !== state.currentId) { return; }
            h = h || { ready: false, hits: [] };
            var sig = JSON.stringify([id, h.ready, h.stale, h.generated_at, (h.hits || []).length, h.error || '',
                h.camera, h.observe_ready, (h.observe_segments || []).map(function (s) { return s.frames; }).join(',')]);
            if (sig === state.hlSig) { markHits(); return; }   // 没变化就不重画，免得打断医生正在看的列表
            state.hlSig = sig;
            renderHighlights(h);
        }).catch(function (err) {
            if (id !== state.currentId) { return; }
            state.hlSig = '';
            renderHighlights({ ready: false, hits: [], error: err.message });
        });
    }

    function jumpToMessage(tval, index) {
        switchTab('chat', true);
        var target = tval ? el.chat.querySelector('li.msg[data-t="' + String(tval).replace(/"/g, '') + '"]') : null;
        if (!target && index !== null && index !== '') {
            target = el.chat.querySelectorAll('li.msg:not(.msg-summary)')[Number(index)] || null;
        }
        if (!target) { return; }
        target.scrollIntoView({ block: 'center' });
        target.classList.remove('msg-flash');
        void target.offsetWidth;   // 重新触发闪烁动画
        target.classList.add('msg-flash');
        setTimeout(function () { target.classList.remove('msg-flash'); }, 1800);
    }

    function renderMeta(detail) {
        var s = detail.session;
        var chips = [
            '开始 ' + fmtClock(s.started_at),
            s.ended_at ? '结束 ' + fmtClock(s.ended_at) + '（耗时 ' + fmtDuration(s.ended_at - s.started_at) + '）'
                : '最后活动 ' + fmtRel(s.updated_at),
            s.turns + ' 轮提问',
            s.provider ? '模型来源 ' + s.provider : '',
            s.online ? '数字人在线' : (s.status === 'ended' ? '会话已结束' : '数字人已离线')
        ].filter(Boolean);
        el.detailMeta.innerHTML = chips.map(function (c) {
            return '<span class="meta-chip">' + esc(c) + '</span>';
        }).join('');

        el.detailTitle.textContent = '会话 ' + s.title;
        el.detailSub.textContent = '会话标识 ' + s.id + ' · 更新于 ' + fmtClock(s.updated_at);
        el.detailStatus.textContent = statusText(s.status);
        el.detailStatus.setAttribute('data-status', statusCls(s.status));
        el.chatEnd.hidden = s.ended_at !== null;
        el.chatEnd.textContent = '问诊已结束' + (s.summary_ready ? '，总结查看右侧「预问诊总结」' : '，本次未生成总结');
    }

    function renderDetail(detail) {
        state.detail = detail;
        el.empty.hidden = true;
        el.detail.hidden = false;
        renderMeta(detail);
        renderMessages(detail.messages || [], detail.summary);
        renderSummary(detail);
        switchTab(state.tab, true);
    }

    function loadDetail(id, keepScroll) {
        var scrollTop = keepScroll ? el.paneChat.scrollTop : 0;
        return API.detail(id).then(function (detail) {
            renderDetail(detail);
            el.paneChat.scrollTop = scrollTop || el.paneChat.scrollHeight;
            loadHighlights(id);
        }).catch(function (err) {
            el.empty.hidden = false;
            el.detail.hidden = true;
            el.empty.innerHTML = '<h2>读取会话失败</h2><p>' + esc(err.message) +
                '<br />会话可能已被服务重启清理。</p>';
        });
    }

    function selectSession(id) {
        if (!id) { return; }
        state.currentId = id;
        state.highlights = null;
        state.hlSig = '';
        if (location.hash !== '#' + id) {
            try { history.replaceState(null, '', '#' + id); } catch (e) { location.hash = id; }
        }
        renderList();
        loadDetail(id, false);
    }

    function switchTab(tab, silent) {
        state.tab = tab;
        var tabs = el.tabs.querySelectorAll('.tab');
        for (var i = 0; i < tabs.length; i += 1) {
            tabs[i].classList.toggle('is-on', tabs[i].getAttribute('data-tab') === tab);
        }
        el.paneChat.hidden = tab !== 'chat';
        el.paneSummary.hidden = tab !== 'summary';
        el.paneHighlights.hidden = tab !== 'highlights';
        if (!silent && tab === 'chat') { el.paneChat.scrollTop = el.paneChat.scrollHeight; }
    }

    function setPill(stateName, text) {
        el.connPill.setAttribute('data-state', stateName);
        el.connPill.textContent = text;
    }

    function copySummary() {
        var text = state.summaryText || '';
        if (!text) { return; }
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(function () {
                el.copyBtn.textContent = '已复制';
                setTimeout(function () { el.copyBtn.textContent = '复制医生版总结'; }, 1600);
            }, function () { fallbackCopy(text); });
        } else {
            fallbackCopy(text);
        }
    }

    function fallbackCopy(text) {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); } catch (e) { /* 浏览器不允许就算了 */ }
        document.body.removeChild(ta);
        el.copyBtn.textContent = '已复制';
        setTimeout(function () { el.copyBtn.textContent = '复制医生版总结'; }, 1600);
    }

    /* ── 轮询与事件绑定 ───────────────────────────────────────────────── */

    function tick() {
        if (!state.auto || document.hidden) { return; }
        loadList().then(function (items) {
            // 当前选中会话在过滤后可能不在列表里，详情不受影响，继续刷新即可
            if (state.currentId && (items || []).length) { loadDetail(state.currentId, true); }
        });
    }

    function bind() {
        el.list.addEventListener('click', function (ev) {
            var btn = ev.target.closest ? ev.target.closest('.item') : null;
            if (btn) { selectSession(btn.getAttribute('data-id')); }
        });

        el.chips.addEventListener('click', function (ev) {
            var chip = ev.target.closest ? ev.target.closest('.chip') : null;
            if (!chip) { return; }
            var chips = el.chips.querySelectorAll('.chip');
            for (var i = 0; i < chips.length; i += 1) { chips[i].classList.remove('is-on'); }
            chip.classList.add('is-on');
            state.status = chip.getAttribute('data-status') || '';
            loadList();
        });

        el.search.addEventListener('input', function () {
            clearTimeout(state.searchTimer);
            state.searchTimer = setTimeout(function () {
                state.q = el.search.value.trim();
                loadList();
            }, CFG.searchDelayMs);
        });

        el.tabs.addEventListener('click', function (ev) {
            var tab = ev.target.closest ? ev.target.closest('.tab') : null;
            if (tab) { switchTab(tab.getAttribute('data-tab'), false); }
        });

        el.refreshBtn.addEventListener('click', function () {
            loadList().then(function () {
                if (state.currentId) { loadDetail(state.currentId, true); }
            });
        });

        el.autoChk.addEventListener('change', function () {
            state.auto = el.autoChk.checked;
        });

        el.copyBtn.addEventListener('click', copySummary);

        el.hlList.addEventListener('click', function (ev) {
            var item = ev.target.closest ? ev.target.closest('.hl-item') : null;
            if (item) { jumpToMessage(item.getAttribute('data-t'), item.getAttribute('data-index')); }
        });
    }

    function init() {
        // 左边的名字是 JS 里用的，右边是 doctor.html 里的 id
        var nodes = {
            list: 'list', listMeta: 'list-meta', detail: 'detail', empty: 'empty',
            detailTitle: 'd-title', detailSub: 'd-sub', detailStatus: 'd-status',
            detailMeta: 'd-meta', chat: 'chat', chatEnd: 'chat-end',
            sumBody: 'sum-body', sumMeta: 'sum-meta', sumDot: 'sum-dot',
            patientBody: 'patient-body', patientFold: 'patient-fold', copyBtn: 'copy-btn',
            search: 'q', chips: 'chips', tabs: 'tabs', refreshBtn: 'refresh-btn',
            autoChk: 'auto-chk', connPill: 'conn-pill',
            paneChat: 'pane-chat', paneSummary: 'pane-summary',
            paneHighlights: 'pane-highlights', hlList: 'hl-list', hlMeta: 'hl-meta',
            hlNotice: 'hl-notice', hlDot: 'hl-dot'
        };
        Object.keys(nodes).forEach(function (key) { el[key] = $(nodes[key]); });
        var missing = Object.keys(nodes).filter(function (k) { return !el[k]; });
        if (missing.length) {
            // 页面结构变了就尽早喊出来，否则只会看到"点了没反应"
            console.error('[doctor] 缺少节点:', missing.join(', '));
            return;
        }
        bind();
        if (el.autoChk) { state.auto = el.autoChk.checked; }
        var tabParam = location.search.match(/[?&]tab=(chat|summary|highlights)\b/);
        if (tabParam) { state.tab = tabParam[1]; }
        var initial = (location.hash || '').replace(/^#/, '');
        loadList().then(function () {
            if (initial) { state.currentId = initial; renderList(); loadDetail(initial, false); }
        });
        setInterval(tick, CFG.pollMs);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
}());
