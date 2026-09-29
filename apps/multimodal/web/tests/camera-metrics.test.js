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
