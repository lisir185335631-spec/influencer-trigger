#!/usr/bin/env python3
"""
Ralph v2 - 自主 AI Agent 循环执行器（含 Validator）
Coding 3.0 升级：崩溃恢复 + 成本追踪 + 显式 Story ID 传递 + prd.json 备份 + 级联失败处理
"""

import json
import sys
import subprocess
import time
import os
import shutil
import atexit
from pathlib import Path
from datetime import datetime

# Windows 控制台默认 GBK 编码，无法输出 emoji → 强制 UTF-8
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import dashboard
except ImportError:
    # dashboard.py 未复制到项目 → 降级：所有 dashboard 调用变为 no-op
    class _DashboardStub:
        @staticmethod
        def start(**kwargs): pass
        @staticmethod
        def set_state(**kwargs): pass
    dashboard = _DashboardStub()
    print("⚠️  dashboard.py 未找到，监控面板不可用（不影响执行）")

# ─────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────
MAX_ITERATIONS = 50
TIMEOUT_SECONDS = 30 * 60          # 开发 Agent 超时：30 分钟
VALIDATOR_TIMEOUT_SECONDS = 60 * 60  # Validator 超时：60 分钟
MAX_BACKUPS = 10                   # prd.json 备份保留数量
AUDIT_POLL_INTERVAL = 30           # 审计门禁轮询间隔（秒）

# Agent 选择：支持 "claude"（默认）或 "codex"
_positional_args = [a for a in sys.argv[1:] if not a.startswith("--")]
AGENT = _positional_args[0] if _positional_args else "claude"

# 审计门禁开关：默认启用，--no-audit-gate 关闭（调试用）
NO_AUDIT_GATE = "--no-audit-gate" in sys.argv

# ─────────────────────────────────────────────
# 路径配置
# ─────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent.parent
CLAUDE_INSTRUCTION_FILE = SCRIPT_DIR / "CLAUDE.md"
VALIDATOR_INSTRUCTION_FILE = SCRIPT_DIR / "VALIDATOR.md"
PRD_FILE = SCRIPT_DIR / "prd.json"
PROGRESS_FILE = SCRIPT_DIR / "progress.txt"
LOCK_FILE = SCRIPT_DIR / "ralph-lock.json"
AUDIT_GATE_FILE = SCRIPT_DIR / "audit-gate.json"
COST_LOG_FILE = SCRIPT_DIR / "cost-log.jsonl"
BACKUP_DIR = SCRIPT_DIR / "backups"


# ─────────────────────────────────────────────
# 命令构建
# ─────────────────────────────────────────────
def build_cmd(prompt: str) -> list[str]:
    """根据 AGENT 配置构建命令"""
    import platform
    if AGENT == "codex":
        return ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", prompt]
    # Windows 下 subprocess 需要用 .cmd 扩展名
    claude_bin = "claude.cmd" if platform.system() == "Windows" else "claude"
    return [claude_bin, "--print", "--dangerously-skip-permissions", "--model", "sonnet", prompt]


def build_process_cmd(prompt: str) -> list[str]:
    """构建子进程命令，兼容 Windows（跳过 Unix PTY）"""
    import platform
    cmd = build_cmd(prompt)
    if platform.system() != "Windows":
        return ["script", "-q", "/dev/null"] + cmd
    return cmd


# ─────────────────────────────────────────────
# prd.json 读写
# ─────────────────────────────────────────────
def read_prd() -> dict | None:
    """安全读取 prd.json"""
    try:
        return json.loads(PRD_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️  读取 prd.json 失败: {e}")
        return None


def get_story_by_id(prd: dict, story_id: str) -> dict | None:
    """根据 ID 获取 story"""
    for story in prd.get("userStories", []):
        if story.get("id") == story_id:
            return story
    return None


def get_current_story_id() -> str | None:
    """返回 prd.json 中第一个 passes=False、blocked=False、且依赖已满足的 story ID"""
    prd = read_prd()
    if not prd:
        return None
    for story in prd.get("userStories", []):
        if story.get("passes", False) or story.get("blocked", False):
            continue
        # 检查 depends_on 依赖是否全部已通过
        depends_on = story.get("depends_on", [])
        deps_met = True
        for dep_id in depends_on:
            dep = get_story_by_id(prd, dep_id)
            if not dep or not dep.get("passes", False):
                deps_met = False
                break
        if deps_met:
            return story.get("id")
    return None


def all_stories_resolved() -> bool:
    """检查是否所有 story 都已完成或被 blocked"""
    prd = read_prd()
    if not prd:
        return False
    for story in prd.get("userStories", []):
        if not story.get("passes", False) and not story.get("blocked", False):
            return False
    return True


# ─────────────────────────────────────────────
# P0: prd.json 备份机制
# ─────────────────────────────────────────────
def backup_prd(iteration: int) -> None:
    """在每次 iteration 开始前备份 prd.json，保留最近 MAX_BACKUPS 个"""
    if not PRD_FILE.exists():
        return

    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_name = f"prd.json.bak.{iteration:03d}.{timestamp}"
    backup_path = BACKUP_DIR / backup_name

    try:
        shutil.copy2(PRD_FILE, backup_path)
    except Exception as e:
        print(f"⚠️  prd.json 备份失败: {e}")
        return

    # 清理旧备份，保留最近 MAX_BACKUPS 个
    backups = sorted(BACKUP_DIR.glob("prd.json.bak.*"), key=lambda p: p.stat().st_mtime)
    while len(backups) > MAX_BACKUPS:
        oldest = backups.pop(0)
        try:
            oldest.unlink()
        except Exception:
            pass


# ─────────────────────────────────────────────
# P0: 崩溃恢复 - Lock File 机制
# ─────────────────────────────────────────────
def is_pid_alive(pid: int) -> bool:
    """跨平台检测 PID 是否存活"""
    import platform
    if platform.system() == "Windows":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            return str(pid) in result.stdout
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def write_lock(iteration: int, phase: str, story_id: str | None) -> None:
    """写入 lock file"""
    lock_data = {
        "pid": os.getpid(),
        "iteration": iteration,
        "phase": phase,
        "story_id": story_id,
        "started_at": datetime.now().isoformat(),
    }
    try:
        LOCK_FILE.write_text(json.dumps(lock_data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"⚠️  写入 lock file 失败: {e}")


def read_lock() -> dict | None:
    """读取 lock file"""
    try:
        if LOCK_FILE.exists():
            return json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def clear_lock() -> None:
    """清除 lock file"""
    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
    except Exception:
        pass


def check_crash_recovery() -> int:
    """
    检查是否有上次崩溃的遗留 lock file。
    返回值：应该从第几个 iteration 开始（1 = 从头开始）
    """
    lock = read_lock()
    if not lock:
        return 1

    old_pid = lock.get("pid", -1)
    old_iteration = lock.get("iteration", 1)
    old_phase = lock.get("phase", "unknown")
    old_story = lock.get("story_id", "unknown")
    old_time = lock.get("started_at", "unknown")

    # 如果旧进程还活着，说明已经有一个 ralph 在跑
    if is_pid_alive(old_pid) and old_pid != os.getpid():
        print(f"❌ 检测到另一个 Ralph 进程正在运行 (PID: {old_pid})")
        print(f"   如果确认无残留进程，请删除 {LOCK_FILE}")
        sys.exit(1)

    # 旧进程已死 → 崩溃恢复
    print(f"\n{'='*64}")
    print(f"  🔄 检测到上次崩溃的遗留状态")
    print(f"     上次中断于: 迭代 {old_iteration}, 阶段: {old_phase}")
    print(f"     Story: {old_story}")
    print(f"     时间: {old_time}")
    print(f"{'='*64}")

    # 安全措施：developing/validating 阶段崩溃时，如果 story 的 passes=true 但验证未完成，
    # 必须重置为 false。但 waiting_audit 阶段不重置（story 已通过验证，只是等待审计）。
    if old_story and old_story != "unknown":
        prd = read_prd()
        if prd:
            s = get_story_by_id(prd, old_story)
            if s and s.get("passes", False) and old_phase != "waiting_audit":
                s["passes"] = False
                s["notes"] = (s.get("notes", "") + f"\n[崩溃恢复] {old_phase}阶段中断，passes 已重置为 false").strip()
                try:
                    PRD_FILE.write_text(json.dumps(prd, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(f"  ⚠️  已重置 {old_story} passes → false（{old_phase}阶段崩溃，验证未完成）")
                except Exception:
                    pass

    if old_phase == "developing":
        print(f"  → 开发阶段中断，将从迭代 {old_iteration} 重试 {old_story}")
    elif old_phase == "validating":
        print(f"  → 验证阶段中断，将从迭代 {old_iteration} 重新开始")
    elif old_phase == "waiting_audit":
        gate = read_audit_gate()
        if gate and gate.get("status") == "approved":
            print(f"  → 审计已通过（崩溃前），清除门禁，继续下一个 Story")
            clear_audit_gate()
        elif gate and gate.get("status") == "rejected":
            print(f"  → 审计被驳回（崩溃前），将在主循环中处理")
        else:
            print(f"  → 审计等待中断，将在主循环中恢复等待 {old_story}")
    else:
        print(f"  → 未知阶段 ({old_phase})，将从迭代 {old_iteration} 重新开始")

    clear_lock()
    return old_iteration


# ─────────────────────────────────────────────
# P0: 成本追踪
# ─────────────────────────────────────────────
def log_cost(story_id: str | None, phase: str, duration_seconds: float,
             iteration: int) -> None:
    """
    记录每次 agent 调用的耗时到 cost-log.jsonl。
    注：Claude CLI --print 不输出 token 统计，此处记录可观测的维度（耗时、story、phase）。
    未来可通过捕获 stderr 或 API 日志补充 token 数据。
    """
    entry = {
        "timestamp": datetime.now().isoformat(),
        "iteration": iteration,
        "story_id": story_id,
        "phase": phase,
        "duration_seconds": round(duration_seconds, 1),
    }
    try:
        with open(COST_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"⚠️  成本日志写入失败: {e}")


def print_cost_summary() -> None:
    """打印成本摘要"""
    if not COST_LOG_FILE.exists():
        return

    try:
        entries = []
        for line in COST_LOG_FILE.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                entries.append(json.loads(line))

        if not entries:
            return

        total_dev = sum(e["duration_seconds"] for e in entries if e["phase"] == "developing")
        total_val = sum(e["duration_seconds"] for e in entries if e["phase"] == "validating")
        total = total_dev + total_val
        dev_count = sum(1 for e in entries if e["phase"] == "developing")
        val_count = sum(1 for e in entries if e["phase"] == "validating")

        print(f"\n{'─'*48}")
        print(f"  📊 成本追踪摘要")
        print(f"{'─'*48}")
        print(f"  开发 Agent 调用: {dev_count} 次, 总耗时: {format_duration(total_dev)}")
        print(f"  验证 Agent 调用: {val_count} 次, 总耗时: {format_duration(total_val)}")
        print(f"  总计: {dev_count + val_count} 次调用, 总耗时: {format_duration(total)}")

        # 按 story 统计
        story_times: dict[str, float] = {}
        for e in entries:
            sid = e.get("story_id", "unknown")
            story_times[sid] = story_times.get(sid, 0) + e["duration_seconds"]

        if story_times:
            print(f"\n  按 Story 统计:")
            for sid, t in sorted(story_times.items()):
                print(f"    {sid}: {format_duration(t)}")
        print(f"{'─'*48}")

    except Exception as e:
        print(f"⚠️  成本摘要生成失败: {e}")


# ─────────────────────────────────────────────
# P1: 级联失败处理
# ─────────────────────────────────────────────
def cascade_block_stories() -> None:
    """
    级联阻断：检查所有 pending story，如果其依赖已被 blocked 或不存在，将其也标记为 blocked。
    仅在依赖被永久 blocked 时触发阻断；依赖"未完成"不触发（等待依赖完成后自然满足）。
    在每次迭代开始时调用，确保 blocked 状态逐层传播。
    """
    prd = read_prd()
    if not prd:
        return

    modified = False
    for story in prd.get("userStories", []):
        if story.get("passes", False) or story.get("blocked", False):
            continue

        for dep_id in story.get("depends_on", []):
            dep_story = get_story_by_id(prd, dep_id)
            if not dep_story or dep_story.get("blocked", False):
                story["blocked"] = True
                dep_reason = "不存在" if not dep_story else "已 blocked"
                existing_notes = story.get("notes", "").strip()
                new_note = f"[级联阻断] 依赖 {dep_id} {dep_reason}"
                story["notes"] = f"{existing_notes}\n{new_note}".strip() if existing_notes else new_note
                modified = True
                print(f"  ⛔ {story.get('id')} 级联阻断: 依赖 {dep_id} {dep_reason}")
                break

    if modified:
        try:
            PRD_FILE.write_text(json.dumps(prd, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"⚠️  级联阻断更新 prd.json 失败: {e}")


# ─────────────────────────────────────────────
# P0: Audit Gate - 审计门禁
# ─────────────────────────────────────────────
def write_audit_gate(story_id: str) -> bool:
    """写入审计门禁文件，状态为 pending，等待 Opus 审查。返回是否写入成功。"""
    gate = {
        "story_id": story_id,
        "status": "pending",
        "timestamp": datetime.now().isoformat(),
    }
    try:
        AUDIT_GATE_FILE.write_text(
            json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"⚠️  写入审计门禁失败: {e}（跳过审计等待，直接继续）")
        return False

    print(f"\n{'─'*48}")
    print(f"  🔒 审计门禁已激活: {story_id}")
    print(f"{'─'*48}")
    print(f"  等待 Opus 质量审查（4 维度）...")
    print(f"  Ralph 将每 {AUDIT_POLL_INTERVAL} 秒轮询一次，直到审计完成")
    print(f"")
    print(f"  审查通过后运行:")
    print(f"    python scripts/ralph/ralph-tools.py approve")
    print(f"  驳回（需重做）:")
    print(f"    python scripts/ralph/ralph-tools.py reject \"反馈内容\"")
    print(f"  查看状态:")
    print(f"    python scripts/ralph/ralph-tools.py audit-status")
    print(f"{'─'*48}")
    return True


def read_audit_gate() -> dict | None:
    """读取审计门禁文件"""
    try:
        if AUDIT_GATE_FILE.exists():
            return json.loads(AUDIT_GATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def clear_audit_gate() -> None:
    """清除审计门禁文件"""
    try:
        if AUDIT_GATE_FILE.exists():
            AUDIT_GATE_FILE.unlink()
    except Exception:
        pass


def wait_for_audit(story_id: str) -> str:
    """
    轮询 audit-gate.json，等待 Opus 写入 approved 或 rejected。
    返回 "approved" 或 "rejected"。
    """
    poll_count = 0
    while True:
        gate = read_audit_gate()
        if gate and gate.get("story_id") == story_id:
            status = gate.get("status", "pending")
            if status == "approved":
                return "approved"
            elif status == "rejected":
                return "rejected"

        poll_count += 1
        if poll_count % 10 == 0:  # 每 5 分钟提醒一次
            elapsed_min = (poll_count * AUDIT_POLL_INTERVAL) // 60
            print(f"  ⏳ 已等待 {elapsed_min} 分钟，仍在等待 Opus 审计 {story_id}...")

        time.sleep(AUDIT_POLL_INTERVAL)


def handle_audit_result(story_id: str) -> None:
    """处理审计结果：approved 继续，rejected 重置 story 状态"""
    gate = read_audit_gate()
    if not gate:
        return

    # 安全检查：确保 gate 中的 story_id 与预期一致
    gate_story = gate.get("story_id")
    if gate_story and gate_story != story_id:
        print(f"  ⚠️  审计门禁 story_id 不匹配: 预期 {story_id}, 实际 {gate_story}，清除过期门禁")
        clear_audit_gate()
        return

    status = gate.get("status", "pending")

    if status == "approved":
        print(f"  ✅ {story_id} 通过 Opus 质量审查")
        clear_audit_gate()

    elif status == "rejected":
        feedback = gate.get("feedback", "无具体反馈")
        print(f"  ❌ {story_id} 被 Opus 审计驳回")
        print(f"     反馈: {feedback}")

        # 重置 passes，写入反馈到 notes
        prd = read_prd()
        if prd:
            s = get_story_by_id(prd, story_id)
            if s:
                s["passes"] = False
                s["retryCount"] = s.get("retryCount", 0) + 1
                existing_notes = s.get("notes", "").strip()
                new_note = f"[Opus 审计驳回] {feedback}"
                s["notes"] = f"{existing_notes}\n{new_note}".strip() if existing_notes else new_note
                try:
                    PRD_FILE.write_text(
                        json.dumps(prd, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    print(f"     已重置 {story_id} passes → false，将在下一轮重新开发")
                except Exception as e:
                    print(f"     ⚠️  重置 passes 失败: {e}")

        clear_audit_gate()


# ─────────────────────────────────────────────
# P0: Tiered Context Injection - 构建动态 Prompt
# ─────────────────────────────────────────────
def build_developer_prompt(story_id: str | None) -> str:
    """
    构建开发 Agent 的 prompt：
    基础指令 + 当前 Story 上下文 + Codebase Patterns
    """
    base = CLAUDE_INSTRUCTION_FILE.read_text(encoding="utf-8")

    if not story_id:
        return base

    prd = read_prd()
    if not prd:
        return base

    story = get_story_by_id(prd, story_id)
    if not story:
        return base

    # 注入当前 story 的完整信息
    context_parts = [base]
    context_parts.append(f"\n\n## 📋 当前任务 Story（由编排器注入，无需自行从 prd.json 查找）\n")
    context_parts.append(f"- **Story ID**: {story.get('id')}")
    context_parts.append(f"- **Title**: {story.get('title')}")
    context_parts.append(f"- **Description**: {story.get('description')}")
    context_parts.append(f"- **Priority**: {story.get('priority')}")
    context_parts.append(f"- **Retry Count**: {story.get('retryCount', 0)}")

    criteria = story.get("acceptanceCriteria", [])
    if criteria:
        context_parts.append(f"- **Acceptance Criteria**:")
        for i, c in enumerate(criteria, 1):
            context_parts.append(f"  {i}. {c}")

    notes = story.get("notes", "")
    if notes:
        context_parts.append(f"\n### ⚠️ 上次验证失败的反馈（优先阅读，针对性修复）：")
        context_parts.append(notes)

    # 注入 Codebase Patterns（如果 progress.txt 存在）
    if PROGRESS_FILE.exists():
        try:
            progress_text = PROGRESS_FILE.read_text(encoding="utf-8")
            # 提取 Codebase Patterns 段落
            if "## Codebase Patterns" in progress_text:
                pattern_start = progress_text.index("## Codebase Patterns")
                # 找下一个 ## 或文件结尾
                next_section = progress_text.find("\n## ", pattern_start + 1)
                if next_section == -1:
                    patterns = progress_text[pattern_start:]
                else:
                    patterns = progress_text[pattern_start:next_section]
                if patterns.strip():
                    context_parts.append(f"\n### 📖 Codebase Patterns（从历史迭代中学习到的模式）：")
                    context_parts.append(patterns.strip())
        except Exception:
            pass

    # 注入上游依赖 story 的 summary（如果有 depends_on）
    depends_on = story.get("depends_on", [])
    if depends_on:
        context_parts.append(f"\n### 🔗 上游依赖 Stories（已完成，供参考）：")
        for dep_id in depends_on:
            dep_story = get_story_by_id(prd, dep_id)
            if dep_story and dep_story.get("passes", False):
                context_parts.append(f"- **{dep_id}**: {dep_story.get('title')} — ✅ 已完成")

    return "\n".join(context_parts)


def build_validator_prompt(story_id: str | None) -> str:
    """
    构建 Validator 的 prompt：
    基础指令 + 显式注入 story ID 和 acceptance criteria
    """
    base = VALIDATOR_INSTRUCTION_FILE.read_text(encoding="utf-8")

    if not story_id:
        return base

    prd = read_prd()
    if not prd:
        return base

    story = get_story_by_id(prd, story_id)
    if not story:
        return base

    # 显式注入 story 信息，Validator 无需从 progress.txt 猜测
    context_parts = [base]
    context_parts.append(f"\n\n## 📋 本次验证目标（由编排器注入）\n")
    context_parts.append(f"- **Story ID**: {story.get('id')}")
    context_parts.append(f"- **Title**: {story.get('title')}")
    context_parts.append(f"- **当前 retryCount**: {story.get('retryCount', 0)}")
    context_parts.append(f"- **Acceptance Criteria**:")
    for i, c in enumerate(story.get("acceptanceCriteria", []), 1):
        context_parts.append(f"  {i}. {c}")
    context_parts.append(f"\n⚠️ 注意：请直接验证以上 Story，不需要再从 progress.txt 推断 story ID。")

    return "\n".join(context_parts)


# ─────────────────────────────────────────────
# Agent 执行
# ─────────────────────────────────────────────
def run_agent(prompt: str, label: str, timeout: int) -> tuple[bool, int | None, float]:
    """
    通用 Agent 执行函数。
    返回 (是否超时, 进程退出码或None, 实际耗时秒数)
    - 正常完成: (False, 0, duration)
    - 非零退出: (False, code, duration)
    - 超时终止: (True, None, duration)
    - 启动异常: (False, None, duration)
    """
    cmd = build_process_cmd(prompt)

    start_time = time.time()
    try:
        process = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT))

        while True:
            ret_code = process.poll()
            if ret_code is not None:
                elapsed = time.time() - start_time
                if ret_code != 0:
                    print(f"\n⚠️  {label}非零退出码: {ret_code} (耗时: {format_duration(elapsed)})")
                else:
                    print(f"\n✓ {label}完成 (耗时: {format_duration(elapsed)})")
                return False, ret_code, elapsed

            elapsed = time.time() - start_time
            if elapsed > timeout:
                print(f"\n⚠️  {label}超时! 已运行 {int(elapsed)} 秒")
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                print(f"   进程已终止")
                return True, None, elapsed

            time.sleep(60)

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n❌ {label}错误: {e}")
        return False, None, elapsed


def run_developer(iteration: int, story_id: str | None) -> bool:
    """调用开发 Agent，返回是否超时"""
    print(f"\n{'='*64}\n  迭代 {iteration}/{MAX_ITERATIONS} | Story: {story_id or 'N/A'}\n{'='*64}")

    if not CLAUDE_INSTRUCTION_FILE.exists():
        print(f"❌ 错误: {CLAUDE_INSTRUCTION_FILE} 不存在")
        return False

    prompt = build_developer_prompt(story_id)
    timed_out, _exit_code, duration = run_agent(prompt, "开发迭代", TIMEOUT_SECONDS)
    log_cost(story_id, "developing", duration, iteration)
    return timed_out


def run_validator(iteration: int, story_id: str | None) -> None:
    """调用 Validator Agent"""
    print(f"\n{'='*64}\n  验证迭代 {iteration} | Story: {story_id or 'N/A'}\n{'='*64}")

    if not VALIDATOR_INSTRUCTION_FILE.exists():
        print(f"⚠️  警告: {VALIDATOR_INSTRUCTION_FILE} 不存在，跳过验证")
        return

    prompt = build_validator_prompt(story_id)
    timed_out, exit_code, duration = run_agent(prompt, "验证", VALIDATOR_TIMEOUT_SECONDS)
    log_cost(story_id, "validating", duration, iteration)

    # 安全措施：Validator 未正常完成时（超时 / 非零退出 / 启动异常），不能信任 passes 状态
    validator_failed = timed_out or exit_code is None or exit_code != 0
    if validator_failed:
        if timed_out:
            reason = "超时"
        elif exit_code is None:
            reason = "启动失败"
        else:
            reason = f"异常退出(code={exit_code})"
        print(f"   Validator {reason}，检查 passes 状态")
        prd = read_prd()
        if prd:
            s = get_story_by_id(prd, story_id) if story_id else None
            if s and s.get("passes", False):
                s["passes"] = False
                s["notes"] = (s.get("notes", "") + f"\n[Validator {reason}] 验证未完成，passes 已重置为 false").strip()
                try:
                    PRD_FILE.write_text(json.dumps(prd, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(f"   已重置 {story_id} passes → false（验证未完成，不可信任）")
                except Exception as e:
                    print(f"   ⚠️  重置 passes 失败: {e}")


# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────
def format_duration(seconds: float) -> str:
    """将秒数格式化为易读的时间字符串"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}小时 {m}分钟 {s}秒"
    elif m > 0:
        return f"{m}分钟 {s}秒"
    else:
        return f"{s}秒"


# ─────────────────────────────────────────────
# 主循环
# ─────────────────────────────────────────────
def main():
    """主函数"""
    print(f"启动 Ralph v2 - 最大迭代次数: {MAX_ITERATIONS}")
    audit_label = "启用" if not NO_AUDIT_GATE else "禁用(--no-audit-gate)"
    print(f"  Agent: {AGENT} | 开发超时: {TIMEOUT_SECONDS//60}min | 验证超时: {VALIDATOR_TIMEOUT_SECONDS//60}min | 审计门禁: {audit_label}")

    # 崩溃恢复检查
    start_iteration = check_crash_recovery()

    # 注册退出时清理 lock file
    atexit.register(clear_lock)

    total_start_time = time.time()
    dashboard.start(max_iterations=MAX_ITERATIONS)

    for i in range(start_iteration, MAX_ITERATIONS + 1):
        try:
            # P0: 审计门禁恢复检查（崩溃后重启时，若有未完成的审计则继续等待）
            if not NO_AUDIT_GATE:
                gate = read_audit_gate()
                if gate and gate.get("status") == "pending":
                    pending_story = gate.get("story_id", "?")
                    # 检查该 story 是否已被外部标记为 blocked/完成 → 过期门禁，直接清除
                    _prd = read_prd()
                    _gs = get_story_by_id(_prd, pending_story) if _prd else None
                    if _gs and _gs.get("blocked", False):
                        print(f"  ⚠️  审计门禁 {pending_story} 对应 story 已 blocked，清除过期门禁")
                        clear_audit_gate()
                    else:
                        print(f"\n  🔒 检测到未完成的审计门禁: {pending_story}，恢复等待...")
                        write_lock(i, "waiting_audit", pending_story)
                        dashboard.set_state(phase="waiting_audit")
                        wait_for_audit(pending_story)
                        handle_audit_result(pending_story)
                elif gate and gate.get("status") in ("approved", "rejected"):
                    pending_story = gate.get("story_id", "?")
                    handle_audit_result(pending_story)

            # P0: 备份 prd.json
            backup_prd(i)

            # P1: 级联阻断传播（依赖已 blocked 的 story 自动 blocked）
            cascade_block_stories()

            # 获取当前 story（已检查依赖是否满足）
            current_story = get_current_story_id()

            if current_story is None:
                # 没有待执行的 story 了
                if all_stories_resolved():
                    dashboard.set_state(phase="done")
                    elapsed = time.time() - total_start_time
                    print("✅ 所有任务已完成或已标记为 BLOCKED!")
                    print(f"⏱️  总运行时间: {format_duration(elapsed)}")
                    print_cost_summary()
                    clear_lock()
                    sys.exit(0)
                else:
                    print("⚠️  未找到可执行的 story，但仍有未完成的 story，请检查 prd.json")
                    break

            # ─── 第一步：开发 ───
            write_lock(i, "developing", current_story)
            dashboard.set_state(iteration=i, phase="developing", current_story=current_story)
            timed_out = run_developer(i, current_story)

            if timed_out:
                # 安全措施：Developer 超时时可能已设 passes=true（执行到一半），必须重置
                prd = read_prd()
                if prd and current_story:
                    s = get_story_by_id(prd, current_story)
                    if s and s.get("passes", False):
                        s["passes"] = False
                        s["notes"] = (s.get("notes", "") + "\n[Developer 超时] 开发未完成，passes 已重置为 false").strip()
                        try:
                            PRD_FILE.write_text(json.dumps(prd, ensure_ascii=False, indent=2), encoding="utf-8")
                            print(f"   已重置 {current_story} passes → false（开发超时，不可信任）")
                        except Exception as e:
                            print(f"   ⚠️  重置 passes 失败: {e}")
                dashboard.set_state(phase="idle")
                print("⏭️  开发 Agent 超时，跳过验证，下一次迭代继续...")
                time.sleep(2)
                continue

            # ─── 第二步：验证 ───
            write_lock(i, "validating", current_story)
            dashboard.set_state(phase="validating")
            run_validator(i, current_story)

            # ─── 第三步：审计门禁 ───
            if not NO_AUDIT_GATE:
                prd = read_prd()
                if prd and current_story:
                    s = get_story_by_id(prd, current_story)
                    if s and s.get("passes", False):
                        # Story 通过验证 → 激活审计门禁，等待 Opus 审查
                        gate_written = write_audit_gate(current_story)
                        if gate_written:
                            write_lock(i, "waiting_audit", current_story)
                            dashboard.set_state(phase="waiting_audit")
                            wait_for_audit(current_story)
                            handle_audit_result(current_story)

            # ─── 第四步：检查完成状态 ───
            dashboard.set_state(phase="idle")
            if all_stories_resolved():
                dashboard.set_state(phase="done")
                elapsed = time.time() - total_start_time
                print("✅ 所有任务已完成或已标记为 BLOCKED!")
                print(f"⏱️  总运行时间: {format_duration(elapsed)}")
                print_cost_summary()
                clear_lock()
                sys.exit(0)

        except KeyboardInterrupt:
            elapsed = time.time() - total_start_time
            print(f"\n\n⚠️  用户中断")
            print(f"⏱️  总运行时间: {format_duration(elapsed)}")
            print_cost_summary()
            clear_lock()
            sys.exit(130)

    elapsed = time.time() - total_start_time
    print(f"\n已达到最大迭代次数 ({MAX_ITERATIONS})")
    print(f"⏱️  总运行时间: {format_duration(elapsed)}")
    print_cost_summary()
    clear_lock()
    sys.exit(1)


if __name__ == "__main__":
    main()
