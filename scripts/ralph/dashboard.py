#!/usr/bin/env python3
"""
Ralph Dashboard - 实时监控面板
启动一个本地 HTTP 服务，服务 dashboard.html 并提供 /api/state 接口。
"""

import json
import re
import sys
import threading
import webbrowser
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Windows 控制台默认 GBK 编码，无法输出 emoji → 强制 UTF-8
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent.parent.resolve()
PRD_FILE = SCRIPT_DIR / "prd.json"
PROGRESS_FILE = SCRIPT_DIR / "progress.txt"
AUDIT_GATE_FILE = SCRIPT_DIR / "audit-gate.json"
COST_LOG_FILE = SCRIPT_DIR / "cost-log.jsonl"
RALPH_LOCK_FILE = SCRIPT_DIR / "ralph-lock.json"
HTML_FILE = SCRIPT_DIR / "dashboard.html"
PIXEL_HTML_FILE = SCRIPT_DIR / "dashboard-p.html"
AGENT_LOGS_DIR = SCRIPT_DIR / "agent-logs"
SCREENSHOTS_DIR = PROJECT_ROOT / "screenshots"
SERVER_DIR = PROJECT_ROOT / "server"

MAX_LOG_RESPONSE_BYTES = 256 * 1024  # API 返回 progress.txt 最大 256KB
MAX_AGENT_LOG_TAIL_BYTES = 16 * 1024  # agent-log tail 最大 16KB
MAX_PROMPT_PREVIEW_BYTES = 3 * 1024   # prompt 预览最大 3KB
SCREENSHOT_FILENAME_RE = re.compile(r"^validator-us-\d{3}-(pass|fail)-\d+\.png$")

_state: dict = {
    "iteration": 0,
    "max_iterations": 50,
    "phase": "idle",       # idle | developing | validating | waiting_audit | done | error
    "current_story": None,
    "started_at": None,
}
_state_lock = threading.Lock()
_UNSET = object()  # 哨兵值，区分"不更新"和"设为 None"


def set_state(
    iteration: int | None | object = _UNSET,
    phase: str | None | object = _UNSET,
    current_story: str | None | object = _UNSET,
) -> None:
    with _state_lock:
        if iteration is not _UNSET:
            _state["iteration"] = iteration
        if phase is not _UNSET:
            _state["phase"] = phase
        if current_story is not _UNSET:
            _state["current_story"] = current_story


def _runtime_state_with_fallback() -> tuple[str, int, str | None]:
    """读 _state；若字段为 None，fallback 读 ralph-lock.json 或 audit-gate.json 补齐"""
    with _state_lock:
        phase = _state["phase"]
        iteration = _state["iteration"]
        story_id = _state["current_story"]

    if story_id and phase != "idle":
        return phase, iteration, story_id

    # fallback 1: ralph-lock.json
    try:
        if RALPH_LOCK_FILE.exists():
            lock = json.loads(RALPH_LOCK_FILE.read_text(encoding="utf-8"))
            story_id = story_id or lock.get("story_id")
            iteration = iteration or lock.get("iteration", 0)
            phase = lock.get("phase", phase) if phase == "idle" else phase
    except Exception:
        pass

    # fallback 2: audit-gate.json（phase 可能仍是 idle，但 story_id 从 audit gate 拿）
    if not story_id:
        try:
            if AUDIT_GATE_FILE.exists():
                gate = json.loads(AUDIT_GATE_FILE.read_text(encoding="utf-8"))
                story_id = gate.get("story_id")
                if gate.get("status") == "pending" and phase == "idle":
                    phase = "waiting_audit"
        except Exception:
            pass

    return phase, iteration, story_id


def _read_tail_utf8(path: Path, max_bytes: int) -> str:
    """读文件尾部 max_bytes 字节，UTF-8 解码（边界处截掉不完整字符）"""
    try:
        size = path.stat().st_size
        if size == 0:
            return ""
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                raw = f.read()
                # 丢掉首个可能被截断的字符（直到下一个换行或整 UTF-8 起点）
                nl = raw.find(b"\n")
                if nl > 0:
                    raw = raw[nl + 1:]
            else:
                raw = f.read()
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _read_head_utf8(path: Path, max_bytes: int) -> str:
    """读文件头部 max_bytes 字节"""
    try:
        with path.open("rb") as f:
            raw = f.read(max_bytes)
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _find_current_agent_log() -> dict:
    """扫 agent-logs/ 目录找最新的开发/验证 log（按 phase 挑对应类型）"""
    result = {
        "phase": None,
        "iteration": None,
        "story_id": None,
        "file_name": None,
        "size_bytes": 0,
        "last_modified": None,
        "tail_content": "",
        "prompt_preview": "",
        "prompt_file_name": None,
    }
    phase, iteration, story_id = _runtime_state_with_fallback()
    result["phase"] = phase
    result["iteration"] = iteration
    result["story_id"] = story_id

    if not AGENT_LOGS_DIR.exists():
        return result

    # phase 映射到 agent-log 后缀
    if phase == "developing":
        log_suffix = "_开发迭代.log"
        prompt_suffix = "_开发迭代_prompt.md"
    elif phase == "validating":
        log_suffix = "_验证.log"
        prompt_suffix = "_验证_prompt.md"
    elif phase == "waiting_audit":
        # waiting_audit 阶段展示最近验证 log（刚验完）
        log_suffix = "_验证.log"
        prompt_suffix = "_验证_prompt.md"
    else:
        # idle/done/error 找全局最新的 log
        logs = sorted(AGENT_LOGS_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if logs:
            latest = logs[0]
            result["file_name"] = latest.name
            result["size_bytes"] = latest.stat().st_size
            result["last_modified"] = time.strftime("%H:%M:%S", time.localtime(latest.stat().st_mtime))
            result["tail_content"] = _read_tail_utf8(latest, MAX_AGENT_LOG_TAIL_BYTES)
        return result

    # 匹配对应后缀的最新 log
    matches = sorted(
        [p for p in AGENT_LOGS_DIR.glob(f"*{log_suffix}")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if matches:
        latest = matches[0]
        result["file_name"] = latest.name
        result["size_bytes"] = latest.stat().st_size
        result["last_modified"] = time.strftime("%H:%M:%S", time.localtime(latest.stat().st_mtime))
        result["tail_content"] = _read_tail_utf8(latest, MAX_AGENT_LOG_TAIL_BYTES)

        # 对应的 prompt 文件（相同时间戳前缀）
        stem = latest.name.removesuffix(log_suffix)
        prompt_file = AGENT_LOGS_DIR / f"{stem}{prompt_suffix}"
        if prompt_file.exists():
            result["prompt_file_name"] = prompt_file.name
            result["prompt_preview"] = _read_head_utf8(prompt_file, MAX_PROMPT_PREVIEW_BYTES)

    return result


def _find_current_screenshots(story_id: str | None) -> list:
    """列出当前 story 相关的 validator 截图（含 screenshots/ 和 server/ 两处）"""
    if not story_id:
        return []
    story_lower = story_id.lower()  # US-001 → us-001
    results = []
    for base in (SCREENSHOTS_DIR, SERVER_DIR):
        if not base.exists():
            continue
        for p in base.glob(f"validator-{story_lower}-*.png"):
            if not SCREENSHOT_FILENAME_RE.match(p.name):
                continue
            try:
                stat = p.stat()
                results.append({
                    "name": p.name,
                    "size": stat.st_size,
                    "mtime": int(stat.st_mtime),
                    "mtime_str": time.strftime("%H:%M:%S", time.localtime(stat.st_mtime)),
                    "result": "pass" if "-pass-" in p.name else "fail",
                    "url": f"/screenshot/{p.name}",
                })
            except OSError:
                continue
    # 同名文件（两个目录都有）去重，保留 mtime 更新的
    by_name = {}
    for item in results:
        existing = by_name.get(item["name"])
        if existing is None or item["mtime"] > existing["mtime"]:
            by_name[item["name"]] = item
    return sorted(by_name.values(), key=lambda x: x["mtime"])


def _resolve_screenshot_path(name: str) -> Path | None:
    """在 screenshots/ 和 server/ 中找截图文件，返回首个匹配"""
    if not SCREENSHOT_FILENAME_RE.match(name):
        return None
    for base in (SCREENSHOTS_DIR, SERVER_DIR):
        candidate = base / name
        if candidate.is_file():
            return candidate
    return None


def _build_api_response() -> dict:
    with _state_lock:
        s = dict(_state)

    elapsed = int(time.time() - s["started_at"]) if s["started_at"] else 0

    project = ""
    branch_name = ""
    stories = []
    try:
        prd = json.loads(PRD_FILE.read_text(encoding="utf-8"))
        project = prd.get("project", "")
        branch_name = prd.get("branchName", "")
        stories = prd.get("userStories", [])
    except Exception:
        pass

    logs = ""
    try:
        if PROGRESS_FILE.exists():
            raw = PROGRESS_FILE.read_bytes()
            # H4: 截断过大的 progress.txt 只返回尾部（按字节截断，对多字节 UTF-8 安全）
            if len(raw) > MAX_LOG_RESPONSE_BYTES:
                truncated = raw[-(MAX_LOG_RESPONSE_BYTES // 2):]
                content = truncated.decode("utf-8", errors="ignore")
                first_nl = content.find("\n")
                if first_nl > 0:
                    content = content[first_nl + 1:]
                content = "[... 日志已截断，仅显示最近内容 ...]\n\n" + content
            else:
                content = raw.decode("utf-8", errors="replace")
            logs = content
    except Exception:
        pass

    audit_gate = None
    try:
        if AUDIT_GATE_FILE.exists():
            audit_gate = json.loads(AUDIT_GATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass

    # M14: 成本追踪摘要
    cost_summary = None
    try:
        if COST_LOG_FILE.exists():
            entries = []
            for line in COST_LOG_FILE.read_text(encoding="utf-8").strip().split("\n"):
                if line.strip():
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            if entries:
                total_dev = sum(e.get("duration_seconds", 0) for e in entries if e.get("phase") == "developing")
                total_val = sum(e.get("duration_seconds", 0) for e in entries if e.get("phase") == "validating")
                dev_count = sum(1 for e in entries if e.get("phase") == "developing")
                val_count = sum(1 for e in entries if e.get("phase") == "validating")
                # 重试次数统计
                story_retries = {}
                for e in entries:
                    sid = e.get("story_id", "unknown")
                    if e.get("phase") == "developing":
                        story_retries[sid] = story_retries.get(sid, 0) + 1
                total_retries = sum(max(0, v - 1) for v in story_retries.values())
                cost_summary = {
                    "dev_calls": dev_count,
                    "val_calls": val_count,
                    "dev_seconds": round(total_dev),
                    "val_seconds": round(total_val),
                    "total_seconds": round(total_dev + total_val),
                    "total_retries": total_retries,
                }
    except Exception:
        pass

    # 用 _runtime_state_with_fallback 综合读 _state + ralph-lock + audit-gate
    phase, iteration_fb, current_story = _runtime_state_with_fallback()
    iteration = s["iteration"] if s["iteration"] > 0 else iteration_fb

    # 如果所有 story 都已 resolved（passes 或 blocked），自动修正运行时状态为 done
    if stories and all(st.get("passes") or st.get("blocked") for st in stories):
        phase = "done"
        current_story = None

    # ★ 当前 story 的运行时进度（elapsed_in_phase / screenshots_count / log_bytes）
    phase_elapsed = 0
    phase_started_at = None
    screenshots_count = 0
    log_bytes = 0
    log_file_name = None
    try:
        if RALPH_LOCK_FILE.exists():
            lock = json.loads(RALPH_LOCK_FILE.read_text(encoding="utf-8"))
            phase_started_at = lock.get("started_at")
            if phase_started_at:
                # ISO 格式 parse
                from datetime import datetime
                dt = datetime.fromisoformat(phase_started_at)
                phase_elapsed = int(time.time() - dt.timestamp())
    except Exception:
        pass

    if current_story:
        try:
            shots = _find_current_screenshots(current_story)
            screenshots_count = len(shots)
        except Exception:
            pass

    try:
        agent_log = _find_current_agent_log()
        log_bytes = agent_log.get("size_bytes", 0)
        log_file_name = agent_log.get("file_name")
    except Exception:
        pass

    return {
        "runtime": {
            "iteration": iteration,
            "max_iterations": s["max_iterations"],
            "phase": phase,
            "current_story": current_story,
            "elapsed": elapsed,
            "phase_elapsed": phase_elapsed,
            "phase_started_at": phase_started_at,
            "screenshots_count": screenshots_count,
            "log_bytes": log_bytes,
            "log_file_name": log_file_name,
        },
        "project": project,
        "branchName": branch_name,
        "stories": stories,
        "logs": logs,
        "auditGate": audit_gate,
        "costSummary": cost_summary,
    }


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?")[0]

        if path == "/api/state":
            body = json.dumps(_build_api_response(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == "/api/agent-logs/current":
            body = json.dumps(_find_current_agent_log(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == "/api/screenshots/current":
            _, _, current_story = _runtime_state_with_fallback()
            shots = _find_current_screenshots(current_story)
            payload = {"story_id": current_story, "screenshots": shots}
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path.startswith("/screenshot/"):
            name = path[len("/screenshot/"):]
            fp = _resolve_screenshot_path(name)
            if fp is None:
                self.send_response(404)
                self.end_headers()
                return
            try:
                data = fp.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "public, max-age=60")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                msg = str(e).encode()
                self.send_response(500)
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)

        elif path in ("/", "/index.html"):
            try:
                html = HTML_FILE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
            except Exception as e:
                msg = str(e).encode()
                self.send_response(500)
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)

        elif path in ("/p", "/p.html"):
            try:
                html = PIXEL_HTML_FILE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
            except Exception as e:
                msg = str(e).encode()
                self.send_response(500)
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args) -> None:  # suppress access logs
        pass


def start(port: int = 7331, max_iterations: int = 50, open_browser: bool = True) -> None:
    with _state_lock:
        _state["started_at"] = time.time()
        _state["max_iterations"] = max_iterations

    try:
        server = HTTPServer(("127.0.0.1", port), _Handler)
    except OSError as e:
        print(f"⚠️  Dashboard 启动失败 (端口 {port} 可能被占用): {e}")
        return
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://localhost:{port}"
    print(f"🖥️  Dashboard: {url}")

    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
