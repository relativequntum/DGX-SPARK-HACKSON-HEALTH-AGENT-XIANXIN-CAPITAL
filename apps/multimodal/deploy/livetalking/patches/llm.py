# 来源与许可：本文件改自 lipku/LiveTalking 的 llm.py
#   https://github.com/lipku/LiveTalking （上游提交 b3e7490a20e7a6330492f8a6ea8200a5d50279d1）
#   上游以 Apache License 2.0 发布：http://www.apache.org/licenses/LICENSE-2.0
# 本项目（spark-Hackson）修改了此文件：新增 openclaw / local provider、会话复用、失败降级、
# TTS 文本清理、SSE 文字事件与问诊转写落盘等。修改后的文件仍按 Apache-2.0 分发。
# 第三方说明见仓库根目录 THIRD_PARTY_NOTICES.md。
import re
import time
import os
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from avatars.base_avatar import BaseAvatar
from utils.logger import logger

# 问诊转写落盘（医生端控制台的数据来源）。缺省缺失或被删都不影响对话：
# 所有调用包 try/except，记录失败只打日志。
try:
    import consult_recorder as _recorder
except Exception as _e:  # noqa: BLE001
    logger.warning("consult_recorder 不可用，医生端将拿不到问诊记录: %s", _e)
    _recorder = None

# Built-in LLM providers. Each exposes an OpenAI-compatible chat completions
# endpoint; the active one is selected with --llm_provider (default: dashscope).
LLM_PROVIDERS = {
    "openclaw": {
        "api_key_env": "OPENCLAW_API_KEY",
        "base_url": os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789/v1"),
        "default_model": os.getenv("OPENCLAW_MODEL", "openclaw/tcm"),
    },
    "local": {
        "api_key_env": "LOCAL_LLM_API_KEY",
        "base_url": os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8080/v1"),
        "default_model": os.getenv("LOCAL_LLM_MODEL", ""),
    },
    "dashscope": {
        "api_key_env": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
    },
    "orcarouter": {
        "api_key_env": "ORCAROUTER_API_KEY",
        "base_url": "https://api.orcarouter.ai/v1",
        "default_model": "orcarouter/auto",
    },
}

# System prompt for plain OpenAI-compatible providers. Kept inside the
# pre-consultation safety boundary: collect and organise information only.
# The openclaw provider is an agent endpoint with its own persona and rules,
# so no system message is injected there.
SYSTEM_PROMPT = os.getenv(
    'LLM_SYSTEM_PROMPT',
    '你是预问诊助手，只负责采集和整理患者信息，不做诊断、不给用药或治疗建议；'
    '每次只问一个必要问题，回复简短、口语化。')

# Last-resort line when every provider fails: deterministic and safe to speak.
FALLBACK_LINE = os.getenv('LLM_FALLBACK_LINE', '抱歉，我这边有点卡，请您再说一遍。')

# Markdown / emoji noise that TTS would otherwise read out loud.
_TTS_NOISE = re.compile(
    r'[*_`#|~]'
    r'|-{2,}'
    r'|[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200B-\u200D]'
)


def _llm_provider(opt) -> str:
    """Return the configured provider name, defaulting to dashscope."""
    return getattr(opt, 'llm_provider', 'dashscope') or 'dashscope'


def _llm_cfg(provider: str) -> dict:
    return LLM_PROVIDERS.get(provider, LLM_PROVIDERS['dashscope'])


def _llm_client(opt, provider: str = None):
    """Create the OpenAI-compatible client for the given/configured provider."""
    from openai import OpenAI
    cfg = _llm_cfg(provider or _llm_provider(opt))
    return OpenAI(
        api_key=os.getenv(cfg['api_key_env']),
        base_url=cfg['base_url'],
        timeout=float(os.getenv('LLM_TIMEOUT', '60')),
    )


def _llm_model(opt, provider: str = None) -> str:
    """Resolve the model name, falling back to the provider default."""
    provider = provider or _llm_provider(opt)
    if provider == _llm_provider(opt):
        cli_model = getattr(opt, 'llm_model', '') or ''
        if cli_model:
            return cli_model
    return _llm_cfg(provider)['default_model']


def _clean_for_tts(text: str) -> str:
    """Strip markdown/emoji so the avatar does not read symbols out loud."""
    return _TTS_NOISE.sub('', text).strip()


def _notify(avatar_session, eventpoint: dict) -> None:
    """把事件推给前端（/sse）。推送失败绝不能影响对话主流程。"""
    try:
        avatar_session.notify(eventpoint)
    except Exception:
        logger.debug('notify failed: %s', eventpoint)


def _is_silent(datainfo: dict) -> bool:
    """前端可通过 tts={'silent': True} 要求“只回文字、不朗读”。

    用于「生成预问诊记录」这类长文本：内容要展示在对话区，但不适合让数字人整段念出来。
    """
    tts = (datainfo or {}).get('tts') or {}
    if not isinstance(tts, dict):
        return False
    return bool(tts.get('silent'))


def _max_speak_chars(datainfo: dict) -> int:
    """单轮最多朗读多少字（0 = 不限制）。

    数字人每多念一句，就要多合成一段音频、多渲染上百帧。实测渲染队列被打满时
    （日志 sleep qsize=20）服务端来不及回应浏览器的 ICE 保活包，30s 后连接被判失效断开。
    预问诊本来就该一次只问一个问题，所以按句子边界截断，保证一句话说完整。
    只显示不朗读的请求（小结）不占渲染资源，不截断。
    """
    if _is_silent(datainfo):
        return 0
    return int(os.getenv('LLM_MAX_SPEAK_CHARS', '70'))


# Agent 会把调用工具的过程当成正文说出来，患者不该看到这些内部动作。
# 只在"第一人称意图 + 系统动作 + 内部对象"同时出现时才丢，避免误伤正常问诊语句。
_AGENT_INTERNAL_RE = re.compile(
    r'(Skill|skill|session|records?/|会话目录|记录目录|会话信息|会话标识|调用工具|工具调用|目录|规范流程|中医预问诊的规范)'
    r'|(我需要|我要|让我|我先|我会先|接下来我)[^。！？]{0,30}'
    r'(获取|建立|读取|创建|调用|初始化)[^。！？]{0,20}(会话|目录|文件|工具|信息|状态|标识|记录)'
)


def _is_agent_internal(text: str) -> bool:
    """这句话是不是 agent 在描述自己的内部动作。"""
    return bool(_AGENT_INTERNAL_RE.search(text or ''))


def _say(avatar_session, text: str, datainfo: dict, speak: bool = True):
    if _is_agent_internal(text):
        logger.info('skip agent internal: %s', (text or '')[:40])
        return
    # 文本先推给前端（右侧对话区/小结卡片），不等待 TTS；静默请求只推文本
    _notify(avatar_session, {'status': 'llm_text', 'text': text})
    if not speak:
        return          # 只是不再送 TTS，正文已经完整推给前端了
    cleaned = _clean_for_tts(text)
    if cleaned and not _is_silent(datainfo):
        segs = [s for s in _split_segments(cleaned) if s.strip()]   # TTS-SEGMENT
        last = len(segs) - 1
        for i, seg in enumerate(segs):
            di = dict(datainfo)
            di['_seg_last'] = (i == last)   # 前端据此判断本轮是否播完
            avatar_session.put_msg_txt(seg, di)



def _tts_segment_chars() -> int:
    """单段最多多少字（0 = 不切分）。段越短，TTS 合成越快，数字人开口越早。"""
    return int(os.getenv('TTS_SEGMENT_CHARS', '18'))


def _split_segments(text: str) -> list:
    """按标点把长句切成短段，段内保持完整语气，不切断词。

    只为让第一段尽快开始合成：总音频时长不变，但首段开口时间显著提前。
    """
    import re
    max_chars = _tts_segment_chars()
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]
    parts = re.split(r'(?<=[\u3002\uff01\uff1f!?\uff1b;\uff0c,\u3001])', text)
    segs, cur = [], ''
    for p in parts:
        if not p:
            continue
        if cur and len(cur) + len(p) > max_chars:
            segs.append(cur)
            cur = p
        else:
            cur += p
    if cur:
        segs.append(cur)
    return segs or [text]


def _llm_stream(provider: str, message, avatar_session: 'BaseAvatar', datainfo: dict) -> str:
    """Stream one reply from the given provider and push sentences to TTS.

    Returns the full reply text (excluding lines filtered out as agent
    internal) so the caller can persist the transcript.
    """
    opt = avatar_session.opt
    start = time.perf_counter()
    # 本轮真正说出去的正文（给前端显示的都算），用于落盘给医生端看
    said = []
    client = _llm_client(opt, provider)
    model = _llm_model(opt, provider)
    if provider == 'openclaw':
        # Agent endpoint: one agent session per avatar session so the agent
        # keeps the consultation state across turns.
        sessionid = getattr(avatar_session, 'sessionid', '') or ''
        kwargs = {
            'model': model,
            'messages': [{'role': 'user', 'content': message}],
            'stream': True,
        }
        if sessionid:
            kwargs['user'] = sessionid
    else:
        kwargs = {
            'model': model,
            'messages': [{'role': 'system', 'content': SYSTEM_PROMPT},
                         {'role': 'user', 'content': message}],
            'stream': True,
            # Display token usage in the last line of the streamed response.
            'stream_options': {"include_usage": True},
        }
    end = time.perf_counter()
    logger.info(f"llm Time init: {end-start}s,provider={provider},model={model},{message}")
    completion = client.chat.completions.create(**kwargs)
    result = ""
    spoken = 0
    speak_enabled = True
    max_chars = _max_speak_chars(datainfo)
    first = True
    for chunk in completion:
        if len(chunk.choices) > 0:
            if first:
                end = time.perf_counter()
                logger.info(f"llm Time to first chunk: {end-start}s")
                first = False
            msg = chunk.choices[0].delta.content
            if msg is None:
                continue
            lastpos = 0
            for i, char in enumerate(msg):
                if char in ",.!;:，。！？：；":
                    result = result + msg[lastpos:i+1]
                    lastpos = i + 1
                    if len(result) > 10:
                        logger.info(result)
                        if not _is_agent_internal(result):
                            said.append(result)
                        _say(avatar_session, result, datainfo, speak_enabled)
                        spoken += len(result)
                        result = ""
                        if max_chars and spoken >= max_chars:
                            # 朗读长度到此为止（避免渲染队列积压），但剩余正文照常推给前端显示
                            logger.info('llm speech capped after %d spoken chars', spoken)
                            speak_enabled = False
            result = result + msg[lastpos:]
    end = time.perf_counter()
    logger.info(f"llm Time to last chunk: {end-start}s")
    if result:
        if not _is_agent_internal(result):
            said.append(result)
        _say(avatar_session, result, datainfo, speak_enabled)
    return ''.join(said)


def llm_response(message, avatar_session: 'BaseAvatar', datainfo: dict = {}):
    datainfo = datainfo or {}
    provider = _llm_provider(avatar_session.opt)
    fallback = os.getenv('LLM_FALLBACK_PROVIDER', 'local')
    used = ''
    # 患者的提问从这里进入：先落盘，保证即使后面推理失败，医生也能看到患者说了什么。
    # 静默轮是「生成小结」的指令，不是患者的陈述，不进对话记录。
    sessionid = getattr(avatar_session, 'sessionid', '') or ''
    if _recorder and sessionid and not _is_silent(datainfo):
        try:
            _recorder.record_user(sessionid, message)
        except Exception:  # noqa: BLE001
            logger.exception('record user failed')
    reply = ''
    try:
        reply = _llm_stream(provider, message, avatar_session, datainfo)
        used = provider
    except Exception:
        logger.exception(f'llm exception (provider={provider}):')
        # Degrade to the local model so the avatar can still answer out loud.
        if provider != fallback and fallback in LLM_PROVIDERS:
            logger.warning(f'llm fallback: {provider} -> {fallback}')
            try:
                reply = _llm_stream(fallback, message, avatar_session, datainfo)
                used = fallback
            except Exception:
                logger.exception(f'llm fallback exception (provider={fallback}):')
    if not used:
        # Nothing worked: say something safe instead of staying silent.
        _say(avatar_session, FALLBACK_LINE, datainfo)
        reply = FALLBACK_LINE
        used = 'fallback-line'
    # 整轮正文落盘：带标题的就是预问诊记录，医生端按小结展示
    if _recorder and sessionid and reply:
        try:
            _recorder.record_reply(sessionid, reply, used, _is_silent(datainfo))
        except Exception:  # noqa: BLE001
            logger.exception('record reply failed')
    # 告诉前端“本轮回复结束”，用于把对话从“思考中”切回“可继续聆听”
    _notify(avatar_session, {'status': 'llm_done', 'provider': used, 'silent': _is_silent(datainfo)})
