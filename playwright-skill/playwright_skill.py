#!/usr/bin/env python3
"""
Playwright Skill - Browser automation for web tasks.

Supports persistent sessions, screenshots, data extraction, and form automation.

Usage:
    python playwright_skill.py open URL [--session NAME] [--headless]
    python playwright_skill.py screenshot URL [--output FILE] [--full-page] [--session NAME]
    python playwright_skill.py click SELECTOR [--session NAME]
    python playwright_skill.py type SELECTOR TEXT [--session NAME]
    python playwright_skill.py extract SELECTOR [--attr ATTR] [--all] [--session NAME]
    python playwright_skill.py eval JAVASCRIPT [--session NAME]
    python playwright_skill.py wait SELECTOR [--timeout MS] [--session NAME]
    python playwright_skill.py scroll [--direction up|down] [--amount PIXELS] [--session NAME]
    python playwright_skill.py pdf URL [--output FILE] [--session NAME]
    python playwright_skill.py sessions
    python playwright_skill.py close [--session NAME]
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
except ImportError:
    print("Error: playwright not installed.")
    print("Install with: pip install playwright && playwright install")
    sys.exit(1)

# Paths
SKILL_DIR = Path(__file__).parent
SESSIONS_DIR = SKILL_DIR / "sessions"
STATE_FILE = SKILL_DIR / "browser_state.json"

# Ensure directories exist
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

# Global state for persistent browser
_playwright = None
_browser = None
_contexts: dict[str, BrowserContext] = {}
_pages: dict[str, Page] = {}


def get_session_path(session_name: str) -> Path:
    """Get the storage state path for a session."""
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_name)
    return SESSIONS_DIR / f"{safe_name}.json"


def load_state() -> dict:
    """Load browser state."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"sessions": {}}


def save_state(state: dict):
    """Save browser state."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_browser(headless: bool = True) -> Browser:
    """Get or create browser instance."""
    global _playwright, _browser

    if _browser is None or not _browser.is_connected():
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
        )
    return _browser


def get_context(session_name: str = "default", headless: bool = True) -> BrowserContext:
    """Get or create browser context for a session."""
    global _contexts

    if session_name in _contexts:
        return _contexts[session_name]

    browser = get_browser(headless)
    session_path = get_session_path(session_name)

    # Load existing session state if available
    if session_path.exists():
        try:
            context = browser.new_context(
                storage_state=str(session_path),
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        except:
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
    else:
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

    _contexts[session_name] = context
    return context


def get_page(session_name: str = "default", headless: bool = True) -> Page:
    """Get or create page for a session."""
    global _pages

    if session_name in _pages:
        try:
            # Check if page is still valid
            _pages[session_name].title()
            return _pages[session_name]
        except:
            pass

    context = get_context(session_name, headless)
    pages = context.pages

    if pages:
        page = pages[0]
    else:
        page = context.new_page()

    _pages[session_name] = page
    return page


def save_session(session_name: str):
    """Save session state to disk."""
    if session_name in _contexts:
        session_path = get_session_path(session_name)
        _contexts[session_name].storage_state(path=str(session_path))

        state = load_state()
        state["sessions"][session_name] = {
            "path": str(session_path),
            "updated": datetime.now().isoformat()
        }
        save_state(state)


def close_session(session_name: str):
    """Close a session and save state."""
    save_session(session_name)

    if session_name in _pages:
        try:
            _pages[session_name].close()
        except:
            pass
        del _pages[session_name]

    if session_name in _contexts:
        try:
            _contexts[session_name].close()
        except:
            pass
        del _contexts[session_name]


def close_all():
    """Close all sessions and browser."""
    global _playwright, _browser, _contexts, _pages

    for session_name in list(_contexts.keys()):
        close_session(session_name)

    if _browser:
        try:
            _browser.close()
        except:
            pass
        _browser = None

    if _playwright:
        try:
            _playwright.stop()
        except:
            pass
        _playwright = None


# ============ Commands ============


def cmd_open(args):
    """Open a URL in the browser."""
    headless = args.headless if hasattr(args, 'headless') else True
    page = get_page(args.session, headless=not args.visible if hasattr(args, 'visible') else headless)

    page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
    save_session(args.session)

    print(json.dumps({
        "success": True,
        "url": page.url,
        "title": page.title(),
        "session": args.session
    }, indent=2))


def cmd_screenshot(args):
    """Take a screenshot."""
    page = get_page(args.session)

    if args.url:
        page.goto(args.url, wait_until="domcontentloaded", timeout=30000)

    output = args.output or f"screenshot_{int(time.time())}.png"

    page.screenshot(
        path=output,
        full_page=args.full_page
    )

    save_session(args.session)

    print(json.dumps({
        "success": True,
        "file": output,
        "url": page.url,
        "full_page": args.full_page
    }, indent=2))


def cmd_click(args):
    """Click an element."""
    page = get_page(args.session)

    page.click(args.selector, timeout=10000)
    page.wait_for_load_state("domcontentloaded")
    save_session(args.session)

    print(json.dumps({
        "success": True,
        "selector": args.selector,
        "url": page.url
    }, indent=2))


def cmd_type(args):
    """Type text into an element."""
    page = get_page(args.session)

    if args.clear:
        page.fill(args.selector, args.text, timeout=10000)
    else:
        page.type(args.selector, args.text, timeout=10000, delay=50)

    save_session(args.session)

    print(json.dumps({
        "success": True,
        "selector": args.selector,
        "text": args.text[:50] + "..." if len(args.text) > 50 else args.text
    }, indent=2))


def cmd_extract(args):
    """Extract text or attributes from elements."""
    page = get_page(args.session)

    if args.all:
        elements = page.query_selector_all(args.selector)
        results = []
        for el in elements:
            if args.attr:
                results.append(el.get_attribute(args.attr))
            else:
                results.append(el.text_content())
        print(json.dumps({
            "success": True,
            "count": len(results),
            "data": results
        }, indent=2))
    else:
        element = page.query_selector(args.selector)
        if element:
            if args.attr:
                value = element.get_attribute(args.attr)
            else:
                value = element.text_content()
            print(json.dumps({
                "success": True,
                "data": value
            }, indent=2))
        else:
            print(json.dumps({
                "success": False,
                "error": f"Element not found: {args.selector}"
            }, indent=2))


def cmd_eval(args):
    """Evaluate JavaScript in the page."""
    page = get_page(args.session)

    result = page.evaluate(args.javascript)
    save_session(args.session)

    print(json.dumps({
        "success": True,
        "result": result
    }, indent=2, default=str))


def cmd_wait(args):
    """Wait for an element to appear."""
    page = get_page(args.session)

    timeout = args.timeout or 30000

    try:
        page.wait_for_selector(args.selector, timeout=timeout)
        print(json.dumps({
            "success": True,
            "selector": args.selector
        }, indent=2))
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": str(e)
        }, indent=2))


def cmd_scroll(args):
    """Scroll the page."""
    page = get_page(args.session)

    amount = args.amount or 500
    if args.direction == "up":
        amount = -amount

    page.evaluate(f"window.scrollBy(0, {amount})")

    print(json.dumps({
        "success": True,
        "direction": args.direction,
        "amount": abs(amount)
    }, indent=2))


def cmd_pdf(args):
    """Save page as PDF."""
    page = get_page(args.session)

    if args.url:
        page.goto(args.url, wait_until="domcontentloaded", timeout=30000)

    output = args.output or f"page_{int(time.time())}.pdf"

    page.pdf(path=output, format="A4", print_background=True)

    print(json.dumps({
        "success": True,
        "file": output,
        "url": page.url
    }, indent=2))


def cmd_sessions(args):
    """List active and saved sessions."""
    state = load_state()
    saved = []

    for name, info in state.get("sessions", {}).items():
        session_path = Path(info.get("path", ""))
        saved.append({
            "name": name,
            "exists": session_path.exists(),
            "updated": info.get("updated")
        })

    print(json.dumps({
        "active": list(_contexts.keys()),
        "saved": saved
    }, indent=2))


def cmd_close(args):
    """Close a session or all sessions."""
    if args.all:
        close_all()
        print(json.dumps({"success": True, "message": "All sessions closed"}))
    else:
        close_session(args.session)
        print(json.dumps({"success": True, "session": args.session}))


def cmd_html(args):
    """Get page HTML content."""
    page = get_page(args.session)

    if args.selector:
        element = page.query_selector(args.selector)
        if element:
            html = element.inner_html()
        else:
            print(json.dumps({"success": False, "error": "Element not found"}))
            return
    else:
        html = page.content()

    if args.output:
        with open(args.output, "w") as f:
            f.write(html)
        print(json.dumps({"success": True, "file": args.output, "length": len(html)}))
    else:
        print(json.dumps({"success": True, "html": html[:5000] + "..." if len(html) > 5000 else html}))


def cmd_cookies(args):
    """Get or set cookies."""
    context = get_context(args.session)

    if args.set:
        # Parse cookie string: name=value
        name, value = args.set.split("=", 1)
        context.add_cookies([{
            "name": name,
            "value": value,
            "domain": args.domain or ".example.com",
            "path": "/"
        }])
        save_session(args.session)
        print(json.dumps({"success": True, "cookie": name}))
    else:
        cookies = context.cookies()
        if args.name:
            cookies = [c for c in cookies if c["name"] == args.name]
        print(json.dumps({"success": True, "cookies": cookies}, indent=2))


def add_session_arg(parser):
    """Add --session argument to a parser."""
    parser.add_argument(
        "--session", "-s",
        default="default",
        help="Session name for persistent state (default: 'default')"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Playwright Skill - Browser automation for web tasks"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Open
    open_parser = subparsers.add_parser("open", help="Open a URL")
    open_parser.add_argument("url", help="URL to open")
    open_parser.add_argument("--visible", "-v", action="store_true", help="Show browser window")
    add_session_arg(open_parser)
    open_parser.set_defaults(func=cmd_open)

    # Screenshot
    screenshot_parser = subparsers.add_parser("screenshot", help="Take a screenshot")
    screenshot_parser.add_argument("url", nargs="?", help="URL to screenshot (optional if page already open)")
    screenshot_parser.add_argument("--output", "-o", help="Output filename")
    screenshot_parser.add_argument("--full-page", "-f", action="store_true", help="Capture full page")
    add_session_arg(screenshot_parser)
    screenshot_parser.set_defaults(func=cmd_screenshot)

    # Click
    click_parser = subparsers.add_parser("click", help="Click an element")
    click_parser.add_argument("selector", help="CSS selector or text")
    add_session_arg(click_parser)
    click_parser.set_defaults(func=cmd_click)

    # Type
    type_parser = subparsers.add_parser("type", help="Type text into an element")
    type_parser.add_argument("selector", help="CSS selector")
    type_parser.add_argument("text", help="Text to type")
    type_parser.add_argument("--clear", "-c", action="store_true", help="Clear field before typing")
    add_session_arg(type_parser)
    type_parser.set_defaults(func=cmd_type)

    # Extract
    extract_parser = subparsers.add_parser("extract", help="Extract text/attributes from elements")
    extract_parser.add_argument("selector", help="CSS selector")
    extract_parser.add_argument("--attr", "-a", help="Attribute to extract (default: text content)")
    extract_parser.add_argument("--all", action="store_true", help="Extract from all matching elements")
    add_session_arg(extract_parser)
    extract_parser.set_defaults(func=cmd_extract)

    # Eval
    eval_parser = subparsers.add_parser("eval", help="Evaluate JavaScript")
    eval_parser.add_argument("javascript", help="JavaScript code to execute")
    add_session_arg(eval_parser)
    eval_parser.set_defaults(func=cmd_eval)

    # Wait
    wait_parser = subparsers.add_parser("wait", help="Wait for an element")
    wait_parser.add_argument("selector", help="CSS selector to wait for")
    wait_parser.add_argument("--timeout", "-t", type=int, help="Timeout in milliseconds")
    add_session_arg(wait_parser)
    wait_parser.set_defaults(func=cmd_wait)

    # Scroll
    scroll_parser = subparsers.add_parser("scroll", help="Scroll the page")
    scroll_parser.add_argument("--direction", "-d", choices=["up", "down"], default="down")
    scroll_parser.add_argument("--amount", "-a", type=int, help="Pixels to scroll")
    add_session_arg(scroll_parser)
    scroll_parser.set_defaults(func=cmd_scroll)

    # PDF
    pdf_parser = subparsers.add_parser("pdf", help="Save page as PDF")
    pdf_parser.add_argument("url", nargs="?", help="URL to save")
    pdf_parser.add_argument("--output", "-o", help="Output filename")
    add_session_arg(pdf_parser)
    pdf_parser.set_defaults(func=cmd_pdf)

    # HTML
    html_parser = subparsers.add_parser("html", help="Get page HTML")
    html_parser.add_argument("--selector", help="Get HTML of specific element")
    html_parser.add_argument("--output", "-o", help="Save to file")
    add_session_arg(html_parser)
    html_parser.set_defaults(func=cmd_html)

    # Cookies
    cookies_parser = subparsers.add_parser("cookies", help="Get or set cookies")
    cookies_parser.add_argument("--name", "-n", help="Filter by cookie name")
    cookies_parser.add_argument("--set", help="Set cookie (name=value)")
    cookies_parser.add_argument("--domain", help="Domain for setting cookie")
    add_session_arg(cookies_parser)
    cookies_parser.set_defaults(func=cmd_cookies)

    # Sessions
    sessions_parser = subparsers.add_parser("sessions", help="List sessions")
    sessions_parser.set_defaults(func=cmd_sessions)

    # Close
    close_parser = subparsers.add_parser("close", help="Close session(s)")
    close_parser.add_argument("--all", action="store_true", help="Close all sessions")
    add_session_arg(close_parser)
    close_parser.set_defaults(func=cmd_close)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    finally:
        # Don't auto-close - sessions persist
        pass


if __name__ == "__main__":
    main()
