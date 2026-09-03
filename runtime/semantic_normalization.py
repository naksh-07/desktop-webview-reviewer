"""
Deterministic Semantic Normalization for Web Controls.
Normalizes heterogeneous Chromium accessibility tree roles and DOM element semantics
into a canonical set of predictable agent-facing control types while preserving role provenance.
"""

from __future__ import annotations
from typing import Dict, Optional, Tuple, Any

from runtime.observation_models import RoleSource


# Canonical supported semantic roles
CANONICAL_ROLES = {
    "button",
    "link",
    "textbox",
    "checkbox",
    "radio",
    "combobox",
    "listbox",
    "option",
    "tab",
    "tabpanel",
    "menuitem",
    "menu",
    "dialog",
    "heading",
    "image",
    "paragraph",
    "form",
    "table",
    "row",
    "cell",
    "list",
    "listitem",
    "slider",
    "progressbar",
    "generic",
}

# Actionable roles that can typically receive user interaction
ACTIONABLE_ROLES = {
    "button",
    "link",
    "textbox",
    "checkbox",
    "radio",
    "combobox",
    "listbox",
    "option",
    "tab",
    "menuitem",
    "slider",
    "dialog",
}

# Mapping from raw accessibility tree roles (Chromium AXTree) to canonical roles
AX_ROLE_MAP: Dict[str, str] = {
    "button": "button",
    "pushbutton": "button",
    "togglebutton": "button",
    "link": "link",
    "textfield": "textbox",
    "textbox": "textbox",
    "searchbox": "textbox",
    "search": "textbox",
    "input": "textbox",
    "checkbox": "checkbox",
    "switch": "checkbox",
    "radio": "radio",
    "radiobutton": "radio",
    "combobox": "combobox",
    "listbox": "listbox",
    "option": "option",
    "listboxoption": "option",
    "menuitem": "menuitem",
    "menuitemcheckbox": "menuitem",
    "menuitemradio": "menuitem",
    "tab": "tab",
    "tabpanel": "tabpanel",
    "dialog": "dialog",
    "alertdialog": "dialog",
    "modal": "dialog",
    "heading": "heading",
    "image": "image",
    "img": "image",
    "graphic": "image",
    "paragraph": "paragraph",
    "form": "form",
    "table": "table",
    "grid": "table",
    "row": "row",
    "cell": "cell",
    "gridcell": "cell",
    "list": "list",
    "listitem": "listitem",
    "slider": "slider",
    "progressbar": "progressbar",
}


def normalize_web_role(
    ax_role: Optional[str] = None,
    tag_name: str = "div",
    input_type: Optional[str] = None,
    aria_role: Optional[str] = None,
    attributes: Optional[Dict[str, str]] = None,
) -> Tuple[str, RoleSource]:
    """
    Deterministically normalizes web control semantics into a canonical role with provenance.

    Precedence:
    1. Direct W3C WAI-ARIA role attribute (if explicitly specified and valid) -> ACCESSIBILITY
    2. Chromium Accessibility Tree AXRole (if informative and not generic) -> ACCESSIBILITY
    3. Native DOM element semantics (tag, type, href) -> DOM
    4. Structural and behavioral hints (onclick, role inference) -> INFERRED
    5. Fallback -> ("generic", DOM)
    """
    attrs = attributes or {}
    tag = tag_name.lower().strip() if tag_name else "div"
    itype = input_type.lower().strip() if input_type else attrs.get("type", "").lower().strip()
    raw_aria = aria_role or attrs.get("role", "")
    if raw_aria:
        raw_aria = raw_aria.lower().strip()

    # 1. Explicit ARIA role attribute
    if raw_aria and raw_aria in AX_ROLE_MAP:
        return AX_ROLE_MAP[raw_aria], RoleSource.ACCESSIBILITY

    # 2. Chromium AX Tree role
    if ax_role:
        clean_ax = ax_role.lower().strip()
        if clean_ax in AX_ROLE_MAP:
            return AX_ROLE_MAP[clean_ax], RoleSource.ACCESSIBILITY
        # Ignore generic container roles in AX tree
        if clean_ax in ("generic", "none", "presentation", "group", "div", "section", "region", "rootwebarea"):
            pass  # Fall through to DOM inspection

    # 3. Native DOM semantics
    if tag == "button":
        return "button", RoleSource.DOM

    if tag == "a":
        if "href" in attrs or attrs.get("tabindex") is not None:
            return "link", RoleSource.DOM
        return "generic", RoleSource.DOM

    if tag == "input":
        if itype in ("button", "submit", "reset", "image"):
            return "button", RoleSource.DOM
        if itype in ("checkbox",):
            return "checkbox", RoleSource.DOM
        if itype in ("radio",):
            return "radio", RoleSource.DOM
        if itype in ("range",):
            return "slider", RoleSource.DOM
        # Textual inputs
        if itype in ("text", "search", "tel", "url", "email", "password", "number", "date", "time", "datetime-local", "file", ""):
            return "textbox", RoleSource.DOM
        return "textbox", RoleSource.DOM

    if tag == "textarea":
        return "textbox", RoleSource.DOM

    if tag == "select":
        if attrs.get("multiple") is not None or (attrs.get("size") and int(attrs["size"]) > 1):
            return "listbox", RoleSource.DOM
        return "combobox", RoleSource.DOM

    if tag == "option":
        return "option", RoleSource.DOM

    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        return "heading", RoleSource.DOM

    if tag == "img":
        return "image", RoleSource.DOM

    if tag == "dialog":
        return "dialog", RoleSource.DOM

    if tag == "form":
        return "form", RoleSource.DOM

    if tag == "p":
        return "paragraph", RoleSource.DOM

    if tag in ("ul", "ol"):
        return "list", RoleSource.DOM

    if tag == "li":
        return "listitem", RoleSource.DOM

    if tag == "table":
        return "table", RoleSource.DOM

    if tag == "tr":
        return "row", RoleSource.DOM

    if tag in ("td", "th"):
        return "cell", RoleSource.DOM

    if tag == "progress":
        return "progressbar", RoleSource.DOM

    # 4. Behavioral / Inferred hints (e.g. div with click handlers or tabindex)
    if "onclick" in attrs or attrs.get("role") == "button":
        return "button", RoleSource.INFERRED

    if attrs.get("tabindex") is not None:
        try:
            if int(attrs["tabindex"]) >= 0 and ("btn" in attrs.get("class", "").lower() or "button" in attrs.get("class", "").lower()):
                return "button", RoleSource.INFERRED
        except ValueError:
            pass

    # 5. Fallback
    return "generic", RoleSource.DOM


def is_actionable_role(role: str) -> bool:
    """Returns True if the normalized role represents an interactive affordance."""
    return role.lower().strip() in ACTIONABLE_ROLES
