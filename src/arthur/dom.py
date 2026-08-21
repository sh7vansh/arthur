"""In-page semantic DOM snapshot generator and Ref-ID registry."""

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from arthur.cdp import CDPClient
from arthur.errors import (
    ActionInterceptionError,
    BrowserUnavailableError,
    CDPError,
    ElementNotFoundError,
)

IN_PAGE_DOM_SCRIPT = r"""
((payload) => {


  const INTERACTIVE_ROLES = new Set([
    "button", "link", "checkbox", "radio", "combobox", "textbox",
    "searchbox", "menuitem", "menuitemcheckbox", "menuitemradio",
    "tab", "switch", "slider", "spinbutton", "treeitem", "option"
  ]);

  const IGNORED_TAGS = new Set([
    "SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "SVG", "CANVAS",
    "META", "LINK", "HEAD", "IFRAME", "EMBED", "OBJECT"
  ]);

  function isVisible(el, style) {
    if (el.hasAttribute("hidden")) return false;
    if (el.getAttribute("aria-hidden") === "true") return false;
    if (el.hasAttribute("inert")) return false;

    if (typeof el.checkVisibility === "function") {
      if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) {
        if (el.tagName === "INPUT" && (el.type === "checkbox" || el.type === "radio")) {
          return true;
        }
        return false;
      }
    }

    if (!style) style = window.getComputedStyle(el);
    if (style.display === "none") return false;
    if (style.visibility === "hidden" || style.visibility === "collapse") return false;
    if (parseFloat(style.opacity) < 0.05) return false;

    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) {
      if (el.tagName === "INPUT" && (el.type === "checkbox" || el.type === "radio")) {
        return true;
      }
      return false;
    }
    return true;
  }

  function getAccessibleName(el) {
    const labelledby = el.getAttribute("aria-labelledby");
    if (labelledby) {
      const parts = labelledby.split(/\s+/).map(id => document.getElementById(id)?.innerText?.trim()).filter(Boolean);
      if (parts.length > 0) return parts.join(" ");
    }

    const ariaLabel = el.getAttribute("aria-label");
    if (ariaLabel && ariaLabel.trim()) return ariaLabel.trim();

    if (el.id && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT")) {
      const labelEl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (labelEl && labelEl.innerText.trim()) return labelEl.innerText.trim();
    }
    const parentLabel = el.closest("label");
    if (parentLabel && parentLabel.innerText.trim()) {
      return parentLabel.innerText.trim();
    }

    if (el.getAttribute("placeholder")) return el.getAttribute("placeholder").trim();
    if (el.getAttribute("title")) return el.getAttribute("title").trim();
    if (el.getAttribute("alt")) return el.getAttribute("alt").trim();

    const directText = Array.from(el.childNodes)
      .filter(node => node.nodeType === Node.TEXT_NODE)
      .map(node => node.textContent.trim())
      .filter(Boolean)
      .join(" ");
    if (directText) return directText.slice(0, 120);

    if (["BUTTON", "A", "SUMMARY", "OPTION"].includes(el.tagName)) {
      const fullText = el.innerText?.trim();
      if (fullText) return fullText.slice(0, 120);
    }

    return "";
  }

  function getComputedRole(el) {
    const explicitRole = el.getAttribute("role");
    if (explicitRole) return explicitRole.toLowerCase().trim();

    const tag = el.tagName.toLowerCase();
    switch (tag) {
      case "a": return el.hasAttribute("href") ? "link" : "generic";
      case "button": return "button";
      case "input": {
        const type = (el.getAttribute("type") || "text").toLowerCase();
        if (["button", "submit", "reset", "image"].includes(type)) return "button";
        if (type === "checkbox") return "checkbox";
        if (type === "radio") return "radio";
        if (type === "search") return "searchbox";
        return "textbox";
      }
      case "select": return "combobox";
      case "textarea": return "textbox";
      case "summary": return "button";
      case "details": return "group";
      case "h1": return "heading[level=1]";
      case "h2": return "heading[level=2]";
      case "h3": return "heading[level=3]";
      case "h4": return "heading[level=4]";
      case "h5": return "heading[level=5]";
      case "h6": return "heading[level=6]";
      case "nav": return "navigation";
      case "main": return "main";
      case "header": return "banner";
      case "footer": return "contentinfo";
      case "form": return "form";
      case "table": return "table";
      default: return "generic";
    }
  }

  function isActionable(el, role, style) {
    if (["A", "BUTTON", "SELECT", "TEXTAREA", "DETAILS", "SUMMARY"].includes(el.tagName)) {
      if (el.tagName === "A" && !el.hasAttribute("href")) return false;
      return true;
    }

    if (el.tagName === "INPUT") {
      return (el.getAttribute("type") || "text").toLowerCase() !== "hidden";
    }

    if (INTERACTIVE_ROLES.has(role)) return true;
    if (el.tabIndex >= 0 && el.tagName !== "IFRAME") return true;
    if (el.isContentEditable) return true;
    if (style.cursor === "pointer" && el.children.length === 0) return true;

    return false;
  }

  function generateSnapshot() {
    const root = document.body;
    if (!root) return { snapshot: "Empty Page", totalInteractive: 0, epoch: Date.now() };

    const refMap = new Map();
    const historyMap = window.__ag_history || {};
    let refCounter = 1;
    const lines = [];

    const viewportHeight = window.innerHeight;
    const viewportWidth = window.innerWidth;

    const walker = document.createTreeWalker(
      root,
      NodeFilter.SHOW_ELEMENT,
      {
        acceptNode: (node) => {
          if (IGNORED_TAGS.has(node.tagName)) return NodeFilter.FILTER_REJECT;
          if (node.hasAttribute("hidden") || node.getAttribute("aria-hidden") === "true" || node.hasAttribute("inert")) {
            return NodeFilter.FILTER_REJECT;
          }
          const style = window.getComputedStyle(node);
          if (style.display === "none" || style.visibility === "hidden" || parseFloat(style.opacity) < 0.05) {
            return NodeFilter.FILTER_REJECT;
          }
          return NodeFilter.FILTER_ACCEPT;
        }
      }
    );

    function getNodeDepth(node) {
      let d = 0;
      let cur = node;
      while (cur && cur !== root) {
        d++;
        cur = cur.parentElement;
      }
      return d;
    }

    let currentNode = walker.currentNode;
    while (currentNode) {
      if (currentNode !== root) {
        const node = currentNode;
        const style = window.getComputedStyle(node);
        if (isVisible(node, style)) {
          const role = getComputedRole(node);
          const actionable = isActionable(node, role, style);
          const name = getAccessibleName(node);
          const depth = Math.min(6, getNodeDepth(node));
          const indent = "  ".repeat(depth);

          if (actionable) {
            const refId = refCounter++;
            refMap.set(refId, node);

            historyMap[refId] = {
              ref: `#${refId}`,
              tag: node.tagName.toLowerCase(),
              role: role,
              name: name,
              className: node.className || "",
            };

            const extras = [];
            if (node.tagName === "INPUT" || node.tagName === "TEXTAREA") {
              const inputType = (node.getAttribute("type") || "text").toLowerCase();
              if (inputType !== "checkbox" && inputType !== "radio" && node.value) {
                extras.push(`value="${node.value.slice(0, 50)}"`);
              } else if ((inputType === "checkbox" || inputType === "radio") && node.hasAttribute("value") && node.getAttribute("value") !== "on") {
                extras.push(`value="${node.value.slice(0, 50)}"`);
              }
              if (node.placeholder && node.placeholder !== name) extras.push(`placeholder="${node.placeholder}"`);
            }
            if (node.checked) extras.push("checked");
            if (node.disabled || node.getAttribute("aria-disabled") === "true") extras.push("disabled");
            if (node.hasAttribute("aria-expanded")) extras.push(`expanded=${node.getAttribute("aria-expanded")}`);
            if (node.hasAttribute("aria-selected")) extras.push(`selected=${node.getAttribute("aria-selected")}`);
            if (node.tagName === "A" && node.getAttribute("href")) {
              const href = node.getAttribute("href");
              if (href && !href.startsWith("javascript:")) extras.push(`href="${href.slice(0, 80)}"`);
            }

            const rect = node.getBoundingClientRect();
            const inViewport = (rect.top < viewportHeight && rect.bottom > 0 && rect.left < viewportWidth && rect.right > 0);
            if (!inViewport) extras.push("offscreen");

            const extraStr = extras.length > 0 ? ` (${extras.join(", ")})` : "";
            const nameStr = name ? ` "${name}"` : "";
            lines.push(`${indent}- ${role} [#${refId}]${nameStr}${extraStr}`);
          } else if (role !== "generic" || (name && name.length > 0 && node.children.length === 0)) {
            const nameStr = name ? `: "${name}"` : "";
            lines.push(`${indent}- ${role}${nameStr}`);
          }
        }
      }
      currentNode = walker.nextNode();
    }

    const epoch = Date.now();
    window.__AG_REGISTRY__ = {
      epoch,
      refMap,
      totalInteractive: refCounter - 1
    };
    window.__ag_history = historyMap;

    return {
      snapshot: [`PAGE: "${document.title}" (${window.location.href})`, ...lines].join("\n"),
      totalInteractive: refCounter - 1,
      epoch,
      title: document.title,
      url: window.location.href
    };
  }

  function resolveTarget(target) {
    if (target === undefined || target === null) return null;

    let refId = null;
    let selector = null;

    if (typeof target === "number") {
      refId = target;
    } else if (typeof target === "string") {
      const str = target.trim();
      const mBracket = str.match(/^\[#\s*(\d+)\]$/);
      const mHash = str.match(/^#(\d+)$/);
      const mRef = str.match(/^ref[:=](\d+)$/i);
      if (mBracket) refId = parseInt(mBracket[1], 10);
      else if (mHash) refId = parseInt(mHash[1], 10);
      else if (mRef) refId = parseInt(mRef[1], 10);
      else selector = str;
    } else if (typeof target === "object") {
      if (target.refId !== undefined) {
        refId = parseInt(target.refId, 10);
      } else if (target.selector) {
        selector = target.selector;
      }
    }

    if (refId !== null) {
      const el = window.__AG_REGISTRY__?.refMap?.get(refId);
      if (el && el.isConnected) {
        return { el, targetLabel: `[#${refId}]`, refId };
      }

      const hist = window.__ag_history?.[refId];
      const suggestions = [];
      if (window.__AG_REGISTRY__?.refMap) {
        for (const [candRef, candEl] of window.__AG_REGISTRY__.refMap.entries()) {
          if (!candEl.isConnected) continue;
          const candRole = getComputedRole(candEl);
          const candName = getAccessibleName(candEl);
          if (hist && (candRole === hist.role || (candName && hist.name && candName.toLowerCase().includes(hist.name.toLowerCase())))) {
            suggestions.push({ ref: `#${candRef}`, role: candRole, name: candName });
            if (suggestions.length >= 3) break;
          }
        }
      }

      return {
        error: {
          code: "ELEMENT_NOT_FOUND",
          target: `[#${refId}]`,
          stale: true,
          suggestions,
          url: window.location.href
        }
      };
    }

    if (selector) {
      const el = document.querySelector(selector);
      if (el) {
        return { el, targetLabel: selector };
      }
      return {
        error: {
          code: "ELEMENT_NOT_FOUND",
          target: selector,
          stale: false,
          suggestions: [],
          url: window.location.href
        }
      };
    }

    return { error: { code: "ELEMENT_NOT_FOUND", target: String(target), suggestions: [], url: window.location.href } };
  }

  function resolveCoords(target) {
    const res = resolveTarget(target);
    if (res && res.error) return { __error: res.error };
    if (!res || !res.el) return { __error: { code: "ELEMENT_NOT_FOUND", target: String(target), suggestions: [], url: window.location.href } };

    const el = res.el;
    el.scrollIntoView({ behavior: "instant", block: "center", inline: "center" });

    const rect = el.getBoundingClientRect();
    const cx = Math.max(0, Math.min(window.innerWidth - 1, rect.left + rect.width / 2));
    const cy = Math.max(0, Math.min(window.innerHeight - 1, rect.top + rect.height / 2));

    // Hit-testing inspection
    const hit = document.elementFromPoint(cx, cy);
    let isIntercepted = false;
    let interceptorTag = "";
    let interceptorDesc = "";

    if (hit && hit !== el && !el.contains(hit) && !hit.contains(el)) {
      const interceptor = hit.closest("dialog, [role=\"dialog\"], header, .modal, .overlay, [aria-modal=\"true\"]") || hit;
      isIntercepted = true;
      interceptorTag = interceptor.tagName.toLowerCase();
      interceptorDesc = interceptor.innerText?.slice(0, 50) || interceptor.className || "";
    }

    return {
      x: cx,
      y: cy,
      width: rect.width,
      height: rect.height,
      targetLabel: res.targetLabel,
      tagName: el.tagName,
      text: el.innerText || el.textContent || "",
      isIntercepted,
      interceptorTag,
      interceptorDesc
    };
  }

  function selectOption(target, value) {
    const res = resolveTarget(target);
    if (res && res.error) return { __error: res.error };
    if (!res || !res.el) return { __error: { code: "ELEMENT_NOT_FOUND", target: String(target), suggestions: [], url: window.location.href } };

    const el = res.el;
    if (el.tagName !== "SELECT") {
      return { __error: { code: "ELEMENT_NOT_FOUND", target: String(target), message: "Element is not a <select> dropdown" } };
    }

    let found = false;
    for (const opt of el.options) {
      if (opt.value === value || opt.text === value) {
        opt.selected = true;
        found = true;
        break;
      }
    }
    if (found) {
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return { status: "ok", action: "select", value, target: res.targetLabel };
    }
    return { __error: { code: "ELEMENT_NOT_FOUND", target: String(target), message: `Option "${value}" not found` } };
  }

  function getAttribute(target, name) {
    const res = resolveTarget(target);
    if (res && res.error) return { __error: res.error };
    if (!res || !res.el) return null;
    return res.el.getAttribute(name);
  }

  function getText(target) {
    const res = resolveTarget(target);
    if (res && res.error) return { __error: res.error };
    if (!res || !res.el) return "";
    return res.el.innerText || res.el.textContent || "";
  }

  function clearActive() {
    const el = document.activeElement;
    if (el) {
      if ("value" in el) el.value = "";
      else if (el.isContentEditable) el.innerText = "";
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }
    return { status: "ok" };
  }

  function scrollViewport(x, y) {
    const dx = Number(x || 0);
    const dy = Number(y || 0);
    window.scrollBy({ left: dx, top: dy, behavior: "instant" });
    return { status: "ok", scrollX: window.scrollX, scrollY: window.scrollY };
  }

  function submitActive() {
    const el = document.activeElement;
    if (el && el.form) {
      if (typeof el.form.requestSubmit === "function") {
        el.form.requestSubmit();
      } else {
        el.form.submit();
      }
    }
    return { status: "ok" };
  }

  function getMetrics() {
    const refCount = window.__AG_REGISTRY__?.totalInteractive || 0;
    return {
      readyState: document.readyState,
      refCount,
      viewport: `${window.innerWidth}x${window.innerHeight}`,
      totalElements: document.querySelectorAll("*").length,
      url: window.location.href,
      title: document.title
    };
  }

  window.__arthur_dom_op = function(payload) {
    const op = payload ? payload.operation : "snapshot";
    const args = payload ? payload.args : {};

    if (op === "snapshot") return generateSnapshot();
    if (op === "resolve_coords") return resolveCoords(args.target);
    if (op === "select_option") return selectOption(args.target, args.value);
    if (op === "get_attribute") return getAttribute(args.target, args.name);
    if (op === "get_text") return getText(args.target);
    if (op === "clear_active") return clearActive();
    if (op === "submit_active") return submitActive();
    if (op === "get_metrics") return getMetrics();
    if (op === "scroll_viewport") return scrollViewport(args.x, args.y);

    return { __error: { message: `Unknown DOM operation: ${op}` } };
  };

  return window.__arthur_dom_op(payload);
})
"""


@dataclass
class DOMSnapshotResult:
    snapshot: str
    total_interactive: int
    epoch: int
    title: str
    url: str


async def evaluate_dom_operation(
    cdp: CDPClient,
    operation: str,
    args: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
) -> Any:
    """Evaluate an in-page DOM operation via CDP Runtime.evaluate."""
    payload = json.dumps({"operation": operation, "args": args or {}})
    expression = f"({IN_PAGE_DOM_SCRIPT})({payload})"

    try:
        eval_result = await cdp.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
            session_id=session_id,
        )
    except Exception as e:
        raise CDPError(f"DOM evaluation failed: {e}") from e

    result_obj = eval_result.get("result", {})
    if "value" in result_obj:
        val = result_obj["value"]
        if isinstance(val, dict) and "__error" in val:
            err_data = val["__error"]
            if err_data.get("code") == "ELEMENT_NOT_FOUND":
                raise ElementNotFoundError(
                    target=err_data.get("target", ""),
                    stale=err_data.get("stale", False),
                    suggestions=err_data.get("suggestions", []),
                    url=err_data.get("url", ""),
                )
            raise CDPError(err_data.get("message", "DOM operation error"))
        return val

    return None


async def generate_snapshot(
    cdp: CDPClient, session_id: Optional[str] = None
) -> DOMSnapshotResult:
    """Generate semantic DOM outline snapshot."""
    raw = await evaluate_dom_operation(cdp, "snapshot", session_id=session_id)
    if not isinstance(raw, dict):
        raw = {}
    return DOMSnapshotResult(
        snapshot=raw.get("snapshot", ""),
        total_interactive=raw.get("totalInteractive", 0),
        epoch=raw.get("epoch", 0),
        title=raw.get("title", ""),
        url=raw.get("url", ""),
    )


async def resolve_target_coordinates(
    cdp: CDPClient,
    target: Union[int, str],
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve element center coordinates and hit-testing data."""
    res = await evaluate_dom_operation(
        cdp, "resolve_coords", {"target": target}, session_id=session_id
    )
    if not isinstance(res, dict):
        raise ElementNotFoundError(target=str(target))
    if res.get("isIntercepted"):
        raise ActionInterceptionError(
            target=res.get("targetLabel", str(target)),
            interceptor_tag=res.get("interceptorTag", ""),
            interceptor_desc=res.get("interceptorDesc", ""),
        )
    return res


async def dom_select_option(
    cdp: CDPClient,
    target: Union[int, str],
    value: str,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Select option in a <select> element."""
    res = await evaluate_dom_operation(
        cdp,
        "select_option",
        {"target": target, "value": value},
        session_id=session_id,
    )
    if isinstance(res, dict):
        return res
    return {"status": "ok", "action": "select", "value": value}


async def dom_get_attribute(
    cdp: CDPClient,
    target: Union[int, str],
    name: str,
    session_id: Optional[str] = None,
) -> Optional[str]:
    """Get DOM attribute value of element."""
    res = await evaluate_dom_operation(
        cdp,
        "get_attribute",
        {"target": target, "name": name},
        session_id=session_id,
    )
    return str(res) if res is not None else None


async def dom_get_text(
    cdp: CDPClient,
    target: Union[int, str],
    session_id: Optional[str] = None,
) -> str:
    """Get innerText or textContent of element."""
    res = await evaluate_dom_operation(
        cdp,
        "get_text",
        {"target": target},
        session_id=session_id,
    )
    return str(res) if res is not None else ""


async def dom_clear_active_element(
    cdp: CDPClient, session_id: Optional[str] = None
) -> None:
    """Clear value/text of active element."""
    await evaluate_dom_operation(cdp, "clear_active", session_id=session_id)


async def dom_submit_active_form(
    cdp: CDPClient, session_id: Optional[str] = None
) -> None:
    """Submit form belonging to active element."""
    await evaluate_dom_operation(cdp, "submit_active", session_id=session_id)


async def get_dom_metrics(
    cdp: CDPClient, session_id: Optional[str] = None
) -> Dict[str, Any]:
    """Retrieve lightweight metrics from target page DOM."""
    res = await evaluate_dom_operation(cdp, "get_metrics", session_id=session_id)
    return res if isinstance(res, dict) else {}


async def dom_scroll_viewport(
    cdp: CDPClient, x: int = 0, y: int = 500, session_id: Optional[str] = None
) -> Dict[str, Any]:
    """Scroll viewport by (x, y)."""
    res = await evaluate_dom_operation(
        cdp, "scroll_viewport", {"x": x, "y": y}, session_id=session_id
    )
    return res if isinstance(res, dict) else {"status": "ok", "x": x, "y": y}
