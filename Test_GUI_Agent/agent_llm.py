# # agent_llm.py
# import os, json
# from typing import Dict, Any, List
# from openai import OpenAI

# MODEL = os.getenv("GUI_AGENT_MODEL", "gpt-4o-mini")

# SYSTEM_PROMPT = """You are a careful GUI Agent planner.

# You receive:
# 1) A user instruction (natural language).
# 2) A compact element index from DOM+AX trees (each element has uid, role, tag, name, selector_pref, bbox).

# Return ONLY a JSON object with a list of steps to complete the task.

# Rules:
# - Only plan actions for elements that EXIST in the provided element_index_min (match by name text, role).
# - Prefer elements whose role and name best match the intent. Be robust to case and whitespace.
# - If the instruction says "click Continue", DO NOT pick social-login buttons like "Continue with Google/Facebook/Apple" unless the provider is explicitly mentioned.
# - Correct obvious typos in the user's instruction (e.g., "lean" -> "learn") when matching elements.
# - For typing, target textboxes/inputs by names like "Email address" or "Password".
# - For clicks, prefer role=button/link with exact or near-exact name match like "Continue", "Learn".
# - If multiple candidates exist, choose the one likely near the main form or current focus (no need to explain).
# - Supported actions: type, click, wait_url_contains, end.
# - Output must be a valid JSON object following: { "steps": [ ... ] } (no prose).
# """

# def _short_element_view(elements_min: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
#     out = []
#     for e in elements_min:
#         out.append({
#             "uid": e.get("uid"),
#             "role": e.get("role"),
#             "tag": e.get("tag"),
#             "name": e.get("name"),
#             "selector_pref": e.get("selector_pref"),
#             "bbox": e.get("bbox"),
#             "frame_path": e.get("frame_path"),
#             "shadow_path": e.get("shadow_path"),
#         })
#     return out

# def plan_actions(user_prompt: str, element_index_min: Dict[str, Any], email_value: str = "", extra_vars: Dict[str, str] = None) -> Dict[str, Any]:
#     client = OpenAI()
#     elements_min = element_index_min["elements_min"]
#     compact = _short_element_view(elements_min)
#     user_vars = {"EMAIL": email_value}
#     if extra_vars:
#         user_vars.update(extra_vars)

#     messages = [
#         {"role": "system", "content": SYSTEM_PROMPT},
#         {"role": "user", "content": json.dumps({
#             "instruction": user_prompt,
#             "user_vars": user_vars,
#             "element_index_min": compact
#         })}
#     ]

#     resp = client.chat.completions.create(
#         model=MODEL,
#         messages=messages,
#         temperature=0.0,
#         response_format={"type": "json_object"},
#     )
#     content = resp.choices[0].message.content
#     try:
#         plan = json.loads(content)
#         if not isinstance(plan, dict) or "steps" not in plan:
#             return {"steps": []}
#         return plan
#     except Exception:
#         return {"steps": []}
# agent_llm.py — LLM 規劃器（含 value->text 正規化）
from __future__ import annotations
import os, json
from typing import Dict, Any, List, Optional
from openai import OpenAI

MODEL = os.getenv("GUI_AGENT_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT = """You are a careful GUI Agent planner.

You receive:
1) A user instruction (natural language).
2) A compact element index from DOM+AX trees (each element has uid, role, tag, name, selector_pref, bbox).

Return ONLY a JSON object with a list of steps to complete the task.

Rules:
- Only plan actions for elements that EXIST in the provided element_index_min (match by name text, role).
- Prefer elements whose role and name best match the intent. Be robust to case and whitespace.
- For typing, target textboxes/inputs by names like "Email address" or "Password".
- For clicks, prefer role=button/link with exact or near-exact name match like "Continue", "Learn".
- If multiple candidates exist, choose the one likely near the main form or current focus (no need to explain).
- Supported actions: type, click, wait_url_contains, end.
- IMPORTANT: For typing actions, put the string to type in the 'text' field (NOT 'value').
- Use variables in angle brackets literally (e.g., <EMAIL>) if they appear in the instruction.
- Output must be a valid JSON object following: { "steps": [ ... ] } (no prose)."""

def _short_element_view(elements_min: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in elements_min:
        out.append({
            "uid": e.get("uid"),
            "role": e.get("role"),
            "tag": e.get("tag"),
            "name": e.get("name"),
            "selector_pref": e.get("selector_pref"),
            "bbox": e.get("bbox"),
            "frame_path": e.get("frame_path"),
            "shadow_path": e.get("shadow_path"),
            "selector": e.get("selector"),
        })
    return out


def _normalize_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """把所有 type 步驟的 value -> text，避免執行器漏填"""
    steps = (plan or {}).get("steps")
    if not isinstance(steps, list):
        return {"steps": []}
    for st in steps:
        if isinstance(st, dict) and st.get("action", "").lower() == "type":
            if "text" not in st and "value" in st:
                st["text"] = st.pop("value")
    return {"steps": steps}


def plan_actions(
    user_prompt: str,
    element_index_min: Dict[str, Any],
    email_value: str = "",
    extra_vars: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    用 LLM 產出 {steps:[...]}；會自動正規化 'value' -> 'text'
    """
    client = OpenAI()
    elements_min = element_index_min.get("elements_min") or []
    compact = _short_element_view(elements_min)

    # 讓 prompt 可帶 <EMAIL> 等變數（例如 "Enter <EMAIL> and click Continue"）
    user_vars = {"EMAIL": email_value or ""}
    if extra_vars:
        user_vars.update(extra_vars)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps({
                "instruction": user_prompt,
                "elements_min": compact,
                "hints": {
                    "vars": {k: f"<{k}>" for k in user_vars.keys()}
                }
            }, ensure_ascii=False)
        }
    ]

    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.0,
        response_format={"type": "json_object"},
    )

    content = resp.choices[0].message.content
    try:
        raw_plan = json.loads(content)
    except Exception:
        return {"steps": []}

    # 正規化 plan
    plan = _normalize_plan(raw_plan)
    return plan
