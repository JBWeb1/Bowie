"""Convert requests, responses and streams between the Anthropic Messages
format and the OpenAI Chat Completions format.

Streams are handled as iterators of parsed SSE payloads (dicts) in, and
iterators of (event_name, payload) out, so the server only deals with
framing.
"""

import json
import time
import uuid

# ---------------------------------------------------------------- requests


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content or [] if b.get("type") == "text")


def _anthropic_image_to_openai(block: dict) -> dict:
    src = block.get("source", {})
    if src.get("type") == "base64":
        url = f"data:{src.get('media_type', 'image/png')};base64,{src.get('data', '')}"
    else:
        url = src.get("url", "")
    return {"type": "image_url", "image_url": {"url": url}}


def anthropic_to_openai_request(body: dict, model: str, max_tokens_cap: int | None = None) -> dict:
    messages = []
    system = body.get("system")
    if system:
        messages.append({"role": "system", "content": _text_of(system)})

    for msg in body.get("messages", []):
        role, content = msg["role"], msg.get("content")
        if role == "system":  # mid-conversation system message
            messages.append({"role": "system", "content": _text_of(content)})
            continue
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue
        if role == "assistant":
            text = _text_of(content)
            calls = [
                {"id": b["id"], "type": "function",
                 "function": {"name": b["name"], "arguments": json.dumps(b.get("input", {}))}}
                for b in content if b.get("type") == "tool_use"
            ]
            out = {"role": "assistant", "content": text or None}
            if calls:
                out["tool_calls"] = calls
            messages.append(out)
            continue
        # user: tool results become role "tool" messages, which must come first
        parts = []
        for b in content:
            kind = b.get("type")
            if kind == "tool_result":
                result = b.get("content", "")
                result = result if isinstance(result, str) else _text_of(result)
                if b.get("is_error"):
                    result = f"[error] {result}"
                messages.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": result})
            elif kind == "text":
                parts.append({"type": "text", "text": b["text"]})
            elif kind == "image":
                parts.append(_anthropic_image_to_openai(b))
        if parts:
            only_text = all(p["type"] == "text" for p in parts)
            messages.append({"role": "user",
                             "content": "".join(p["text"] for p in parts) if only_text else parts})

    out = {"model": model, "messages": messages}
    max_tokens = body.get("max_tokens")
    if max_tokens:
        out["max_tokens"] = min(max_tokens, max_tokens_cap) if max_tokens_cap else max_tokens
    for src, dst in (("temperature", "temperature"), ("top_p", "top_p"), ("stop_sequences", "stop")):
        if src in body:
            out[dst] = body[src]

    tools = [
        {"type": "function", "function": {
            "name": t["name"], "description": t.get("description", ""),
            "parameters": t.get("input_schema", {"type": "object", "properties": {}})}}
        for t in body.get("tools", []) if "input_schema" in t  # server tools have no schema; drop them
    ]
    if tools:
        out["tools"] = tools
        choice = body.get("tool_choice", {}).get("type")
        if choice == "any":
            out["tool_choice"] = "required"
        elif choice == "tool":
            out["tool_choice"] = {"type": "function", "function": {"name": body["tool_choice"]["name"]}}
        elif choice == "none":
            out["tool_choice"] = "none"
    if body.get("stream"):
        out["stream"] = True
        out["stream_options"] = {"include_usage": True}
    return out


def _openai_part_to_anthropic(part: dict) -> dict | None:
    if part.get("type") == "text":
        return {"type": "text", "text": part["text"]}
    if part.get("type") == "image_url":
        url = part["image_url"]["url"] if isinstance(part["image_url"], dict) else part["image_url"]
        if url.startswith("data:"):
            header, data = url.split(",", 1)
            return {"type": "image", "source": {
                "type": "base64", "media_type": header[5:].split(";")[0], "data": data}}
        return {"type": "image", "source": {"type": "url", "url": url}}
    return None


def _parse_args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {"value": value}
    except json.JSONDecodeError:
        return {"_raw_arguments": raw}


def openai_to_anthropic_request(body: dict, model: str, max_tokens_cap: int | None = None) -> dict:
    system, messages = [], []

    def push(role, blocks):
        # Anthropic wants alternating roles; merge consecutive same-role messages
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"].extend(blocks)
        else:
            messages.append({"role": role, "content": blocks})

    for msg in body.get("messages", []):
        role, content = msg["role"], msg.get("content")
        if role in ("system", "developer"):
            system.append(content if isinstance(content, str) else _text_of(content))
        elif role == "tool":
            text = content if isinstance(content, str) else _text_of(content)
            push("user", [{"type": "tool_result", "tool_use_id": msg["tool_call_id"], "content": text}])
        elif role == "assistant":
            blocks = []
            text = content if isinstance(content, str) else _text_of(content or [])
            if text:
                blocks.append({"type": "text", "text": text})
            for call in msg.get("tool_calls") or []:
                fn = call["function"]
                blocks.append({"type": "tool_use", "id": call["id"], "name": fn["name"],
                               "input": _parse_args(fn.get("arguments"))})
            if blocks:
                push("assistant", blocks)
        else:
            if isinstance(content, str):
                blocks = [{"type": "text", "text": content}]
            else:
                blocks = [b for b in map(_openai_part_to_anthropic, content or []) if b]
            push("user", blocks)

    requested = body.get("max_completion_tokens") or body.get("max_tokens") or 16_000
    out = {"model": model, "messages": messages,
           "max_tokens": min(requested, max_tokens_cap) if max_tokens_cap else requested}
    if system:
        out["system"] = "\n\n".join(system)
    stop = body.get("stop")
    if stop:
        out["stop_sequences"] = [stop] if isinstance(stop, str) else stop
    effort = body.get("reasoning_effort")
    if effort in ("low", "medium", "high"):
        out["output_config"] = {"effort": effort}
    # Sampling params are dropped: current Claude models reject non-default values.

    tools = [
        {"name": t["function"]["name"], "description": t["function"].get("description", ""),
         "input_schema": t["function"].get("parameters") or {"type": "object", "properties": {}}}
        for t in body.get("tools", []) if t.get("type") == "function"
    ]
    if tools:
        out["tools"] = tools
        choice = body.get("tool_choice")
        # Forced tool choice ("required"/named) 400s on current Claude models; "auto" is the safe mapping.
        if choice == "none":
            out["tool_choice"] = {"type": "none"}
    if body.get("stream"):
        out["stream"] = True
    return out


# --------------------------------------------------------------- responses

_OPENAI_TO_ANTHROPIC_STOP = {"stop": "end_turn", "length": "max_tokens",
                             "tool_calls": "tool_use", "function_call": "tool_use",
                             "content_filter": "refusal"}
_ANTHROPIC_TO_OPENAI_STOP = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length",
                             "tool_use": "tool_calls", "refusal": "content_filter",
                             "pause_turn": "stop", "model_context_window_exceeded": "length"}


def _msg_id() -> str:
    return f"msg_{uuid.uuid4().hex[:24]}"


def openai_to_anthropic_response(resp: dict, model: str) -> dict:
    choice = (resp.get("choices") or [{}])[0]
    msg = choice.get("message", {})
    content = []
    if msg.get("content"):
        content.append({"type": "text", "text": msg["content"]})
    for call in msg.get("tool_calls") or []:
        content.append({"type": "tool_use", "id": call["id"], "name": call["function"]["name"],
                        "input": _parse_args(call["function"].get("arguments"))})
    usage = resp.get("usage") or {}
    return {
        "id": _msg_id(), "type": "message", "role": "assistant", "model": model,
        "content": content,
        "stop_reason": _OPENAI_TO_ANTHROPIC_STOP.get(choice.get("finish_reason"), "end_turn"),
        "stop_sequence": None,
        "usage": {"input_tokens": usage.get("prompt_tokens", 0),
                  "output_tokens": usage.get("completion_tokens", 0)},
    }


def anthropic_to_openai_response(msg: dict, model: str) -> dict:
    text, calls = [], []
    for b in msg.get("content", []):
        if b.get("type") == "text":
            text.append(b["text"])
        elif b.get("type") == "tool_use":
            calls.append({"id": b["id"], "type": "function",
                          "function": {"name": b["name"], "arguments": json.dumps(b.get("input", {}))}})
    message = {"role": "assistant", "content": "".join(text) or None}
    if calls:
        message["tool_calls"] = calls
    usage = msg.get("usage") or {}
    inp = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}", "object": "chat.completion",
        "created": int(time.time()), "model": model,
        "choices": [{"index": 0, "message": message,
                     "finish_reason": _ANTHROPIC_TO_OPENAI_STOP.get(msg.get("stop_reason"), "stop")}],
        "usage": {"prompt_tokens": inp, "completion_tokens": usage.get("output_tokens", 0),
                  "total_tokens": inp + usage.get("output_tokens", 0)},
    }


# ----------------------------------------------------------------- streams


def openai_stream_to_anthropic(chunks, model: str):
    """chunks: parsed OpenAI stream payloads. Yields (event, data) Anthropic SSE pairs."""
    yield "message_start", {"type": "message_start", "message": {
        "id": _msg_id(), "type": "message", "role": "assistant", "model": model, "content": [],
        "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 0, "output_tokens": 0}}}

    index = -1
    open_kind = None          # "text" or ("tool", openai_tool_index)
    finish = None
    usage = {}

    def close():
        nonlocal open_kind
        if open_kind is not None:
            open_kind = None
            return [("content_block_stop", {"type": "content_block_stop", "index": index})]
        return []

    for chunk in chunks:
        if chunk.get("usage"):
            usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("content"):
                if open_kind != "text":
                    yield from close()
                    index += 1
                    open_kind = "text"
                    yield "content_block_start", {"type": "content_block_start", "index": index,
                                                  "content_block": {"type": "text", "text": ""}}
                yield "content_block_delta", {"type": "content_block_delta", "index": index,
                                              "delta": {"type": "text_delta", "text": delta["content"]}}
            for call in delta.get("tool_calls") or []:
                key = ("tool", call.get("index", 0))
                if open_kind != key:
                    yield from close()
                    index += 1
                    open_kind = key
                    fn = call.get("function") or {}
                    yield "content_block_start", {"type": "content_block_start", "index": index,
                                                  "content_block": {"type": "tool_use",
                                                                    "id": call.get("id") or f"toolu_{uuid.uuid4().hex[:24]}",
                                                                    "name": fn.get("name", ""), "input": {}}}
                args = (call.get("function") or {}).get("arguments")
                if args:
                    yield "content_block_delta", {"type": "content_block_delta", "index": index,
                                                  "delta": {"type": "input_json_delta", "partial_json": args}}
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]

    yield from close()
    yield "message_delta", {"type": "message_delta",
                            "delta": {"stop_reason": _OPENAI_TO_ANTHROPIC_STOP.get(finish, "end_turn"),
                                      "stop_sequence": None},
                            "usage": {"input_tokens": usage.get("prompt_tokens", 0),
                                      "output_tokens": usage.get("completion_tokens", 0)}}
    yield "message_stop", {"type": "message_stop"}


def anthropic_stream_to_openai(events, model: str, include_usage: bool = False):
    """events: parsed Anthropic SSE payloads. Yields OpenAI chunk dicts (caller adds [DONE])."""
    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    def chunk(delta, finish=None):
        return {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}

    tool_index = {}   # anthropic block index -> openai tool index
    input_tokens = output_tokens = 0
    for ev in events:
        kind = ev.get("type")
        if kind == "message_start":
            u = ev["message"].get("usage", {})
            input_tokens = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                            + u.get("cache_creation_input_tokens", 0))
            yield chunk({"role": "assistant", "content": ""})
        elif kind == "content_block_start" and ev["content_block"].get("type") == "tool_use":
            block = ev["content_block"]
            tool_index[ev["index"]] = len(tool_index)
            yield chunk({"tool_calls": [{"index": tool_index[ev["index"]], "id": block["id"], "type": "function",
                                         "function": {"name": block["name"], "arguments": ""}}]})
        elif kind == "content_block_delta":
            d = ev["delta"]
            if d.get("type") == "text_delta":
                yield chunk({"content": d["text"]})
            elif d.get("type") == "input_json_delta" and ev["index"] in tool_index:
                yield chunk({"tool_calls": [{"index": tool_index[ev["index"]],
                                             "function": {"arguments": d["partial_json"]}}]})
        elif kind == "message_delta":
            output_tokens = ev.get("usage", {}).get("output_tokens", output_tokens)
            stop = ev.get("delta", {}).get("stop_reason")
            yield chunk({}, _ANTHROPIC_TO_OPENAI_STOP.get(stop, "stop"))
        elif kind == "error":
            raise UpstreamStreamError(ev.get("error", {}).get("message", "upstream stream error"))
    if include_usage:
        yield {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [],
               "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens,
                         "total_tokens": input_tokens + output_tokens}}


class UpstreamStreamError(Exception):
    pass
