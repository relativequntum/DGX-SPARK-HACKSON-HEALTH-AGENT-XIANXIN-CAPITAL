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
