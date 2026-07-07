#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local visual Web UI for course_grabber.py.

Run:
    python webui_server.py
Then open:
    http://127.0.0.1:8765
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import subprocess
import re
import sys
import threading
import time
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "webui"
CONFIG_PATH = WEB_DIR / "config.json"
RUNS_PATH = WEB_DIR / "runs.json"
LOG_DIR = ROOT / "logs"
COURSE_GRABBER = ROOT / "course_grabber.py"

DEFAULT_CONFIG: dict[str, Any] = {
    "web_username": "admin",
    "web_password": "",
    "require_auth": False,
    "urp_username": "",
    "urp_password": "",
    "mode": "grab",
    "category": "free",
    "course_id": "888006010A07_01,888006010A07_14",
    "kch": "888006010A07",
    "kxh": "",
    "name": "体育-3网球",
    "teacher": "",
    "search": "",
    "limit": 20,
    "interval": 1.35,
    "jitter": 0.9,
    "max_attempts": 600,
    "confirm_attempts": 4,
    "quiet_login": True,
    "dry_run": False,
    "once": False,
    "no_confirm": False,
    "extra_args": "",
}

CURRENT: dict[str, Any] = {"process": None, "run": None, "lock": threading.Lock()}
SESSIONS: set[str] = set()


def ensure_dirs() -> None:
    WEB_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)
    if not CONFIG_PATH.exists():
        write_json(CONFIG_PATH, DEFAULT_CONFIG)
    if not RUNS_PATH.exists():
        write_json(RUNS_PATH, [])


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def norm_config(data: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    for k in cfg:
        if k in data:
            cfg[k] = data[k]
    for k in ["require_auth", "quiet_login", "dry_run", "once", "no_confirm"]:
        cfg[k] = bool(cfg.get(k))
    for k in ["limit", "max_attempts", "confirm_attempts"]:
        try:
            cfg[k] = int(cfg.get(k) or 0)
        except Exception:
            cfg[k] = DEFAULT_CONFIG[k]
    for k in ["interval", "jitter"]:
        try:
            cfg[k] = float(cfg.get(k) or 0)
        except Exception:
            cfg[k] = DEFAULT_CONFIG[k]
    if cfg["mode"] not in {"list", "grab"}:
        cfg["mode"] = "grab"
    if cfg["category"] not in {"intent", "plan", "school", "depart", "free"}:
        cfg["category"] = "free"
    return cfg


def split_extra_args(s: str) -> list[str]:
    # Lightweight split for simple flags/values. Quote-heavy cases can be put in normal fields.
    import shlex
    try:
        return shlex.split(s or "", posix=False)
    except Exception:
        return []


def build_args(cfg: dict[str, Any]) -> list[str]:
    args = [sys.executable, str(COURSE_GRABBER)]
    # Credentials are passed through child environment, not command line,
    # so process lists and runs.json do not expose the password.
    if cfg.get("quiet_login"):
        args.append("--quiet-login")
    args += [cfg["mode"], "--category", str(cfg["category"])]
    field_flags = [
        ("course_id", "--course-id"), ("kch", "--kch"), ("kxh", "--kxh"),
        ("name", "--name"), ("teacher", "--teacher"), ("search", "--search"),
    ]
    for key, flag in field_flags:
        value = str(cfg.get(key) or "").strip()
        if value:
            args += [flag, value]
    if int(cfg.get("limit") or 0) > 0:
        args += ["--limit", str(int(cfg["limit"]))]
    if cfg.get("dry_run"):
        args.append("--dry-run")
    if cfg.get("no_confirm"):
        args.append("--no-confirm")
    if cfg["mode"] == "grab":
        args += ["--interval", str(cfg["interval"]), "--jitter", str(cfg["jitter"])]
        if int(cfg.get("max_attempts") or 0) > 0:
            args += ["--max-attempts", str(int(cfg["max_attempts"]))]
        if int(cfg.get("confirm_attempts") or 0) > 0:
            args += ["--confirm-attempts", str(int(cfg["confirm_attempts"]))]
        if cfg.get("once"):
            args.append("--once")
    args += split_extra_args(str(cfg.get("extra_args") or ""))
    return args


def process_alive(proc: subprocess.Popen | None) -> bool:
    return proc is not None and proc.poll() is None


def add_run(run: dict[str, Any]) -> None:
    runs = read_json(RUNS_PATH, [])
    runs.insert(0, run)
    write_json(RUNS_PATH, runs[:200])


def update_run_record(run: dict[str, Any]) -> None:
    runs = read_json(RUNS_PATH, [])
    key = run.get("stdout")
    replaced = False
    for i, item in enumerate(runs):
        if item.get("stdout") == key:
            runs[i] = run
            replaced = True
            break
    if not replaced:
        runs.insert(0, run)
    write_json(RUNS_PATH, runs[:200])


def latest_run() -> dict[str, Any] | None:
    runs = read_json(RUNS_PATH, [])
    if runs:
        return runs[0]
    files = sorted(LOG_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if files:
        return {"status": "log-only", "stdout": str(files[0].resolve()), "started_at": datetime.fromtimestamp(files[0].stat().st_mtime).isoformat(timespec="seconds")}
    return None


def update_current_run_status() -> None:
    with CURRENT["lock"]:
        proc = CURRENT.get("process")
        run = CURRENT.get("run")
        if run and proc and proc.poll() is not None:
            run["status"] = "exited"
            run["returncode"] = proc.returncode
            run["ended_at"] = datetime.now().isoformat(timespec="seconds")
            CURRENT["process"] = None
            CURRENT["run"] = run
            update_run_record(run)


def tail_file(path: Path, lines: int = 200) -> str:
    if not path.exists():
        return ""
    # Efficient enough for normal logs; cap bytes to avoid huge responses.
    data = path.read_bytes()[-512_000:]
    text = data.decode("utf-8", errors="replace")
    return "\n".join(text.splitlines()[-lines:])


def stats_from_text(text: str) -> dict[str, int]:
    return {
        "attempts": text.count("轮询") + text.count("尝试") + text.count("第"),
        "submit": text.count("提交目标"),
        "selected": text.count('"final_status": "selected"') + text.count("提交成功"),
        "failed": text.count('"final_status": "failed"') + text.count("失败"),
        "bad_gateway": text.count("502") + text.count("503") + text.count("504"),
    }


def selected_alerts_from_text(text: str) -> list[dict[str, str]]:
    """Extract compact selected-course alerts from log text."""
    lines = text.splitlines()
    alerts: list[dict[str, str]] = []
    seen: set[str] = set()
    for i, line in enumerate(lines):
        if '"final_status": "selected"' not in line and '????' not in line:
            continue
        start = max(0, i - 10)
        end = min(len(lines), i + 8)
        snippet_lines = [x for x in lines[start:end] if x.strip()]
        snippet = "\n".join(snippet_lines)[-1800:]
        course = ""
        m = re.search(r"[A-Za-z0-9]+_[0-9A-Za-z]+(?:_[0-9]{4}-[0-9]{4}-[0-9]-[0-9])?", snippet)
        if m:
            course = m.group(0)
        key = course or snippet[-200:]
        if key in seen:
            continue
        seen.add(key)
        alerts.append({"course": course or "?????", "message": snippet})
    return alerts[-20:]


def redact_run(run: dict[str, Any]) -> dict[str, Any]:
    safe = json.loads(json.dumps(run, ensure_ascii=False))
    cfg = safe.get("config")
    if isinstance(cfg, dict):
        for k in ["urp_password", "web_password"]:
            if cfg.get(k):
                cfg[k] = "******"
    args = safe.get("args")
    if isinstance(args, list):
        for i, v in enumerate(args[:-1]):
            if v in {"--password"}:
                args[i + 1] = "******"
    return safe


def public_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return config for browser. Passwords are kept in inputs for local editing."""
    return cfg


def parse_cookies(header: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (header or "").split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            out[k] = v
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "URPQWebUI/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), fmt % args))


    def is_authed(self) -> bool:
        cfg = norm_config(read_json(CONFIG_PATH, DEFAULT_CONFIG))
        if not cfg.get("require_auth"):
            return True
        token = parse_cookies(self.headers.get("Cookie", "")).get("urpq_session", "")
        return bool(token and token in SESSIONS)

    def require_auth_or_401(self) -> bool:
        if self.is_authed():
            return True
        if urlparse(self.path).path.startswith("/api/"):
            return self.send_json({"ok": False, "error": "unauthorized"}, 401) or False
        self.send_response(302)
        self.send_header("Location", "/login.html")
        self.end_headers()
        return False

    def send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        ensure_dirs()
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        update_current_run_status()
        if path == "/":
            path = "/index.html"
        if path == "/login.html":
            pass
        elif not self.require_auth_or_401():
            return
        if path == "/api/config":
            return self.send_json(public_config(norm_config(read_json(CONFIG_PATH, DEFAULT_CONFIG))))
        if path == "/api/status":
            with CURRENT["lock"]:
                proc = CURRENT.get("process")
                run = CURRENT.get("run")
                alive = process_alive(proc)
                code = None if not proc else proc.poll()
            visible_run = run or latest_run()
            active_log = visible_run.get("stdout") if visible_run else None
            text = tail_file(Path(active_log), 300) if active_log else ""
            return self.send_json({"running": alive, "returncode": code, "run": redact_run(visible_run) if visible_run else None, "stats": stats_from_text(text), "selected_alerts": selected_alerts_from_text(text)})
        if path == "/api/logs":
            runs = read_json(RUNS_PATH, [])
            files = sorted(LOG_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
            return self.send_json({"runs": [redact_run(r) for r in runs], "files": [str(p) for p in files[:100]]})
        if path == "/api/tail":
            file_arg = qs.get("file", [""])[0]
            lines = int(qs.get("lines", ["200"])[0] or 200)
            with CURRENT["lock"]:
                run = CURRENT.get("run")
            visible_run = run or latest_run()
            target = Path(file_arg) if file_arg else Path(visible_run["stdout"]) if visible_run else None
            if not target:
                return self.send_json({"text": "", "stats": {}})
            target = target.resolve()
            # Only serve project logs to avoid arbitrary file read from browser.
            if LOG_DIR.resolve() not in [target.parent, *target.parents]:
                return self.send_json({"error": "log path out of logs directory"}, 400)
            text = tail_file(target, lines)
            return self.send_json({"file": str(target), "text": text, "stats": stats_from_text(text), "selected_alerts": selected_alerts_from_text(text)})
        if path == "/api/stream":
            return self.stream_logs(qs)

        file_path = (WEB_DIR / path.lstrip("/")).resolve()
        if WEB_DIR.resolve() not in [file_path.parent, *file_path.parents] or not file_path.exists() or file_path.is_dir():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        ctype = "text/html; charset=utf-8" if file_path.suffix == ".html" else "text/plain; charset=utf-8"
        if file_path.suffix == ".css": ctype = "text/css; charset=utf-8"
        if file_path.suffix == ".js": ctype = "application/javascript; charset=utf-8"
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        ensure_dirs()
        path = urlparse(self.path).path
        try:
            data = self.read_body_json()
            if path == "/api/login":
                cfg = norm_config(read_json(CONFIG_PATH, DEFAULT_CONFIG))
                user_ok = str(data.get("username") or "") == str(cfg.get("web_username") or "admin")
                pwd_ok = str(data.get("password") or "") == str(cfg.get("web_password") or "")
                if user_ok and pwd_ok:
                    token = secrets.token_urlsafe(32)
                    SESSIONS.add(token)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Set-Cookie", f"urpq_session={token}; HttpOnly; SameSite=Lax; Path=/")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8"))
                    return
                return self.send_json({"ok": False, "error": "???????"}, 401)
            if path == "/api/logout":
                token = parse_cookies(self.headers.get("Cookie", "")).get("urpq_session", "")
                SESSIONS.discard(token)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", "urpq_session=; Max-Age=0; Path=/")
                self.end_headers()
                self.wfile.write(b"{\"ok\":true}")
                return
            if not self.require_auth_or_401():
                return
            if path == "/api/config":
                cfg = norm_config(data)
                write_json(CONFIG_PATH, cfg)
                return self.send_json({"ok": True, "config": cfg})
            if path == "/api/start":
                cfg = norm_config(data or read_json(CONFIG_PATH, DEFAULT_CONFIG))
                write_json(CONFIG_PATH, cfg)
                with CURRENT["lock"]:
                    if process_alive(CURRENT.get("process")):
                        return self.send_json({"ok": False, "error": "已有任务正在运行"}, 409)
                    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    suffix = secrets.token_hex(3)
                    base = f"{cfg['mode']}_{cfg['category']}_{stamp}_{suffix}"
                    stdout = LOG_DIR / f"{base}.log"
                    stderr = LOG_DIR / f"{base}.err.log"
                    args = build_args(cfg)
                    # Append mode + unique filename: no user's historical log is cleared or overwritten.
                    out = open(stdout, "a", encoding="utf-8", buffering=1)
                    err = open(stderr, "a", encoding="utf-8", buffering=1)
                    child_env = os.environ.copy()
                    if str(cfg.get("urp_username") or "").strip():
                        child_env["SCU_USERNAME"] = str(cfg.get("urp_username")).strip()
                    if str(cfg.get("urp_password") or ""):
                        child_env["SCU_PASSWORD"] = str(cfg.get("urp_password"))
                    proc = subprocess.Popen(args, cwd=str(ROOT), stdout=out, stderr=err, text=True, env=child_env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    run = {
                        "pid": proc.pid, "status": "running", "returncode": None,
                        "started_at": datetime.now().isoformat(timespec="seconds"),
                        "ended_at": None, "stdout": str(stdout.resolve()), "stderr": str(stderr.resolve()),
                        "args": args, "config": cfg,
                    }
                    CURRENT["process"] = proc
                    CURRENT["run"] = run
                    add_run(run)
                return self.send_json({"ok": True, "run": redact_run(run) if run else None})
            if path == "/api/stop":
                with CURRENT["lock"]:
                    proc = CURRENT.get("process")
                    run = CURRENT.get("run")
                    if not process_alive(proc):
                        return self.send_json({"ok": True, "message": "没有正在运行的任务"})
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    if run:
                        run["status"] = "stopped"
                        run["returncode"] = proc.returncode
                        run["ended_at"] = datetime.now().isoformat(timespec="seconds")
                        update_run_record(run)
                    CURRENT["process"] = None
                    CURRENT["run"] = run
                return self.send_json({"ok": True, "run": redact_run(run) if run else None})
            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as e:
            self.send_json({"ok": False, "error": repr(e)}, 500)

    def stream_logs(self, qs: dict[str, list[str]]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        file_arg = qs.get("file", [""])[0]
        pos = 0
        while True:
            update_current_run_status()
            with CURRENT["lock"]:
                run = CURRENT.get("run")
                running = process_alive(CURRENT.get("process"))
            visible_run = run or latest_run()
            target = Path(file_arg) if file_arg else Path(visible_run["stdout"]) if visible_run else None
            if target and target.exists():
                size = target.stat().st_size
                if pos == 0:
                    pos = max(0, size - 64_000)
                if size < pos:
                    pos = 0
                with open(target, "rb") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                if chunk:
                    text = chunk.decode("utf-8", errors="replace")
                    payload = json.dumps({"text": text, "running": running, "file": str(target.resolve())}, ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
            else:
                payload = json.dumps({"text": "", "running": running}, ensure_ascii=False)
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
            if not running and run:
                # Keep connection alive a little, then let browser reconnect.
                time.sleep(1)
            time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="URP抢课可视化网页")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    ensure_dirs()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"可视化网页已启动：http://{args.host}:{args.port}")
    print(f"项目目录：{ROOT}")
    print("按 Ctrl+C 退出；已启动的抢课子进程可在网页停止。")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()


