"""大模型接入：默认走本机 Ollama，也支持任意 OpenAI 兼容接口。

设计原则：
- 模型只负责“把数据库事实讲成人话”，事实由后端查询后放进提示词，避免模型编造业务数据；
- 没配置/连不上/超时都返回明确错误，助手自动退回规则问答，不影响核心业务。
"""
import json
import time

import requests
from flask import current_app

MAX_FACTS_CHARS = 4000


class LLMError(RuntimeError):
    pass


def _cfg():
    c = current_app.config
    return {
        "enabled": bool(c.get("LLM_ENABLED", True)),
        "provider": (c.get("LLM_PROVIDER") or "ollama").lower(),
        "base": (c.get("LLM_BASE_URL") or "").rstrip("/"),
        "model": c.get("LLM_MODEL") or "",
        "key": c.get("LLM_API_KEY") or "",
        "timeout": int(c.get("LLM_TIMEOUT") or 120),
    }


def status():
    """返回给页面显示的模型状态，不会抛异常。"""
    cfg = _cfg()
    info = {"enabled": cfg["enabled"], "provider": cfg["provider"], "model": cfg["model"],
            "base": cfg["base"], "ready": False, "detail": ""}
    if not cfg["enabled"]:
        info["detail"] = "已在配置中关闭"
        return info
    if cfg["provider"] == "ollama":
        try:
            r = requests.get(cfg["base"] + "/api/tags", timeout=3)
            names = [m.get("name", "") for m in r.json().get("models", [])]
            info["ready"] = any(n == cfg["model"] or n.startswith(cfg["model"] + ":") for n in names)
            info["detail"] = "本地模型已就绪" if info["ready"] else f"Ollama 中未找到模型 {cfg['model']}"
            info["models"] = names[:12]
        except Exception as e:
            info["detail"] = f"连接 Ollama 失败：{type(e).__name__}"
    else:
        info["ready"] = bool(cfg["base"] and cfg["model"] and cfg["key"])
        info["detail"] = "OpenAI 兼容接口" if info["ready"] else "缺少 base_url / model / api_key"
    return info


def chat(messages, timeout=None, temperature=0.2, max_tokens=600):
    """发一次对话请求，返回字符串；失败抛 LLMError。"""
    cfg = _cfg()
    if not cfg["enabled"]:
        raise LLMError("未启用大模型")
    timeout = timeout or cfg["timeout"]
    if cfg["provider"] == "ollama":
        payload = {"model": cfg["model"], "messages": messages, "stream": False,
                   "options": {"temperature": temperature, "num_predict": max_tokens}}
        if cfg["model"].lower().startswith("qwen3"):
            payload["think"] = False  # 关闭思考链，问答更快、更直接
        url = cfg["base"] + "/api/chat"
        headers = {}
    else:
        payload = {"model": cfg["model"], "messages": messages, "temperature": temperature,
                   "max_tokens": max_tokens}
        url = cfg["base"] + "/chat/completions"
        headers = {"Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        raise LLMError(f"调用模型失败：{type(e).__name__}")
    if r.status_code != 200:
        raise LLMError(f"模型返回 HTTP {r.status_code}")
    try:
        data = r.json()
        if cfg["provider"] == "ollama":
            text = (data.get("message") or {}).get("content", "")
        else:
            text = data["choices"][0]["message"]["content"]
    except Exception:
        raise LLMError("模型返回格式无法解析")
    text = (text or "").strip()
    if not text:
        raise LLMError("模型返回空内容")
    return text


SYSTEM_PROMPT = (
    "你是“陈皮柑果园智慧管理系统”的业务助手。"
    "你只能依据用户消息中给出的【数据库事实】回答，不能编造任何数量、名称、日期或结论。"
    "如果事实里没有相关信息，就直接说“当前数据库里没有这项数据”，并给出可以查询的方向。"
    "回答用简洁中文，必要时用短列表；不要输出 Markdown 表格，不要重复问题。"
)


def ask(question, facts):
    """把数据库事实和问题一起交给模型，返回回答文本。"""
    facts = (facts or "（没有检索到结构化事实）")[:MAX_FACTS_CHARS]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"【数据库事实】\n{facts}\n\n【用户问题】\n{question}"},
    ]
    return chat(messages)


def warm():
    """预热模型（首次加载可能要几十秒），失败不影响业务。"""
    try:
        chat([{"role": "user", "content": "回复“就绪”两个字"}], timeout=180, max_tokens=8)
        return True
    except LLMError:
        return False
