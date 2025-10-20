# snapshot_runtime.py  — DOM+AX snapshot with ARIA fallback and "min==[]" guard
import json, time
from pathlib import Path
from typing import Any, Dict, List, Optional
from rapidfuzz import fuzz

def _uid() -> str:
    import uuid as _u; return str(_u.uuid4())[:8]

def _str_or_none(x):
    if x is None: return None
    s = str(x).strip()
    return s if s else None

def _is_visible_like(node: Dict) -> bool:
    style = node.get("style") or {}
    if style.get("display") == "none" or style.get("visibility") == "hidden":
        return False
    b = node.get("bbox") or {}
    w, h = float(b.get("width", 0) or 0), float(b.get("height", 0) or 0)
    return w >= 1 and h >= 1

def _preferred_selector(tag: str, attrs: Dict, css: Optional[str]) -> Optional[str]:
    if attrs.get("aria-label"):
        return f'[aria-label="{attrs["aria-label"]}"]'
    if tag == "input" and attrs.get("name"):
        return f'input[name="{attrs["name"]}"]'
    if tag == "a" and attrs.get("href"):
        return f'a[href="{attrs["href"]}"]'
    if css:
        return css
    return None

def _aria_selector(role: Optional[str], name: Optional[str]) -> Optional[str]:
    if not role or not name: return None
    return f"aria://{str(role).strip().lower()}::{str(name).strip()}"

DOM_SNAPSHOT_JS = """
() => {
  const isEl = (n) => n && n.nodeType === Node.ELEMENT_NODE;
  const rect = (el) => { try { const r = el.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height}; } catch(e){ return null; } };
  const cssPath = (el) => {
    if (!isEl(el)) return null;
    const path = [];
    while (el && isEl(el)) {
      let selector = el.nodeName.toLowerCase();
      if (el.id) { selector += '#' + el.id; path.unshift(selector); break; }
      let i=1, sib=el.previousElementSibling;
      while (sib) { if (sib.nodeName===el.nodeName) i++; sib=sib.previousElementSibling; }
      selector += `:nth-of-type(${i})`;
      path.unshift(selector);
      el = el.parentElement;
    }
    return path.join(' > ');
  };
  const xPath = (el) => {
    if (!isEl(el)) return null;
    const segs=[]; 
    while (el && el.nodeType===1) {
      let i=1, sib=el.previousSibling;
      while (sib) { if (sib.nodeType===1 && sib.nodeName===el.nodeName) i++; sib=sib.previousSibling; }
      segs.unshift(el.nodeName.toLowerCase()+'['+i+']');
      el=el.parentNode;
    }
    return '/'+segs.join('/');
  };
  const textish = (el) => {
    if (!isEl(el)) return null;
    let t = (el.innerText||'').trim();
    if (!t) t = (el.getAttribute('aria-label')||'').trim();
    if (!t) t = (el.getAttribute('title')||'').trim();
    return t || null;
  };
  const getComputed = (el)=>{ try { return window.getComputedStyle(el); } catch(e){ return null; } };

  const take = (doc, framePath=[]) => {
    const out=[];
    const all = doc.querySelectorAll('*');
    for (const el of all) {
      const cs = getComputed(el);
      const node = {
        tag: el.tagName.toLowerCase(),
        id_attr: el.id || null,
        classes: el.className ? String(el.className).split(/\\s+/).filter(Boolean) : [],
        role_attr: el.getAttribute('role') || null,
        name: textish(el),
        attrs: {},
        style: cs ? {display: cs.display, visibility: cs.visibility, opacity: cs.opacity} : {},
        bbox: rect(el),
        css: cssPath(el),
        xpath: xPath(el),
        frame_path: framePath.slice(),
        shadow_path: null
      };
      for (const a of (el.getAttributeNames?.()||[])) {
        if (['class','id','style'].includes(a)) continue;
        node.attrs[a] = el.getAttribute(a);
      }
      out.push(node);
      if (el.shadowRoot) {
        const sAll = el.shadowRoot.querySelectorAll('*');
        for (const s of sAll) {
          const cs2 = getComputed(s);
          const node2 = {
            tag: s.tagName.toLowerCase(),
            id_attr: s.id || null,
            classes: s.className ? String(s.className).split(/\\s+/).filter(Boolean) : [],
            role_attr: s.getAttribute('role') || null,
            name: textish(s),
            attrs: {},
            style: cs2 ? {display: cs2.display, visibility: cs2.visibility, opacity: cs2.opacity} : {},
            bbox: rect(s),
            css: cssPath(s),
            xpath: xPath(s),
            frame_path: framePath.slice(),
            shadow_path: [node.css || node.tag]
          };
          for (const a of (s.getAttributeNames?.()||[])) {
            if (['class','id','style'].includes(a)) continue;
            node2.attrs[a] = s.getAttribute(a);
          }
          out.push(node2);
        }
      }
    }
    return out;
  };

  const result = { frames: [] };
  result.frames.push({ frame_path: [], nodes: take(document) });
  const iframes = Array.from(document.querySelectorAll('iframe'));
  let idx=0;
  for (const f of iframes) {
    try {
      if (!f.contentDocument) continue;
      const fp = ['iframe', idx++];
      result.frames.push({ frame_path: fp, nodes: take(f.contentDocument, fp) });
    } catch(e) {}
  }
  return result;
}
"""

INTERACTIVE_ROLES = {"button","link","textbox","checkbox","radio","combobox","menuitem","switch","tab","listbox","option"}
INTERACTIVE_TAGS  = {"input","button","a","select","textarea","label"}

def _is_interactive(e: Dict) -> bool:
    if not _is_visible_like(e): return False
    tag = (e.get("tag") or "").lower()
    role_attr = (e.get("role_attr") or e.get("attrs",{}).get("role") or "").lower()
    attrs = e.get("attrs") or {}
    role_hit = role_attr in INTERACTIVE_ROLES
    tag_hit  = tag in INTERACTIVE_TAGS
    span_linkish = (tag == "span" and role_attr == "link")
    clickable_attrs = any(k in attrs for k in ["aria-label","tabindex","onclick","href","type","data-react-aria-pressable"])
    provider = any((k or "").startswith("data-social") for k in (attrs.keys() or []))
    return role_hit or tag_hit or span_linkish or clickable_attrs or provider

def snapshot_page(page, out_dir: Path, label: str = "step"):
    """在*目前的 page* 上擷取一次快照，輸出 full 與 min 兩份 JSON + 截圖。"""
    out_dir.mkdir(parents=True, exist_ok=True)

    # 降低拍到 loading 畫面的機率
    try:
        page.wait_for_load_state("networkidle", timeout=4000)
    except Exception:
        pass

    ts = int(time.time())
    png_name = f"screenshot_{label}_{ts}.png"
    page.screenshot(path=str(out_dir / png_name), full_page=False)

    # AX
    ax_root = page.accessibility.snapshot(root=page.locator("html").element_handle(), interesting_only=False)
    ax_flat = []
    def _flatten_ax(ax_node, acc, frame_path):
        if not ax_node: return
        acc.append({
            "role": ax_node.get("role"), "name": ax_node.get("name"),
            "description": ax_node.get("description"),
            "focused": ax_node.get("focused"), "selected": ax_node.get("selected"),
            "checked": ax_node.get("checked"), "pressed": ax_node.get("pressed"),
            "disabled": ax_node.get("disabled"), "expanded": ax_node.get("expanded"),
            "focusable": ax_node.get("focusable"), "frame_path": frame_path[:], "bbox": None
        })
        for c in ax_node.get("children", []) or []:
            _flatten_ax(c, acc, frame_path)
    _flatten_ax(ax_root, ax_flat, frame_path=[])

    # DOM
    dom_raw = page.evaluate(DOM_SNAPSHOT_JS)
    dom_nodes = []
    for frame in dom_raw.get("frames", []):
        fp = frame.get("frame_path") or []
        for n in frame.get("nodes", []):
            n["name"] = _str_or_none(n.get("name"))
            n["frame_path"] = fp
            n["uid"] = _uid()
            n["role"] = n.get("role_attr") or n.get("attrs",{}).get("role")
            n["visible_like"] = _is_visible_like(n)
            dom_nodes.append(n)

    # align AX -> DOM（文字近似 + 角色 bonus）
    ax2dom = {}
    cand_idx = [i for i, dn in enumerate(dom_nodes) if _is_visible_like(dn)]
    for ai, ax in enumerate(ax_flat):
        ax_name = _str_or_none(ax.get("name")) or _str_or_none(ax.get("description")) or ""
        same_frame = [i for i in cand_idx if dom_nodes[i].get("frame_path") == ax.get("frame_path")]
        best, best_s = None, -1.0
        for i in same_frame:
            dn = dom_nodes[i]
            dn_text = dn.get("name") or ""
            text_s = fuzz.token_set_ratio(ax_name, dn_text)/100.0 if (ax_name or dn_text) else 0.0
            role_bonus = 0.1 if (ax.get("role") and (ax.get("role")==dn.get("role_attr") or ax.get("role")==dn.get("attrs",{}).get("role"))) else 0.0
            sc = 0.85*text_s + 0.15*role_bonus
            if sc > best_s:
                best, best_s = i, sc
        if best is not None and best_s >= 0.5:
            ax2dom[ai] = best

    # build full
    full_elems = []
    for i, dn in enumerate(dom_nodes):
        rec = {
            "uid": dn["uid"], "tag": dn.get("tag"), "role": dn.get("role"),
            "name": dn.get("name"), "attrs": dn.get("attrs", {}),
            "css": dn.get("css"), "xpath": dn.get("xpath"),
            "bbox": dn.get("bbox"), "visible": dn.get("visible_like"),
            "style": dn.get("style", {}), "frame_path": dn.get("frame_path"),
            "shadow_path": dn.get("shadow_path"), "ax": None,
            "selector_pref": None
        }
        rec["selector_pref"] = _preferred_selector((rec["tag"] or ""), (rec["attrs"] or {}), rec["css"])
        full_elems.append(rec)
    for ai, di in ax2dom.items():
        ax = ax_flat[ai]
        full_elems[di]["ax"] = {"role": ax.get("role"), "name": ax.get("name"), "description": ax.get("description")}

    # minimal（DOM 為主）
    minimal: List[Dict[str, Any]] = []
    seen = set()
    for e in full_elems:
        if not _is_interactive(e):
            continue
        tag = (e.get("tag") or "").lower()
        role = (e.get("role") or (e.get("ax") or {}).get("role") or None)
        name = e.get("name") or (e.get("ax") or {}).get("name") or ""
        pref = e.get("selector_pref") or _preferred_selector(tag, e.get("attrs") or {}, e.get("css"))
        item = {
            "uid": e["uid"], "role": role, "tag": tag, "name": name[:140],
            "selector_pref": pref, "bbox": e.get("bbox"),
            "frame_path": e.get("frame_path"), "shadow_path": e.get("shadow_path")
        }
        key = (item["role"], item["name"], item["selector_pref"])
        if key in seen:
            continue
        seen.add(key)
        minimal.append(item)

    # AX-only fallback：把對不到 DOM 的 AX 節點也加進 minimal（用 aria://role::name）
    for ai, ax in enumerate(ax_flat):
        if ai in ax2dom:
            continue
        ax_role = (ax.get("role") or "").lower()
        ax_name = (ax.get("name") or "").strip()
        if not ax_role or not ax_name:
            continue
        if ax_role not in {"button","link","textbox","combobox","tab","menuitem","checkbox","radio","listbox","option"}:
            continue
        item = {
            "uid": f"ax-{ai}",
            "role": ax_role,
            "tag": None,
            "name": ax_name[:140],
            "selector_pref": _aria_selector(ax_role, ax_name),
            "bbox": None,
            "frame_path": ax.get("frame_path") or [],
            "shadow_path": None
        }
        key = (item["role"], item["name"], item["selector_pref"])
        if key in seen:
            continue
        seen.add(key)
        minimal.append(item)

    # 保底：若 minimal 仍為空，挑幾個顯著的 button/a/input 當候選
    if not minimal and full_elems:
        cands = []
        for e in full_elems:
            tag = (e.get("tag") or "").lower()
            if tag not in {"button","a","input"}:
                continue
            b = e.get("bbox") or {}
            area = max(0, (b.get("width") or 0)) * max(0, (b.get("height") or 0))
            y = b.get("y", 1e9)
            name = e.get("name") or (e.get("ax") or {}).get("name") or ""
            if not name:
                continue
            cands.append((-area, y, e))
        for _, _, e in sorted(cands)[:10]:
            item = {
                "uid": e["uid"], "role": (e.get("role") or (e.get("ax") or {}).get("role")),
                "tag": (e.get("tag") or "").lower(),
                "name": (e.get("name") or (e.get("ax") or {}).get("name") or "")[:140],
                "selector_pref": e.get("selector_pref") or _preferred_selector((e.get("tag") or ""), (e.get("attrs") or {}), e.get("css")),
                "bbox": e.get("bbox"),
                "frame_path": e.get("frame_path"),
                "shadow_path": e.get("shadow_path")
            }
            minimal.append(item)

    meta = {"url": page.url, "timestamp": ts, "viewport": page.viewport_size, "screenshot": png_name}
    full_json = {"meta": meta, "elements": full_elems}
    min_json  = {"meta": meta, "elements_min": minimal}

    (out_dir / f"element_index_{label}_{ts}.json").write_text(json.dumps(full_json, ensure_ascii=False, indent=2), "utf-8")
    (out_dir / f"element_index_min_{label}_{ts}.json").write_text(json.dumps(min_json, ensure_ascii=False, indent=2), "utf-8")
    return min_json, full_json, png_name
