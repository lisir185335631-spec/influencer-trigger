#!/usr/bin/env python3
"""
Ralph Tools - 确定性工具脚本（Coding 3.0）

提供 prd.json 的机械化操作，替代 LLM 解析，节省 token、避免解析错误。

用法:
  python ralph-tools.py next-story          # 返回下一个待执行 story ID
  python ralph-tools.py status              # 打印所有 story 状态摘要
  python ralph-tools.py story US-001        # 打印指定 story 的详细信息
  python ralph-tools.py block US-001 "原因" # 标记指定 story 为 blocked
  python ralph-tools.py reset US-001        # 重置指定 story 的 passes/retryCount
  python ralph-tools.py deps                # 显示依赖关系图
  python ralph-tools.py waves               # 分析 Wave 执行计划（拓扑排序 + 并行度分析）
  python ralph-tools.py validate            # 执行结构化验证（Plan Checker 的 CLI 版本）
  python ralph-tools.py approve             # 审计门禁：通过当前 story 的质量审查
  python ralph-tools.py reject "反馈内容"   # 审计门禁：驳回当前 story（附反馈）
  python ralph-tools.py audit-status        # 审计门禁：查看当前门禁状态
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# Windows 控制台默认 GBK 编码，无法输出 emoji → 强制 UTF-8
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SCRIPT_DIR = Path(__file__).parent.resolve()
PRD_FILE = SCRIPT_DIR / "prd.json"
AUDIT_GATE_FILE = SCRIPT_DIR / "audit-gate.json"


def read_prd() -> dict:
    if not PRD_FILE.exists():
        print(f"❌ prd.json 不存在: {PRD_FILE}", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(PRD_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"❌ prd.json 格式错误: {e}", file=sys.stderr)
        sys.exit(1)


def write_prd(prd: dict) -> None:
    PRD_FILE.write_text(
        json.dumps(prd, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def get_story(prd: dict, story_id: str) -> dict | None:
    for s in prd.get("userStories", []):
        if s.get("id") == story_id:
            return s
    return None


# ─── 子命令 ───────────────────────────────────

def cmd_next_story():
    """返回下一个待执行 story ID（exits 0 + stdout），或 exits 1 如果没有"""
    prd = read_prd()
    for story in prd.get("userStories", []):
        if not story.get("passes", False) and not story.get("blocked", False):
            # 检查依赖
            depends_on = story.get("depends_on", [])
            deps_met = True
            for dep_id in depends_on:
                dep = get_story(prd, dep_id)
                if not dep or not dep.get("passes", False):
                    deps_met = False
                    break
            if deps_met:
                print(story["id"])
                return
    print("(none)", file=sys.stderr)
    sys.exit(1)


def cmd_status():
    """打印所有 story 状态"""
    prd = read_prd()
    stories = prd.get("userStories", [])

    print(f"Project: {prd.get('project', 'N/A')}")
    print(f"Branch:  {prd.get('branchName', 'N/A')}")
    print(f"Stories: {len(stories)}")
    print()

    passed = blocked = pending = 0
    for s in stories:
        sid = s.get("id", "?")
        title = s.get("title", "?")[:50]
        retries = s.get("retryCount", 0)

        if s.get("blocked", False):
            icon = "⛔"
            status = "BLOCKED"
            blocked += 1
        elif s.get("passes", False):
            icon = "✅"
            status = "PASSED"
            passed += 1
        else:
            icon = "⏳"
            status = f"PENDING (retries: {retries})"
            pending += 1

        deps = s.get("depends_on", [])
        dep_str = f" [depends: {','.join(deps)}]" if deps else ""
        print(f"  {icon} {sid} | {status} | {title}{dep_str}")

    print(f"\n  Summary: ✅ {passed} passed, ⏳ {pending} pending, ⛔ {blocked} blocked")

    if pending == 0 and blocked == 0:
        print("  🎉 All stories resolved!")
    elif pending == 0 and blocked > 0:
        print(f"  ⚠️  All remaining stories are blocked ({blocked})")


def cmd_story(story_id: str):
    """打印指定 story 详情"""
    prd = read_prd()
    story = get_story(prd, story_id)
    if not story:
        print(f"❌ Story {story_id} 不存在", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(story, ensure_ascii=False, indent=2))


def cmd_block(story_id: str, reason: str):
    """标记 story 为 blocked"""
    prd = read_prd()
    story = get_story(prd, story_id)
    if not story:
        print(f"❌ Story {story_id} 不存在", file=sys.stderr)
        sys.exit(1)

    story["blocked"] = True
    existing_notes = story.get("notes", "").strip()
    new_note = f"[手动标记 BLOCKED] {reason}"
    story["notes"] = f"{existing_notes}\n{new_note}".strip() if existing_notes else new_note
    write_prd(prd)
    print(f"✅ {story_id} 已标记为 blocked: {reason}")


def cmd_reset(story_id: str):
    """重置 story 的 passes/retryCount/blocked/notes"""
    prd = read_prd()
    story = get_story(prd, story_id)
    if not story:
        print(f"❌ Story {story_id} 不存在", file=sys.stderr)
        sys.exit(1)

    story["passes"] = False
    story["retryCount"] = 0
    story["blocked"] = False
    story["notes"] = ""
    write_prd(prd)
    print(f"✅ {story_id} 已重置为初始状态")


def cmd_deps():
    """显示依赖关系图"""
    prd = read_prd()
    stories = prd.get("userStories", [])

    has_deps = False
    for s in stories:
        deps = s.get("depends_on", [])
        if deps:
            has_deps = True
            sid = s.get("id", "?")
            dep_str = ", ".join(deps)
            status = "✅" if s.get("passes") else ("⛔" if s.get("blocked") else "⏳")
            print(f"  {status} {sid} ← depends on [{dep_str}]")

    if not has_deps:
        print("  (无依赖关系，所有 story 独立)")

    # 检查循环依赖
    dep_map = {}
    for s in stories:
        dep_map[s.get("id", "")] = s.get("depends_on", [])

    def has_cycle(node, visited, path):
        if node in path:
            return True
        if node in visited:
            return False
        visited.add(node)
        path.add(node)
        for dep in dep_map.get(node, []):
            if has_cycle(dep, visited, path):
                return True
        path.remove(node)
        return False

    visited = set()
    for sid in dep_map:
        if has_cycle(sid, visited, set()):
            print(f"\n  ❌ 检测到循环依赖! 涉及 {sid}")
            return

    print("\n  ✅ 无循环依赖")


def cmd_waves():
    """分析并显示 Wave 执行计划（基于 depends_on 的拓扑排序）"""
    prd = read_prd()
    stories = prd.get("userStories", [])

    if not stories:
        print("  (无 stories)")
        return

    # 构建依赖图 + 查找表（避免 O(n²) 线性扫描）
    all_ids = {s["id"] for s in stories}
    story_map = {s["id"]: s for s in stories}
    priority_map = {s["id"]: s.get("priority", 999) for s in stories}
    dep_map = {}
    for s in stories:
        sid = s["id"]
        deps = [d for d in s.get("depends_on", []) if d in all_ids]
        dep_map[sid] = deps

    # Kahn 拓扑排序 → 分 wave
    in_degree = {sid: 0 for sid in all_ids}
    reverse_deps: dict[str, list[str]] = {sid: [] for sid in all_ids}
    for sid, deps in dep_map.items():
        in_degree[sid] = len(deps)
        for dep in deps:
            reverse_deps[dep].append(sid)

    waves: list[list[str]] = []
    ready = [sid for sid, deg in in_degree.items() if deg == 0]
    ready.sort(key=lambda sid: priority_map.get(sid, 999))

    while ready:
        waves.append(sorted(ready, key=lambda sid: priority_map.get(sid, 999)))
        next_ready = []
        for sid in ready:
            for dependent in reverse_deps[sid]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    next_ready.append(dependent)
        ready = next_ready

    # 检查是否有 story 没被排入（循环依赖）
    assigned = set()
    for w in waves:
        assigned.update(w)
    unassigned = all_ids - assigned
    if unassigned:
        print(f"  ❌ 以下 story 有循环依赖，无法排入 wave: {', '.join(unassigned)}")

    # 输出 wave 计划
    print(f"  Wave 执行计划 ({len(waves)} waves, {len(stories)} stories)")
    print()

    for i, wave in enumerate(waves, 1):
        status_counts = {"pass": 0, "blocked": 0, "pending": 0}
        for sid in wave:
            s = story_map.get(sid)
            if s and s.get("blocked"):
                status_counts["blocked"] += 1
            elif s and s.get("passes"):
                status_counts["pass"] += 1
            else:
                status_counts["pending"] += 1

        parallel_label = "可并行" if len(wave) > 1 else "串行"
        print(f"  Wave {i} ({parallel_label}, {len(wave)} stories):")
        for sid in wave:
            s = story_map.get(sid)
            title = s.get("title", "?")[:45] if s else "?"
            icon = "✅" if s and s.get("passes") else ("⛔" if s and s.get("blocked") else "⏳")
            deps = s.get("depends_on", []) if s else []
            dep_str = f" ← [{','.join(deps)}]" if deps else ""
            print(f"    {icon} {sid}: {title}{dep_str}")
        print()

    # 统计
    parallelizable = sum(1 for w in waves if len(w) > 1)
    max_parallel = max(len(w) for w in waves) if waves else 0
    serial_time = len(stories)
    parallel_time = len(waves)
    speedup = serial_time / parallel_time if parallel_time > 0 else 1

    print(f"  📊 统计:")
    print(f"    - 可并行的 wave 数: {parallelizable}/{len(waves)}")
    print(f"    - 最大并行度: {max_parallel}")
    print(f"    - 理论加速比: {speedup:.1f}x (串行 {serial_time} 步 → 并行 {parallel_time} 步)")


def cmd_approve():
    """审计门禁：通过当前 story 的质量审查，Ralph 将继续执行"""
    if not AUDIT_GATE_FILE.exists():
        print("❌ 没有待审核的审计门禁", file=sys.stderr)
        sys.exit(1)

    try:
        gate = json.loads(AUDIT_GATE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ 读取审计门禁失败: {e}", file=sys.stderr)
        sys.exit(1)

    if gate.get("status") != "pending":
        print(f"⚠️  审计门禁状态为 {gate.get('status')}，非 pending", file=sys.stderr)
        sys.exit(1)

    gate["status"] = "approved"
    gate["approved_at"] = datetime.now().isoformat()
    AUDIT_GATE_FILE.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"✅ {gate['story_id']} 审计已通过，Ralph 将继续执行下一个 Story")


def cmd_reject(feedback: str):
    """审计门禁：驳回当前 story，Ralph 将重新开发"""
    if not AUDIT_GATE_FILE.exists():
        print("❌ 没有待审核的审计门禁", file=sys.stderr)
        sys.exit(1)

    try:
        gate = json.loads(AUDIT_GATE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ 读取审计门禁失败: {e}", file=sys.stderr)
        sys.exit(1)

    if gate.get("status") != "pending":
        print(f"⚠️  审计门禁状态为 {gate.get('status')}，非 pending", file=sys.stderr)
        sys.exit(1)

    gate["status"] = "rejected"
    gate["feedback"] = feedback
    gate["rejected_at"] = datetime.now().isoformat()
    AUDIT_GATE_FILE.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"❌ {gate['story_id']} 审计已驳回，Ralph 将根据反馈重新开发")
    print(f"   反馈: {feedback}")


def cmd_audit_status():
    """审计门禁：查看当前门禁状态"""
    if not AUDIT_GATE_FILE.exists():
        print("  没有活跃的审计门禁")
        return

    try:
        gate = json.loads(AUDIT_GATE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ 读取审计门禁失败: {e}", file=sys.stderr)
        sys.exit(1)

    status = gate.get("status", "?")
    icon = {"pending": "🔒", "approved": "✅", "rejected": "❌"}.get(status, "❓")

    print(f"  {icon} 审计门禁状态")
    print(f"  Story:     {gate.get('story_id', '?')}")
    print(f"  Status:    {status}")
    print(f"  Timestamp: {gate.get('timestamp', '?')}")
    if gate.get("feedback"):
        print(f"  Feedback:  {gate['feedback']}")
    if gate.get("approved_at"):
        print(f"  Approved:  {gate['approved_at']}")
    if gate.get("rejected_at"):
        print(f"  Rejected:  {gate['rejected_at']}")


def cmd_validate():
    """结构化验证 prd.json（Plan Checker 的 CLI 版本）"""
    prd = read_prd()
    errors = []
    warnings = []

    # 顶层字段
    if not prd.get("project"):
        errors.append("缺少 project 字段")
    if not prd.get("branchName"):
        errors.append("缺少 branchName 字段")
    elif not prd["branchName"].startswith("ralph/"):
        errors.append(f"branchName 必须以 ralph/ 开头，当前: {prd['branchName']}")

    stories = prd.get("userStories", [])
    if not stories:
        errors.append("userStories 为空")

    required_fields = ["id", "title", "description", "acceptanceCriteria",
                       "priority", "passes", "notes", "retryCount", "blocked", "depends_on"]

    all_ids = [st.get("id") for st in stories]
    prev_priority = 0
    for s in stories:
        sid = s.get("id", "?")

        # 必填字段
        for field in required_fields:
            if field not in s:
                errors.append(f"{sid}: 缺少字段 {field}")

        # ID 格式
        if not str(s.get("id", "")).startswith("US-"):
            errors.append(f"{sid}: ID 格式应为 US-NNN")

        # 初始值
        if s.get("passes") is not False:
            errors.append(f"{sid}: passes 初始值应为 false")
        if s.get("retryCount", 0) != 0:
            errors.append(f"{sid}: retryCount 初始值应为 0")
        if s.get("blocked") is not False:
            errors.append(f"{sid}: blocked 初始值应为 false")
        if s.get("notes", "") != "":
            warnings.append(f"{sid}: notes 初始值应为空字符串")

        # Priority 递增
        p = s.get("priority", 0)
        if p != prev_priority + 1:
            warnings.append(f"{sid}: priority={p}，期望 {prev_priority + 1}（不连续）")
        prev_priority = p

        # Acceptance criteria
        criteria = s.get("acceptanceCriteria", [])
        if len(criteria) < 2:
            warnings.append(f"{sid}: 仅有 {len(criteria)} 条 criteria，建议至少 2 条")
        if len(criteria) > 8:
            warnings.append(f"{sid}: 有 {len(criteria)} 条 criteria，story 可能太大")

        has_typecheck = any("typecheck" in str(c).lower() for c in criteria)
        if not has_typecheck:
            errors.append(f"{sid}: 缺少 'Typecheck passes' criteria")

        # 模糊表述检测（英文 + 中文）
        vague = ["works correctly", "good ux", "handle edge cases",
                 "works as expected", "properly implemented",
                 "正常工作", "工作正常", "良好体验", "良好的ux", "处理边缘情况",
                 "按预期工作", "正确实现"]
        for c in criteria:
            c_lower = str(c).lower()
            for v in vague:
                if v in c_lower:
                    errors.append(f"{sid}: criteria 包含模糊表述 '{v}'")

        # 粒度检查
        title = s.get("title", "")
        if " and " in title.lower() or "和" in title or "以及" in title or "同时" in title:
            warnings.append(f"{sid}: 标题包含连接词，可能需要拆分: {title}")

        desc = s.get("description", "")
        if len(desc.split()) > 100:
            warnings.append(f"{sid}: description 超过 100 词，story 可能太大")

        # depends_on 验证
        deps = s.get("depends_on", [])
        for dep in deps:
            if dep not in all_ids:
                errors.append(f"{sid}: depends_on 引用了不存在的 {dep}")
            else:
                dep_story = next((st for st in stories if st.get("id") == dep), None)
                if dep_story and dep_story.get("priority", 0) >= p:
                    errors.append(f"{sid}: 依赖 {dep} 的 priority >= 自身，执行顺序错误")

    # 输出
    print(f"{'='*48}")
    print(f"  Plan Check Report")
    print(f"{'='*48}")

    if errors:
        print(f"\n  ❌ 错误 ({len(errors)}):")
        for e in errors:
            print(f"    - {e}")

    if warnings:
        print(f"\n  ⚠️  警告 ({len(warnings)}):")
        for w in warnings:
            print(f"    - {w}")

    if not errors and not warnings:
        print(f"\n  ✅ 全部通过!")

    print(f"\n  📊 统计: {len(stories)} stories, {len(errors)} errors, {len(warnings)} warnings")

    conclusion = "PASS" if not errors else "FAIL"
    if not errors and warnings:
        conclusion = "WARN"
    print(f"  🎯 结论: [{conclusion}]")
    print(f"{'='*48}")

    sys.exit(1 if errors else 0)


# ─── 入口 ─────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "next-story":
        cmd_next_story()
    elif cmd == "status":
        cmd_status()
    elif cmd == "story":
        if len(sys.argv) < 3:
            print("用法: ralph-tools.py story <story-id>", file=sys.stderr)
            sys.exit(1)
        cmd_story(sys.argv[2])
    elif cmd == "block":
        if len(sys.argv) < 4:
            print("用法: ralph-tools.py block <story-id> <reason>", file=sys.stderr)
            sys.exit(1)
        cmd_block(sys.argv[2], sys.argv[3])
    elif cmd == "reset":
        if len(sys.argv) < 3:
            print("用法: ralph-tools.py reset <story-id>", file=sys.stderr)
            sys.exit(1)
        cmd_reset(sys.argv[2])
    elif cmd == "deps":
        cmd_deps()
    elif cmd == "waves":
        cmd_waves()
    elif cmd == "validate":
        cmd_validate()
    elif cmd == "approve":
        cmd_approve()
    elif cmd == "reject":
        if len(sys.argv) < 3:
            print("用法: ralph-tools.py reject <feedback>", file=sys.stderr)
            sys.exit(1)
        cmd_reject(sys.argv[2])
    elif cmd == "audit-status":
        cmd_audit_status()
    else:
        print(f"❌ 未知命令: {cmd}", file=sys.stderr)
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
