#!/usr/bin/env python3
"""
Substack Skill - Create, edit, publish, schedule, and manage Substack posts.

Uses Substack's internal (unofficial) JSON API with browser session-cookie auth.
Auth lives in config.json next to this file (multi-account, mirrors notion-skill).

Usage:
    python3 substack_skill.py setup
    python3 substack_skill.py whoami [-a ACCOUNT]
    python3 substack_skill.py list-posts [--status published|draft|scheduled] [--limit N] [-a]
    python3 substack_skill.py get-draft ID [--raw] [-a]
    python3 substack_skill.py get-post SLUG [--raw] [-a]
    python3 substack_skill.py create-draft --title T [--subtitle S] (--body-md FILE | --body-text TEXT) [-a]
    python3 substack_skill.py update-draft ID [--title T] [--subtitle S] [--body-md FILE] [-a]
    python3 substack_skill.py publish ID (--send-email | --no-email) [--share] [-a]
    python3 substack_skill.py schedule ID --at ISO_DATETIME [-a]
    python3 substack_skill.py unschedule ID [-a]
    python3 substack_skill.py delete-draft ID --force [-a]
    python3 substack_skill.py upload-image FILE [-a]
    python3 substack_skill.py sections [-a]

All commands print JSON to stdout and exit non-zero on error.
"""

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SKILL_DIR / "config.json"
GLOBAL_API = "https://substack.com/api/v1"
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
RETRY_STATUSES = {429, 502, 503, 504}


# ---------------------------------------------------------------- output

def emit(payload, exit_code=0):
    print(json.dumps(payload, indent=2, default=str))
    sys.exit(exit_code)


def emit_error(code, message, exit_code=1, **extra):
    print(json.dumps({"error": code, "message": message, **extra}, indent=2, default=str))
    sys.exit(exit_code)


# ---------------------------------------------------------------- config

def load_config():
    if not CONFIG_PATH.exists():
        emit_error("config_missing",
                   f"No config.json at {CONFIG_PATH}. Run `setup` first.",
                   exit_code=2)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    os.chmod(CONFIG_PATH, 0o600)  # session cookie inside


def get_account(cfg, account_name):
    name = account_name or cfg.get("default_account")
    if not name:
        emit_error("no_account", "No account selected and no default_account in config.")
    accounts = cfg.get("accounts", {})
    if name not in accounts:
        emit_error("unknown_account",
                   f"Account '{name}' not in config. Known: {', '.join(sorted(accounts))}")
    return name, accounts[name]


def resolve_account(args):
    cfg = load_config()
    return get_account(cfg, getattr(args, "account", None))


# ---------------------------------------------------------------- http

def _request(account, method, path, data=None, params=None, base="pub", form=False,
             retries=3, soft=False):
    """One HTTP round-trip against the Substack API. Returns parsed JSON.

    With soft=True, failures return None instead of emitting an error and exiting
    (for best-effort calls like prepublish checks and subscriber counts).
    """
    if base == "global":
        url = GLOBAL_API + path
    else:
        pub = account["publication_url"].rstrip("/")
        url = pub + "/api/v1" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)

    headers = {
        "Cookie": account["cookie"],
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"

    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                if not raw.strip():
                    return {"ok": True, "status": resp.status}
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    if soft:
                        return None
                    emit_error("bad_response",
                               f"Non-JSON response from {method} {path} (status {resp.status}). "
                               "Cookie may be expired or the endpoint has changed.",
                               body_snippet=raw[:300])
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            if e.code in RETRY_STATUSES and attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                last_err = (e.code, raw)
                continue
            if soft:
                return None
            try:
                detail = json.loads(raw)
            except json.JSONDecodeError:
                detail = raw[:300]
            if e.code in (401, 403):
                emit_error("auth_failed",
                           f"{method} {path} returned {e.code}. Session cookie is likely "
                           "expired — grab a fresh substack.sid from your browser and re-run setup.",
                           status=e.code, detail=detail)
            emit_error("api_error", f"{method} {path} failed with status {e.code}.",
                       status=e.code, detail=detail)
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                last_err = (None, str(e))
                continue
            if soft:
                return None
            emit_error("network_error", f"Could not reach Substack: {e}")
    if soft:
        return None
    emit_error("retries_exhausted", f"{method} {path} kept failing.", detail=str(last_err))


# ---------------------------------------------------------------- markdown -> prosemirror

BOLD_RE = re.compile(r"\*\*(.+?)\*\*|(?<!\w)__(.+?)__(?!\w)", re.S)
EM_RE = re.compile(r"\*([^*\n]+)\*|(?<!\w)_([^_\n]+)_(?!\w)")
CODE_RE = re.compile(r"`([^`\n]+)`")
STRIKE_RE = re.compile(r"~~(.+?)~~", re.S)
_URL = r"((?:\([^)\s]*\)|[^)\s])+)"  # tolerates one level of balanced parens
LINK_RE = re.compile(r"\[([^\]]+)\]\(" + _URL + r"(?:\s+\"[^\"]*\")?\)")
IMG_INLINE_RE = re.compile(r"!\[([^\]]*)\]\(" + _URL + r"(?:\s+\"[^\"]*\")?\)")
IMG_LINE_RE = re.compile(r"^!\[([^\]]*)\]\(" + _URL + r"(?:\s+\"([^\"]*)\")?\)\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
HR_RE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
FENCE_RE = re.compile(r"^```(\S*)\s*$")
FENCE_CLOSE_RE = re.compile(r"^```\s*$")
LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
# only these markers may interrupt a paragraph (CommonMark: '1.' but not '1984.')
LIST_INTERRUPT_RE = re.compile(r"^\s*([-*+]|1[.)])\s+")
QUOTE_RE = re.compile(r"^>\s?(.*)$")


def text_node(text, marks):
    node = {"type": "text", "text": text}
    if marks:
        node["marks"] = [dict(m) for m in marks]
    return node


def parse_inline(text, marks=()):
    """Parse inline markdown into a list of ProseMirror text nodes."""
    nodes = []
    pos = 0
    # inline images degrade to links (Substack images are block-level)
    text = IMG_INLINE_RE.sub(lambda m: f"[{m.group(1) or 'image'}]({m.group(2)})", text)
    patterns = [
        ("code", CODE_RE),
        ("bold", BOLD_RE),
        ("strike", STRIKE_RE),
        ("link", LINK_RE),
        ("em", EM_RE),
    ]
    while pos < len(text):
        best = None
        best_kind = None
        for kind, rx in patterns:
            m = rx.search(text, pos)
            if m and (best is None or m.start() < best.start()):
                best = m
                best_kind = kind
        if best is None:
            rest = text[pos:]
            if rest:
                nodes.append(text_node(rest, marks))
            break
        if best.start() > pos:
            nodes.append(text_node(text[pos:best.start()], marks))
        if best_kind == "code":
            nodes.append(text_node(best.group(1), list(marks) + [{"type": "code"}]))
        elif best_kind == "bold":
            inner = best.group(1) if best.group(1) is not None else best.group(2)
            nodes.extend(parse_inline(inner, list(marks) + [{"type": "strong"}]))
        elif best_kind == "strike":
            nodes.extend(parse_inline(best.group(1), list(marks) + [{"type": "strikethrough"}]))
        elif best_kind == "link":
            nodes.extend(parse_inline(
                best.group(1),
                list(marks) + [{"type": "link", "attrs": {"href": best.group(2)}}]))
        elif best_kind == "em":
            inner = best.group(1) if best.group(1) is not None else best.group(2)
            nodes.extend(parse_inline(inner, list(marks) + [{"type": "em"}]))
        pos = best.end()
    return nodes


def paragraph_node(text):
    content = parse_inline(text)
    node = {"type": "paragraph"}
    if content:
        node["content"] = content
    return node


def image_block(src, alt, title, account, uploads):
    if not re.match(r"^https?://", src):
        local = Path(src).expanduser()
        if account is not None and local.exists():
            src = upload_image_file(account, local)
            uploads.append({"file": str(local), "url": src})
        else:
            raise ValueError(f"Local image not found: {src}")
    attrs = {
        "src": src, "srcNoWatermark": None, "fullscreen": None, "imageSize": "normal",
        "height": None, "width": None, "resizeWidth": 728, "bytes": None,
        "alt": alt or None, "title": title or None, "type": None, "href": None,
        "belowTheFold": False, "topImage": False, "internalRedirect": None,
    }
    block = {"type": "captionedImage",
             "content": [{"type": "image2", "attrs": attrs}]}
    return block


def parse_list_block(lines, account, uploads):
    """Parse a run of list lines (with one nesting level via indentation)."""
    first = LIST_RE.match(lines[0])
    ordered = bool(re.match(r"\d", first.group(2)))
    base_indent = len(first.group(1))
    items = []
    current = None  # dict with "text" and "children" (list of raw lines)
    for line in lines:
        m = LIST_RE.match(line)
        if m and len(m.group(1)) <= base_indent:
            if current:
                items.append(current)
            current = {"text": m.group(3), "children": []}
        elif current is not None:
            current["children"].append(line)
        # else: stray continuation before first item; ignore
    if current:
        items.append(current)

    item_nodes = []
    for item in items:
        # fold non-list continuation lines into the item's paragraph (no data loss)
        text_cont = [ln.strip() for ln in item["children"]
                     if not LIST_RE.match(ln) and ln.strip()]
        content = [paragraph_node(" ".join([item["text"]] + text_cont))]
        child_list_lines = [ln for ln in item["children"] if LIST_RE.match(ln)]
        if child_list_lines:
            content.append(parse_list_block(child_list_lines, account, uploads))
        item_nodes.append({"type": "list_item", "content": content})
    return {"type": "ordered_list" if ordered else "bullet_list", "content": item_nodes}


def md_to_prosemirror(md_text, account=None):
    """Convert markdown to a Substack ProseMirror doc. Returns (doc, uploaded_images)."""
    uploads = []
    lines = md_text.replace("\r\n", "\n").split("\n")
    # strip leading YAML frontmatter (Obsidian notes)
    if lines and lines[0].strip() == "---":
        for j in range(1, len(lines)):
            if lines[j].strip() in ("---", "..."):
                lines = lines[j + 1:]
                break
    blocks = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        fence = FENCE_RE.match(line)
        if fence:
            lang = fence.group(1) or None
            code_lines = []
            i += 1
            while i < n and not FENCE_CLOSE_RE.match(lines[i]):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            code_text = "\n".join(code_lines)
            node = {"type": "codeBlock"}
            if code_text:
                node["content"] = [{"type": "text", "text": code_text}]
            if lang:
                node["attrs"] = {"language": lang}
            blocks.append(node)
            continue
        h = HEADING_RE.match(line)
        if h:
            blocks.append({"type": "heading", "attrs": {"level": len(h.group(1))},
                           "content": parse_inline(h.group(2).strip())})
            i += 1
            continue
        if HR_RE.match(line) and not LIST_RE.match(line):
            blocks.append({"type": "horizontal_rule"})
            i += 1
            continue
        img = IMG_LINE_RE.match(line.strip())
        if img:
            blocks.append(image_block(img.group(2), img.group(1), img.group(3),
                                      account, uploads))
            i += 1
            continue
        if QUOTE_RE.match(line):
            quote_lines = []
            while i < n and QUOTE_RE.match(lines[i]):
                quote_lines.append(QUOTE_RE.match(lines[i]).group(1))
                i += 1
            paras, buf = [], []
            for ql in quote_lines + [""]:
                if ql.strip():
                    buf.append(ql.strip())
                elif buf:
                    paras.append(paragraph_node(" ".join(buf)))
                    buf = []
            if paras:
                blocks.append({"type": "blockquote", "content": paras})
            continue
        if LIST_RE.match(line):
            list_lines = []
            while i < n and (LIST_RE.match(lines[i]) or
                             (lines[i].startswith((" ", "\t")) and lines[i].strip())):
                list_lines.append(lines[i])
                i += 1
            blocks.append(parse_list_block(list_lines, account, uploads))
            continue
        # paragraph: accumulate until blank line or a new block marker
        buf = [line.strip()]
        i += 1
        while i < n and lines[i].strip():
            nxt = lines[i]
            if (HEADING_RE.match(nxt) or FENCE_RE.match(nxt) or QUOTE_RE.match(nxt)
                    or LIST_INTERRUPT_RE.match(nxt) or HR_RE.match(nxt)
                    or IMG_LINE_RE.match(nxt.strip())):
                break
            buf.append(nxt.strip())
            i += 1
        blocks.append(paragraph_node(" ".join(buf)))
    return {"type": "doc", "content": blocks}, uploads


# ---------------------------------------------------------------- prosemirror -> markdown

def marks_wrap(text, marks):
    for mark in marks or []:
        t = mark.get("type")
        if t == "code":
            text = f"`{text}`"
        elif t == "strong":
            text = f"**{text}**"
        elif t == "em":
            text = f"*{text}*"
        elif t == "strikethrough":
            text = f"~~{text}~~"
        elif t == "link":
            text = f"[{text}]({mark.get('attrs', {}).get('href', '')})"
    return text


def inline_to_md(content):
    out = []
    for node in content or []:
        if node.get("type") == "text":
            out.append(marks_wrap(node.get("text", ""), node.get("marks")))
        elif node.get("type") == "footnoteAnchor":
            out.append(f"[^{node.get('attrs', {}).get('number', '?')}]")
    return "".join(out)


def node_to_md(node, indent=0):
    t = node.get("type")
    pad = "  " * indent
    if t == "paragraph":
        return inline_to_md(node.get("content"))
    if t == "heading":
        level = node.get("attrs", {}).get("level", 1)
        return "#" * level + " " + inline_to_md(node.get("content"))
    if t == "blockquote":
        inner = [node_to_md(c) for c in node.get("content", [])]
        return "\n".join("> " + ln for block in inner for ln in block.split("\n"))
    if t == "codeBlock":
        lang = node.get("attrs", {}).get("language") or ""
        code = "".join(c.get("text", "") for c in node.get("content", []))
        return f"```{lang}\n{code}\n```"
    if t == "horizontal_rule":
        return "---"
    if t in ("bullet_list", "ordered_list"):
        out = []
        for idx, item in enumerate(node.get("content", []), 1):
            marker = f"{idx}." if t == "ordered_list" else "-"
            parts = item.get("content", [])
            first = True
            for part in parts:
                if part.get("type") in ("bullet_list", "ordered_list"):
                    out.append(node_to_md(part, indent + 1))
                else:
                    prefix = f"{pad}{marker} " if first else f"{pad}  "
                    out.append(prefix + node_to_md(part))
                    first = False
        return "\n".join(out)
    if t == "captionedImage":
        for child in node.get("content", []):
            if child.get("type") == "image2":
                a = child.get("attrs", {})
                return f"![{a.get('alt') or ''}]({a.get('src', '')})"
        return ""
    if t == "youtube2":
        vid = node.get("attrs", {}).get("videoId", "")
        return f"[youtube]({vid})"
    if t == "footnote":
        num = node.get("attrs", {}).get("number", "?")
        inner = " ".join(node_to_md(c) for c in node.get("content", []))
        return f"[^{num}]: {inner}"
    # unknown / editor-only node (button, poll, subscribe widget, ...)
    return f"<!-- substack:{t} (widget preserved only in the web editor) -->"


def prosemirror_to_md(doc):
    if isinstance(doc, str):
        doc = json.loads(doc)
    return "\n\n".join(node_to_md(n) for n in doc.get("content", []))


# ---------------------------------------------------------------- api helpers

def upload_image_file(account, path):
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    resp = _request(account, "POST", "/image",
                    data={"image": f"data:{mime};base64,{b64}"}, form=True)
    url = resp.get("url")
    if not url:
        emit_error("upload_failed", "Image upload returned no URL.", detail=resp)
    return url


def fetch_self_profile(account):
    return _request(account, "GET", "/user/profile/self", base="global")


def ensure_user_id(cfg, name, account):
    if account.get("user_id"):
        return account["user_id"]
    profile = fetch_self_profile(account)
    user_id = profile.get("id")
    if not user_id:
        emit_error("no_user_id", "Could not resolve user id from profile.", detail=profile)
    account["user_id"] = user_id
    cfg["accounts"][name] = account
    save_config(cfg)
    return user_id


def read_body_arg(args):
    if getattr(args, "body_md", None):
        p = Path(args.body_md).expanduser()
        if not p.exists():
            emit_error("file_not_found", f"No such file: {p}")
        return p.read_text(encoding="utf-8")
    if getattr(args, "body_text", None):
        return args.body_text
    return None


def slim_post(p):
    return {
        "id": p.get("id"),
        "title": p.get("title") or p.get("draft_title"),
        "subtitle": p.get("subtitle") or p.get("draft_subtitle"),
        "slug": p.get("slug"),
        "audience": p.get("audience"),
        "post_date": p.get("post_date"),
        "draft_updated_at": p.get("draft_updated_at"),
        "is_published": p.get("is_published"),
        "canonical_url": p.get("canonical_url"),
    }


def editor_url(account, draft_id):
    return account["publication_url"].rstrip("/") + f"/publish/post/{draft_id}"


# ---------------------------------------------------------------- commands

def cmd_setup(args):
    cfg = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    cfg.setdefault("accounts", {})

    label = args.label or input("Account label (e.g. personal): ").strip()
    url = args.url or input("Publication URL (e.g. https://yourname.substack.com): ").strip()
    url = url.rstrip("/")
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]  # avoid 301 that downgrades POSTs to GET
    elif not url.startswith("https://"):
        url = "https://" + url
    cookie = args.cookie or input(
        "Session cookie (paste the substack.sid value, or the whole Cookie header): ").strip()
    cookie = cookie.strip().strip(";")
    if cookie.lower().startswith("cookie:"):
        cookie = cookie[len("cookie:"):].strip()
    if "=" not in cookie.split(";")[0]:
        cookie = "substack.sid=" + cookie

    account = {"publication_url": url, "cookie": cookie}
    profile = fetch_self_profile(account)
    user_id = profile.get("id")
    if not user_id:
        emit_error("verify_failed",
                   "Cookie did not authenticate (no user id in profile). "
                   "Copy a fresh substack.sid cookie from a logged-in browser tab.",
                   detail={k: profile.get(k) for k in ("error", "message")})
    account["user_id"] = user_id
    account["user_name"] = profile.get("name")

    cfg["accounts"][label] = account
    if args.set_default or not cfg.get("default_account"):
        cfg["default_account"] = label
    save_config(cfg)
    emit({"ok": True, "account": label, "user_id": user_id,
          "user_name": profile.get("name"), "publication_url": url,
          "default_account": cfg.get("default_account"),
          "config_path": str(CONFIG_PATH)})


def cmd_whoami(args):
    _, account = resolve_account(args)
    profile = fetch_self_profile(account)
    pubs = []
    for pu in profile.get("publicationUsers", []) or []:
        pub = pu.get("publication") or {}
        pubs.append({"name": pub.get("name"), "subdomain": pub.get("subdomain"),
                     "custom_domain": pub.get("custom_domain"),
                     "role": pu.get("role"), "is_primary": pu.get("is_primary")})
    result = {"user_id": profile.get("id"), "name": profile.get("name"),
              "handle": profile.get("handle"),
              "publication_url": account["publication_url"], "publications": pubs}
    checklist = _request(account, "GET", "/publication_launch_checklist", soft=True)
    if isinstance(checklist, dict):
        result["subscriber_count"] = checklist.get("subscriberCount")
    emit(result)


def cmd_list_posts(args):
    _, account = resolve_account(args)
    status = args.status
    if status == "draft":
        posts = _request(account, "GET", "/drafts",
                         params={"filter": "draft", "offset": args.offset,
                                 "limit": args.limit})
    elif status == "scheduled":
        posts = _request(account, "GET", "/post_management/scheduled",
                         params={"offset": args.offset, "limit": args.limit,
                                 "order_by": "post_date", "order_direction": "desc"})
    else:
        posts = _request(account, "GET", "/post_management/published",
                         params={"offset": args.offset, "limit": args.limit,
                                 "order_by": "post_date", "order_direction": "desc"})
    if isinstance(posts, dict):
        posts = posts.get("posts", posts.get("drafts", []))
    emit({"status": status, "count": len(posts), "posts": [slim_post(p) for p in posts]})


def cmd_get_draft(args):
    _, account = resolve_account(args)
    draft = _request(account, "GET", f"/drafts/{args.id}")
    if args.raw:
        emit(draft)
    body_md = None
    if draft.get("draft_body"):
        try:
            body_md = prosemirror_to_md(draft["draft_body"])
        except (json.JSONDecodeError, AttributeError, TypeError) as e:
            body_md = f"<conversion failed: {e}>"
    out = slim_post(draft)
    out["editor_url"] = editor_url(account, args.id)
    out["body_markdown"] = body_md
    emit(out)


def cmd_get_post(args):
    _, account = resolve_account(args)
    post = _request(account, "GET", f"/posts/{args.slug}")
    if args.raw:
        emit(post)
    out = slim_post(post)
    out["description"] = post.get("description")
    out["body_html_chars"] = len(post.get("body_html") or "")
    emit(out)


def cmd_create_draft(args):
    cfg = load_config()
    name, account = get_account(cfg, args.account)
    md = read_body_arg(args)
    if md is None:
        emit_error("no_body", "Provide --body-md FILE or --body-text TEXT.")
    try:
        doc, uploads = md_to_prosemirror(md, account)
    except ValueError as e:
        emit_error("bad_markdown", str(e))
    user_id = ensure_user_id(cfg, name, account)
    body = {
        "draft_title": args.title,
        "draft_subtitle": args.subtitle or "",
        "draft_body": json.dumps(doc),
        "draft_bylines": [{"id": user_id, "is_guest": False}],
        "audience": args.audience,
        "write_comment_permissions": "everyone",
        "draft_section_id": args.section_id,
        "section_chosen": True,
    }
    # retries=1: draft creation is not idempotent (a retried 502 could double-create)
    draft = _request(account, "POST", "/drafts", data=body, retries=1)
    draft_id = draft.get("id")
    if not draft_id:
        emit_error("create_failed", "Draft creation returned no id.", detail=draft)
    emit({"ok": True, "draft_id": draft_id, "title": args.title,
          "audience": args.audience, "editor_url": editor_url(account, draft_id),
          "uploaded_images": uploads,
          "note": "Draft only — nothing is published until you run `publish`."})


def cmd_update_draft(args):
    cfg = load_config()
    name, account = get_account(cfg, args.account)
    body = {}
    if args.title is not None:
        body["draft_title"] = args.title
    if args.subtitle is not None:
        body["draft_subtitle"] = args.subtitle
    if args.audience is not None:
        body["audience"] = args.audience
    if args.section_id is not None:
        body["draft_section_id"] = args.section_id
    md = read_body_arg(args)
    uploads = []
    if md is not None:
        try:
            doc, uploads = md_to_prosemirror(md, account)
        except ValueError as e:
            emit_error("bad_markdown", str(e))
        body["draft_body"] = json.dumps(doc)
        user_id = ensure_user_id(cfg, name, account)
        body["draft_bylines"] = [{"id": user_id, "is_guest": False}]
    if not body:
        emit_error("nothing_to_update",
                   "Pass at least one of --title/--subtitle/--body-md/--body-text/"
                   "--audience/--section-id.")
    _request(account, "PUT", f"/drafts/{args.id}", data=body)
    out = {"ok": True, "draft_id": args.id, "updated_fields": sorted(body.keys()),
           "editor_url": editor_url(account, args.id), "uploaded_images": uploads}
    if "draft_body" in body:
        out["warning"] = ("Body was fully replaced. Any editor-only widgets "
                          "(buttons, polls, paywalls) in the old draft are gone.")
    emit(out)


def cmd_publish(args):
    _, account = resolve_account(args)
    send_email = bool(args.send_email)
    pre = _request(account, "GET", f"/drafts/{args.id}/prepublish", soft=True)
    # retries=1: never risk a double email blast on an ambiguous gateway error
    result = _request(account, "POST", f"/drafts/{args.id}/publish",
                      data={"send": send_email,
                            "share_automatically": bool(args.share)},
                      retries=1)
    emit({"ok": True, "post_id": result.get("id", args.id),
          "sent_email": send_email,
          "canonical_url": result.get("canonical_url"),
          "slug": result.get("slug"),
          "prepublish_warnings": (pre or {}).get("warnings") if isinstance(pre, dict) else None})


def cmd_schedule(args):
    _, account = resolve_account(args)
    result = _request(account, "POST", f"/drafts/{args.id}/schedule",
                      data={"post_date": args.at})
    emit({"ok": True, "draft_id": args.id, "scheduled_for": args.at,
          "detail": slim_post(result) if isinstance(result, dict) else result})


def cmd_unschedule(args):
    _, account = resolve_account(args)
    _request(account, "POST", f"/drafts/{args.id}/schedule", data={"post_date": None})
    emit({"ok": True, "draft_id": args.id, "scheduled_for": None})


def cmd_delete_draft(args):
    _, account = resolve_account(args)
    if not args.force:
        emit_error("confirm_required",
                   "Deleting a draft is irreversible. Re-run with --force to confirm.")
    _request(account, "DELETE", f"/drafts/{args.id}")
    emit({"ok": True, "deleted_draft": args.id})


def cmd_upload_image(args):
    _, account = resolve_account(args)
    p = Path(args.file).expanduser()
    if not p.exists():
        emit_error("file_not_found", f"No such file: {p}")
    url = upload_image_file(account, p)
    emit({"ok": True, "file": str(p), "url": url})


def cmd_sections(args):
    _, account = resolve_account(args)
    subs = _request(account, "GET", "/subscriptions", base="global")
    host = urllib.parse.urlparse(account["publication_url"]).netloc
    sections = []
    pubs = subs.get("publications", []) if isinstance(subs, dict) else []
    for pub in pubs:
        hostname = pub.get("hostname") or ""
        subdomain = pub.get("subdomain") or ""
        if host in (hostname, f"{subdomain}.substack.com"):
            sections = pub.get("sections") or []
            break
    emit({"publication": host,
          "sections": [{"id": s.get("id"), "name": s.get("name")} for s in sections]})


# ---------------------------------------------------------------- main

def add_account_arg(parser):
    parser.add_argument("-a", "--account", help="account label from config.json")


def main():
    p = argparse.ArgumentParser(prog="substack",
                                description="Substack post management (unofficial API).")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("setup", help="add/verify an account and write config.json")
    s.add_argument("--label")
    s.add_argument("--url", help="publication URL")
    s.add_argument("--cookie", help="substack.sid value or full Cookie header")
    s.add_argument("--set-default", action="store_true")
    s.set_defaults(func=cmd_setup)

    s = sub.add_parser("whoami", help="verify auth; show user + publication info")
    add_account_arg(s)
    s.set_defaults(func=cmd_whoami)

    s = sub.add_parser("list-posts", help="list published/draft/scheduled posts")
    s.add_argument("--status", choices=["published", "draft", "scheduled"],
                   default="published")
    s.add_argument("--limit", type=int, default=15)
    s.add_argument("--offset", type=int, default=0)
    add_account_arg(s)
    s.set_defaults(func=cmd_list_posts)

    s = sub.add_parser("get-draft", help="fetch a draft (body converted to markdown)")
    s.add_argument("id")
    s.add_argument("--raw", action="store_true", help="dump full API response")
    add_account_arg(s)
    s.set_defaults(func=cmd_get_draft)

    s = sub.add_parser("get-post", help="fetch a published post by slug")
    s.add_argument("slug")
    s.add_argument("--raw", action="store_true")
    add_account_arg(s)
    s.set_defaults(func=cmd_get_post)

    s = sub.add_parser("create-draft", help="create a draft from markdown")
    s.add_argument("--title", required=True)
    s.add_argument("--subtitle")
    s.add_argument("--body-md", help="path to a markdown file")
    s.add_argument("--body-text", help="inline markdown body")
    s.add_argument("--audience", choices=["everyone", "only_paid", "only_free", "founding"],
                   default="everyone")
    s.add_argument("--section-id", type=int)
    add_account_arg(s)
    s.set_defaults(func=cmd_create_draft)

    s = sub.add_parser("update-draft", help="update a draft's title/subtitle/body")
    s.add_argument("id")
    s.add_argument("--title")
    s.add_argument("--subtitle")
    s.add_argument("--body-md")
    s.add_argument("--body-text")
    s.add_argument("--audience", choices=["everyone", "only_paid", "only_free", "founding"])
    s.add_argument("--section-id", type=int)
    add_account_arg(s)
    s.set_defaults(func=cmd_update_draft)

    s = sub.add_parser("publish", help="publish a draft (CONFIRM WITH USER FIRST)")
    s.add_argument("id")
    email = s.add_mutually_exclusive_group(required=True)
    email.add_argument("--send-email", action="store_true",
                       help="publish AND email all subscribers")
    email.add_argument("--no-email", action="store_true",
                       help="publish to web only, no email blast")
    s.add_argument("--share", action="store_true",
                   help="share automatically to Substack Notes")
    add_account_arg(s)
    s.set_defaults(func=cmd_publish)

    s = sub.add_parser("schedule", help="schedule a draft for future publication")
    s.add_argument("id")
    s.add_argument("--at", required=True,
                   help="ISO-8601 datetime, e.g. 2026-07-08T09:00:00-07:00")
    add_account_arg(s)
    s.set_defaults(func=cmd_schedule)

    s = sub.add_parser("unschedule", help="cancel a scheduled publication")
    s.add_argument("id")
    add_account_arg(s)
    s.set_defaults(func=cmd_unschedule)

    s = sub.add_parser("delete-draft", help="delete a draft (irreversible)")
    s.add_argument("id")
    s.add_argument("--force", action="store_true")
    add_account_arg(s)
    s.set_defaults(func=cmd_delete_draft)

    s = sub.add_parser("upload-image", help="upload an image, get the CDN URL")
    s.add_argument("file")
    add_account_arg(s)
    s.set_defaults(func=cmd_upload_image)

    s = sub.add_parser("sections", help="list publication sections (for --section-id)")
    add_account_arg(s)
    s.set_defaults(func=cmd_sections)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
