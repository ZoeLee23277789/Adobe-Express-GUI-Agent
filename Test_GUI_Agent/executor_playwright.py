# # executor_playwright.py  — uid/match 兼容 + ARIA-aware + 輸入欄位驗證
# from typing import Dict, Any, List, Optional, Callable
# from math import hypot
# import re
# from playwright.sync_api import Page, TimeoutError as PWTimeout

# # ---------- utils ----------
# def _norm(s: Optional[str]) -> str:
#     return re.sub(r"\s+", " ", (s or "")).strip().lower()

# def _bbox_center(b):
#     return (b["x"] + b["width"]/2, b["y"] + b["height"]/2)

# ARIA_RE = re.compile(r"^aria://(?P<role>[a-zA-Z0-9_-]+)::(?P<name>.+)$")

# def _get_by_role(page: Page, sel: str):
#     m = ARIA_RE.match(sel or "")
#     if not m:
#         return None
#     role = m.group("role")
#     name = m.group("name")
#     # Try exact first; then case-insensitive
#     try:
#         return page.get_by_role(role=role, name=name)
#     except Exception:
#         return page.get_by_role(role=role, name=re.compile(rf"^{re.escape(name)}$", re.I))

# def _is_visible(page: Page, sel: str, timeout_ms: int = 1500) -> bool:
#     if sel and sel.startswith("aria://"):
#         loc = _get_by_role(page, sel)
#         if not loc:
#             return False
#         try:
#             loc.first.wait_for(state="visible", timeout=timeout_ms)
#             return True
#         except PWTimeout:
#             return False
#     try:
#         loc = page.locator(sel).first
#         loc.wait_for(state="attached", timeout=timeout_ms)
#         loc.wait_for(state="visible", timeout=timeout_ms)
#         return True
#     except PWTimeout:
#         return False

# def _is_input_like(el: Dict[str, Any]) -> bool:
#     role = _norm(el.get("role"))
#     tag  = _norm(el.get("tag"))
#     attrs = el.get("attrs") or {}
#     if role == "textbox":
#         return True
#     if tag in {"input","textarea"}:
#         return True
#     # 某些富文本欄位：contenteditable
#     ce = attrs.get("contenteditable")
#     if isinstance(ce, str):
#         ce = ce.lower() in {"", "true"}
#     return bool(ce)

# # ---------- resolver ----------
# def _get_by_uid(elements_min: List[Dict[str, Any]], uid: str) -> Optional[Dict[str, Any]]:
#     for e in elements_min:
#         if e.get("uid") == uid:
#             return e
#     return None

# def resolve_element_by_match(
#     elements_min: List[Dict[str, Any]],
#     match: Dict[str, Any],
#     last_target: Optional[Dict[str, Any]] = None,
#     prefer_roles=("textbox","button","link"),
# ) -> Optional[Dict[str, Any]]:
#     """
#     支援 match 欄位：
#       - text: 目標可見名稱
#       - exact: True → 僅完全相等
#       - not_contains: ["with"] → 排除含關鍵字
#       - role / tag: 希望的 role 或 tag
#     """
#     want_text = _norm(match.get("text", ""))
#     exact = bool(match.get("exact", False))
#     not_contains = [_norm(x) for x in match.get("not_contains", [])]
#     want_role = _norm(match.get("role"))
#     want_tag = _norm(match.get("tag"))

#     cands: List[Dict[str, Any]] = []
#     for el in elements_min:
#         name = _norm(el.get("name"))
#         role = _norm(el.get("role"))
#         tag  = _norm(el.get("tag"))
#         if not name:
#             continue

#         if want_role and role != want_role:
#             continue
#         if want_tag and tag != want_tag:
#             continue

#         if want_text:
#             if exact and name != want_text:
#                 continue
#             if not exact and want_text not in name:
#                 continue

#         if any(neg and neg in name for neg in not_contains):
#             continue

#         cands.append(el)

#     if not cands:
#         return None

#     def rank(el):
#         name = _norm(el.get("name"))
#         role = _norm(el.get("role"))
#         score = 0
#         if want_text:
#             if name == want_text: score += 100
#             elif name.startswith(want_text): score += 50
#             else: score += 20
#         if role in prefer_roles:
#             score += (30 - 10*prefer_roles.index(role))  # textbox(30)>button(20)>link(10)
#         if last_target and el.get("bbox") and last_target.get("bbox"):
#             cx1, cy1 = _bbox_center(el["bbox"]); cx2, cy2 = _bbox_center(last_target["bbox"])
#             d = hypot(cx1 - cx2, cy1 - cy2)
#             score += max(0, 40 - min(d/10, 40))
#         y = (el.get("bbox") or {}).get("y", 1e9)
#         return (-score, y)

#     cands.sort(key=rank)
#     return cands[0]

# def choose_target_for_step(
#     elements_min: List[Dict[str, Any]],
#     step: Dict[str, Any],
#     last_target: Optional[Dict[str, Any]]
# ) -> Optional[Dict[str, Any]]:
#     # 先支援 target.uid（若模型給了）
#     tgt = step.get("target") or {}
#     if "uid" in tgt:
#         el = _get_by_uid(elements_min, tgt["uid"])
#         if el:
#             return el
#     # 否則用 match 規則解
#     match = step.get("match") or {}
#     return resolve_element_by_match(elements_min, match, last_target=last_target)

# # ---------- low-level actions ----------
# def _click_aria(page: Page, sel: str) -> bool:
#     loc = _get_by_role(page, sel)
#     if not loc:
#         return False
#     try:
#         loc.first.click(timeout=2500)
#         return True
#     except Exception:
#         return False

# def _fill_aria(page: Page, sel: str, text: str) -> bool:
#     loc = _get_by_role(page, sel)
#     if not loc:
#         return False
#     try:
#         loc.first.fill(text, timeout=3000)
#         return True
#     except Exception:
#         return False

# def _click(page: Page, el: Dict[str, Any]) -> bool:
#     sel = el.get("selector_pref")
#     if sel:
#         if sel.startswith("aria://"):
#             return _click_aria(page, sel)
#         if not _is_visible(page, sel):
#             return False
#         page.locator(sel).first.click()
#         return True
#     b = el.get("bbox") or {}
#     if not b or b.get("width",0) < 1 or b.get("height",0) < 1:
#         return False
#     x = b["x"] + b["width"]/2
#     y = b["y"] + b["height"]/2
#     page.mouse.click(x, y)
#     return True

# def _type_text(page: Page, el: Dict[str, Any], text: str) -> bool:
#     # 僅允許輸入到 input-like
#     if not _is_input_like(el):
#         return False
#     sel = el.get("selector_pref")
#     if sel:
#         if sel.startswith("aria://"):
#             return _fill_aria(page, sel, text)
#         if not _is_visible(page, sel):
#             return False
#         page.locator(sel).first.fill(text)
#         return True
#     if not _click(page, el):
#         return False
#     page.keyboard.type(text)
#     return True

# # ---------- plan executor ----------
# def run_plan_stepwise(
#     page: Page,
#     element_index_min: Dict[str, Any],
#     plan: Dict[str, Any],
#     user_vars: Dict[str, str] = {},
#     on_after_action: Optional[Callable[[str, Dict[str, Any]], None]] = None
# ) -> bool:
#     """
#     逐步執行計畫；任何一步失敗就回傳 False，讓外層 re-snapshot + re-plan。
#     每個 primitive action 完成後，若提供 on_after_action，就會呼叫它。
#     """
#     elements = element_index_min["elements_min"]
#     last_target: Optional[Dict[str, Any]] = None

#     for step in plan.get("steps", []):
#         action = step.get("action")

#         if action in ("click", "type"):
#             target = choose_target_for_step(elements, step, last_target=last_target)
#             if not target:
#                 print(f"[WARN] no target found for {step.get('match') or step.get('target')}")
#                 if on_after_action: on_after_action("no_target", {})
#                 return False

#             ok = False
#             if action == "click":
#                 ok = _click(page, target)
#                 print(f"[{'OK' if ok else 'FAIL'}] click -> {target.get('name')}")
#             else:
#                 text = step.get("text", "")
#                 for k, v in (user_vars or {}).items():
#                     text = text.replace(f"<{k}>", v)
#                 ok = _type_text(page, target, text)
#                 print(f"[{'OK' if ok else 'FAIL'}] type -> {target.get('name')}: {text}")

#             if on_after_action:
#                 on_after_action(action, target)

#             if not ok:
#                 return False

#             last_target = target

#         elif action == "wait_url_contains":
#             val = step.get("value", "")
#             if val:
#                 page.wait_for_url(lambda url: val in url, timeout=25000)
#                 print(f"[OK] wait_url_contains '{val}'")
#             if on_after_action:
#                 on_after_action(action, {"value": val})

#         elif action == "end":
#             print("[END] Agent done.")
#             return True

#         else:
#             print(f"[INFO] unknown action: {action}")
#             if on_after_action:
#                 on_after_action("unknown", {"step": step})

#     return True
from __future__ import annotations
from typing import Dict, Any, List, Optional, Callable
import re
from math import hypot
from playwright.sync_api import Page, TimeoutError as PWTimeout

# ---------- 小工具 ----------
def _norm(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()

def _bbox_center(bbox: Dict[str, float]) -> tuple[float, float]:
    return (bbox.get("x", 0) + bbox.get("width", 0) / 2.0,
            bbox.get("y", 0) + bbox.get("height", 0) / 2.0)

_ARIA_RE = re.compile(r"^aria://(?P<role>[a-zA-Z0-9_-]+)::(?P<name>.+)$")

# DOEM 風格加權
_PREFER_ROLES = ("textbox", "button", "link")
_NEG_DEFAULT = ["with google", "with apple", "with facebook", "with"]

def _score_text(q: str, t: str) -> float:
    """簡單相似度：完全相等 > 前綴包含 > 一般包含"""
    qn = _norm(q); tn = _norm(t)
    if not qn or not tn:
        return 0.0
    if qn == tn:
        return 1.0
    if tn.startswith(qn):
        return 0.85
    if qn in tn:
        return 0.6
    return 0.0

def _is_blocked(text: str, not_contains: list[str]) -> bool:
    tn = _norm(text)
    for bad in (not_contains or []):
        if _norm(bad) and _norm(bad) in tn:
            return True
    return False

def _rank_candidates(elements_min: list[dict], match: dict, last_target: dict | None):
    """
    依據 match 物件（text/role/exact/not_contains）對當前 elements_min 排序。
    回傳由佳到次的 elements 清單。
    """
    want_text = (match or {}).get("text", "")
    want_role = (match or {}).get("role")
    exact = bool((match or {}).get("exact", False))
    not_contains = ((match or {}).get("not_contains") or []) + _NEG_DEFAULT

    cands = []
    for el in elements_min:
        name = el.get("name") or ""
        role = _norm(el.get("role"))
        if want_role and _norm(want_role) != role:
            # 若指定角色，嚴格比對；若未指定，則放寬
            continue
        if not name:
            continue
        if _is_blocked(name, not_contains):
            continue

        # 文字匹配
        s_txt = _score_text(want_text, name) if want_text else 0.3
        if exact and _norm(want_text) != _norm(name):
            s_txt = 0.0
        if s_txt <= 0.0:
            continue

        # 角色偏好
        s_role = 0.0
        if role in _PREFER_ROLES:
            s_role = 0.3 - 0.1 * _PREFER_ROLES.index(role)

        # 與上一個目標的空間鄰近
        s_near = 0.0
        if last_target and el.get("bbox") and last_target.get("bbox"):
            cx = el["bbox"]["x"] + el["bbox"]["width"] / 2.0
            cy = el["bbox"]["y"] + el["bbox"]["height"] / 2.0
            cx2 = last_target["bbox"]["x"] + last_target["bbox"]["width"] / 2.0
            cy2 = last_target["bbox"]["y"] + last_target["bbox"]["height"] / 2.0
            d = hypot(cx - cx2, cy - cy2)
            s_near = max(0.0, 0.25 - min(d / 1000.0, 0.25))  # 最近 +0.25，越遠越扣

        score = s_txt + s_role + s_near
        cands.append((-score, el))  # 分數越高，負號越小，排序在前

    cands.sort(key=lambda x: x[0])
    return [el for _, el in cands]

def _get_by_role(page: Page, aria_selector: str):
    """把 aria://role::name 轉成 Playwright 的 get_by_role 呼叫"""
    m = _ARIA_RE.match(aria_selector or "")
    if not m:
        return None
    role = m.group("role")
    name = m.group("name")
    try:
        # 先精確比對；失敗則大小寫不敏感
        return page.get_by_role(role=role, name=name)
    except Exception:
        return page.get_by_role(role=role, name=re.compile(rf"^{re.escape(name)}$", re.I))

def _is_visible(page: Page, selector: str, timeout_ms: int = 2000) -> bool:
    """判斷 selector 是否可見（支援 aria:// 與 CSS）"""
    try:
        if selector.startswith("aria://"):
            loc = _get_by_role(page, selector)
        else:
            loc = page.locator(selector).first
        if not loc:
            return False
        loc.wait_for(state="visible", timeout=timeout_ms)
        return True
    except PWTimeout:
        return False
    except Exception:
        return False

def _resolve_target_selector(element: Dict[str, Any]) -> Optional[str]:
    """
    從 elements_min 的單一 element 推導出可點可填的 selector。
    優先順序：
    1) element["selector_pref"]（DOM 快照時算好的）
    2) aria://role::name（若 role/name 存在）
    3) element["selector"]（若有）
    """
    sel = element.get("selector_pref")
    if sel:
        return sel
    role = element.get("role")
    name = element.get("name")
    if role and name:
        return f"aria://{str(role).strip().lower()}::{str(name).strip()}"
    sel = element.get("selector")
    if sel:
        return sel
    return None

def _find_element_by_uid(elements_min: List[Dict[str, Any]], uid: str) -> Optional[Dict[str, Any]]:
    for el in elements_min:
        if el.get("uid") == uid:
            return el
    return None

def _find_by_match(elements_min: List[Dict[str, Any]], role: Optional[str], name: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    允許用 role/name fuzzy 尋找（保守：先 exact，再包含）
    """
    role_n = _norm(role)
    name_n = _norm(name)

    # 先 exact
    for el in elements_min:
        if role_n and _norm(el.get("role")) != role_n:
            continue
        if name_n and _norm(el.get("name")) != name_n:
            continue
        return el

    # 再包含
    for el in elements_min:
        if role_n and _norm(el.get("role")) != role_n:
            continue
        if name_n and name_n not in _norm(el.get("name")):
            continue
        return el
    return None

def _type_text(page: Page, selector: str, text: str) -> None:
    """盡量穩健地在欄位輸入文字：先點、清空、再填"""
    if selector.startswith("aria://"):
        loc = _get_by_role(page, selector)
    else:
        loc = page.locator(selector).first
    if not loc:
        raise RuntimeError(f"locator not found for {selector}")

    loc.scroll_into_view_if_needed()
    # 先 focus
    loc.click(timeout=3000)
    # 清空（對常見 input/textarea 有效）
    try:
        loc.fill("", timeout=2000)
    except Exception:
        pass
    # 輸入
    loc.type(text, delay=20, timeout=5000)

def _click(page: Page, selector: str) -> None:
    if selector.startswith("aria://"):
        loc = _get_by_role(page, selector)
    else:
        loc = page.locator(selector).first
    if not loc:
        raise RuntimeError(f"locator not found for {selector}")
    loc.scroll_into_view_if_needed()
    loc.click(timeout=5000)

# ---------- Home/導航專用 fallback ----------
_NAV_OPENER_NAMES = [
    "Menu", "Main menu", "Navigation", "Open navigation", "More", "More options",
    "Toggle navigation", "Show menu", "Close", "Open"
]
_LOGO_NAMES = [
    "Adobe Express", "Express", "Adobe logo", "Home", "Go to Home"
]

def _try_open_nav_and_retry_home(
    page: Page,
    elements_min: List[Dict[str, Any]],
    home_selector: str
) -> bool:
    # 1) 試著點開導覽選單
    for el in elements_min:
        if _norm(el.get("role")) != "button":
            continue
        if _norm(el.get("name")) in [_norm(n) for n in _NAV_OPENER_NAMES]:
            opener_selector = _resolve_target_selector(el)
            try:
                if opener_selector and _is_visible(page, opener_selector, 1500):
                    _click(page, opener_selector)
                    # 打開後再試一次 Home
                    if _is_visible(page, home_selector, 2000):
                        _click(page, home_selector)
                        return True
            except Exception:
                pass

    # 2) 直接點 logo（多數網站 logo = 回首頁）
    for el in elements_min:
        if _norm(el.get("role")) not in ("link", "img", "button"):
            continue
        if _norm(el.get("name")) in [_norm(n) for n in _LOGO_NAMES]:
            logo_selector = _resolve_target_selector(el)
            try:
                if logo_selector and _is_visible(page, logo_selector, 2000):
                    _click(page, logo_selector)
                    return True
            except Exception:
                pass

    # 3) 退而求其次：找任何 link 且 name 含 home
    for el in elements_min:
        if _norm(el.get("role")) != "link":
            continue
        if "home" in _norm(el.get("name")):
            sel = _resolve_target_selector(el)
            try:
                if sel and _is_visible(page, sel, 2000):
                    _click(page, sel)
                    return True
            except Exception:
                pass

    return False

# ---------- 對外：逐步執行 ----------
def run_plan_stepwise(
    page: Page,
    element_index_min: Dict[str, Any],
    plan: Dict[str, Any],
    user_vars: Optional[Dict[str, str]] = None,
    on_after_action: Optional[Callable[[str, Any], None]] = None,
) -> bool:
    """
    依照 LLM 規劃的 steps 逐步執行。
    支援的 action：
      - type {target, text|value}
      - click {target}
      - wait_url_contains {value/text}
      - end
    target 可為：
      - {"uid": "..."}  （由快照提供）
      - {"role": "...", "name": "..."}  （將會在 elements_min 中以 role/name 搜尋）
      - {"selector": "aria://role::name" 或 CSS selector}
      - {"match": {"text": "...", "role": "button|link|textbox", "exact": bool, "not_contains": [..]}}
      - 也支援 (role,name) 同時帶 not_contains/exact，將改用 match 排序
    """
    elements_min = element_index_min.get("elements_min") or []
    steps = (plan or {}).get("steps") or []

    # 用於空間鄰近加權（上一次選中的元素）
    last_chosen_el: Optional[Dict[str, Any]] = None

    def _after(a: str, tgt: Any):
        if on_after_action:
            try:
                on_after_action(a, tgt)
            except Exception:
                pass

    for step in steps:
        try:
            action = (step or {}).get("action", "").strip().lower()
            if not action:
                continue

            if action == "end":
                return True

            # 兼容 text / value
            text = step.get("text")
            if text is None:
                text = step.get("value", "")

            # 變數替換（<EMAIL> 之類）
            if isinstance(text, str) and user_vars:
                for k, v in user_vars.items():
                    text = text.replace(f"<{k}>", v or "")

            # 解析 target -> selector
            target = (step or {}).get("target") or {}
            selector: Optional[str] = None
            chosen_el: Optional[Dict[str, Any]] = None

            if "selector" in target:
                selector = target["selector"]

            elif "uid" in target:
                chosen_el = _find_element_by_uid(elements_min, target["uid"])
                if not chosen_el:
                    raise RuntimeError(f"uid not found: {target['uid']}")
                selector = _resolve_target_selector(chosen_el)

            elif "match" in target:
                ranked = _rank_candidates(elements_min, target["match"], last_chosen_el)
                if not ranked:
                    raise RuntimeError(f"no candidates for match: {target['match']}")
                chosen_el = ranked[0]
                selector = _resolve_target_selector(chosen_el)

            elif ("role" in target or "name" in target) and ("not_contains" in target or "exact" in target):
                # ★ 新增：當 (role|name) 同時帶有 not_contains/exact，就當成 match 用 DOEM 排序
                m = {
                    "role": target.get("role"),
                    "text": target.get("name") or target.get("text", ""),
                    "exact": bool(target.get("exact", False)),
                    "not_contains": target.get("not_contains", []),
                }
                ranked = _rank_candidates(elements_min, m, last_chosen_el)
                if not ranked:
                    raise RuntimeError(f"no candidates for (role,name)+mask: {m}")
                chosen_el = ranked[0]
                selector = _resolve_target_selector(chosen_el)

            elif "role" in target or "name" in target:
                # 兼容舊格式 (role,name) 無遮罩
                chosen_el = _find_by_match(elements_min, target.get("role"), target.get("name"))
                if not chosen_el:
                    raise RuntimeError(f"role/name not found: {target}")
                selector = _resolve_target_selector(chosen_el)

            else:
                # 沒給 target，容錯：直接使用 aria 名稱（某些 LLM 可能只給 name）
                if step.get("name") and step.get("role"):
                    selector = f"aria://{_norm(step['role'])}::{step['name']}"
                else:
                    raise RuntimeError("missing target in step")

            if not selector:
                raise RuntimeError("selector resolve failed")

            # 具體執行
            if action == "type":
                if not isinstance(text, str):
                    text = "" if text is None else str(text)
                if not _is_visible(page, selector):
                    raise RuntimeError(f"target not visible for type: {selector}")
                _type_text(page, selector, text)
                print(f"[OK] type -> {chosen_el.get('name') if chosen_el else selector}: {text}")
                last_chosen_el = chosen_el or last_chosen_el
                _after("type", target)

            elif action == "click":
                # 點擊前再做一次保險的「負面關鍵字」檢查（若有 name）
                if chosen_el and _is_blocked(chosen_el.get("name", ""), target.get("not_contains", [])):
                    # 嘗試找下一名候選（只在 match/遮罩情境會有 ranked；這裡簡單重新跑一次）
                    m2 = {}
                    if "match" in target:
                        m2 = target["match"]
                    elif "role" in target or "name" in target:
                        m2 = {
                            "role": target.get("role"),
                            "text": target.get("name") or target.get("text", ""),
                            "exact": bool(target.get("exact", False)),
                            "not_contains": target.get("not_contains", []),
                        }
                    if m2:
                        alts = _rank_candidates(elements_min, m2, last_chosen_el)
                        if len(alts) >= 2:
                            chosen_el = alts[1]
                            selector = _resolve_target_selector(chosen_el)

                if not _is_visible(page, selector):
                    # 特判：Home 點不到 → 嘗試展開選單/點 logo 再重試
                    tgt_name = _norm((chosen_el or {}).get("name") or (target.get("match") or {}).get("text") or target.get("name") or "")
                    if "home" in tgt_name:
                        ok = _try_open_nav_and_retry_home(page, elements_min, selector)
                        if ok:
                            print("[OK] click -> Home (via fallback)")
                            last_chosen_el = None
                            _after("click", target)
                            continue
                    raise RuntimeError(f"target not visible for click: {selector}")

                _click(page, selector)
                print(f"[OK] click -> {chosen_el.get('name') if chosen_el else selector}")
                last_chosen_el = chosen_el or last_chosen_el
                _after("click", target)

            elif action == "wait_url_contains":
                want = text or ""
                if not isinstance(want, str) or not want:
                    raise RuntimeError("wait_url_contains requires text/value")
                page.wait_for_url(re.compile(re.escape(want)), timeout=10000)
                print(f"[OK] wait_url_contains -> {want}")
                _after("wait_url_contains", {"value": want})

            else:
                # 未支援 action：忽略但不中斷
                print(f"[SKIP] unsupported action: {action}")
                continue

        except Exception as e:
            print(f"[ERR] {e}")
            return False

    return True
