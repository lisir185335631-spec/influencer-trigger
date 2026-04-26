# Security & Access Control Model

> 当前状态：2026-04-26
> 关联讨论：post-`722d193` review 的 B-1（多租户隔离）讨论结论

## 1. 一句话定位

**本项目是单团队（PremLogin BD 等）内部协作工具，不是多租户 SaaS。**
所有核心资源（网红、模板、活动、邮件）是**团队共享池**，登录后的成员都能看见、协作、互相接力。`created_by` 字段在多张表上仅作**审计**用（"谁创建的"），不作**访问控制**用。

## 2. 资源所有权语义对照表

| 资源 | `created_by` 是否在 | 读 | 改/删 | 备注 |
|---|---|---|---|---|
| Influencer | ❌ 没有 | 全员 | 全员 PATCH / **manager+** 批量+硬删+导出 | 单条 PATCH 共享；批量操作 / 硬删除 / 导出 = manager+（R-1, R-3, W-1）|
| Template | ✅ 有（仅审计）| 全员 | 全员 改 / **manager+** 删 | 删模板可能影响他人 in-flight campaign（W-3）|
| Campaign | ✅ 有（**含访问控制**）| 创建者 + admin | 创建者 + admin | 创建者 + admin | LLM 生成内容个性化到收件人，跨人查看 confusing |
| EmailDraft | 通过 Campaign 间接拥有 | 同 Campaign | 同 Campaign | 同 Campaign | 跟 Campaign 一致 |
| ScrapeTask | ✅ 有（仅审计） | 全员 | 全员 | 全员 | 历史抓取记录可见 |
| Note / Collaboration | ✅ 有（仅审计）| 全员 | 全员 | 全员 | CRM 协作内容 |
| Tag | n/a | 全员 | 全员 改 / **manager+** 删 | 删 tag 影响所有用过它的网红（W-2）|
| Mailbox（SMTP 池）| n/a | 全员 | 全员 改 / **manager+** 删 | SMTP 凭据 admin 配置，operator 不该删（W-4）|
| Holiday / FollowUpSettings | n/a | 全员 | manager+ | manager+ | 系统级配置 |

**只有 Campaign / Draft 做了创建者+admin 的访问控制**——这是 phase 1 草稿功能新加的，原因是个性化内容跟收件人一对一绑定，跨人查看 confusing。其他资源遵循组织共享原则。

## 3. 角色分级（已实施）

| 角色 | 能做什么 |
|---|---|
| `admin` | 全部资源 + 系统设置 + 审计日志 + 所有运维诊断 |
| `manager` | 全部资源 + 部分系统设置（节日/跟进规则）+ Mailbox 增删 |
| `operator` | 只读 + 自己创建的 Campaign 的草稿编辑 |

具体限制由各 endpoint 的 `Depends(...)` 决定，不在这里穷举。

## 4. 我们刻意 *不* 做的隔离

### 4.1 Influencer 池跨人共享
理由：BD 团队场景下"我抓的网红同事可以接着发"是典型协作模式，强行 user-scope 反而会让团队拆碎。Influencer 表**没有 created_by 列**就是这个设计意图的物理体现。

### 4.2 Template 库跨人共享
公司有自己的话术库，员工 A 写好的模板员工 B 应该能复用。

### 4.3 Note / Collaboration 跨人共享
CRM 场景下接力跟进是核心能力，跨人不可见反而割裂。

## 5. Review 中提出的 B-1 处置

[Post-`722d193` SendPanel review](#) 提出 Blocker B-1：
> `/api/influencers` 不按 user_id 过滤，任何登录用户能给别人抓到的网红群发邮件。

按本文档原则：**B-1 关闭为 "by design"**。
- "给团队成员抓到的网红群发"不是攻击向量，是 BD 协作功能。
- 全部对内成员经过 `get_current_user` 鉴权（必须登录），非成员看不到任何数据。
- 操作历史可追溯：每封发出的邮件 Campaign 上有 `created_by`，每封 Email 上有 `mailbox_id`，能定位"谁用哪个邮箱发了什么给谁"。

## 6. 数据外泄相关的真风险点（独立于 B-1）

下面这些**不是**多租户隔离问题，但**仍然值得加固**——是单团队场景下的"防误操作 / 防数据外泄"。**未实施，待后续讨论**：

### R-1. `POST /api/influencers/export` ✅ 已限 manager+
**已实施**（2026-04-26）：endpoint 改用 `Depends(require_manager_or_above)`。
**遗留**：admin 操作 audit log 未加，未来需做时参考 `audit_log` 表 schema。

### R-2. `PATCH /api/influencers/{id}` 任何 user 可改任何网红资料
**当前**：同上，仅认证。
**风险**：低（误操作多于恶意），但 CRM 场景下"乱改别人的网红状态/优先级"也烦。
**建议**：保持组织共享但加审计——每次修改写 audit_log（谁改了哪行什么字段），管理员事后追溯。

### R-3. `DELETE /api/influencers/{id}` ✅ 已限 manager+
**已实施**（2026-04-26）：endpoint 改用 `Depends(require_manager_or_above)`。
**遗留**：仍是硬删除；如未来要做"软删除"改用 `status=archived` 列。Operator 想清掉自己抓的网红仍可走 PATCH 改 status=archived（R-2 涉及）。

### R-4. WebSocket 端点完全无认证
**当前**：`/ws` 接受任意 client 连接，broadcast 全员推送。
**风险**：外人能连 ws 接收事件流（虽然 payload 已经去 PII，但元数据如 campaign_id / 进度仍可见）。
**建议**：连接时校验 query 里的 token，failed 即关闭。本身是独立工作（影响所有现有 WS 用户），单独立项。

## 7. 未来扩展为多租户 SaaS 时需要做的事（指引）

如果未来这套系统要切到"多公司各自隔离"模式（不在当前规划内），需要的改造路径：

1. **加 Org/Team 模型**：`Team`, `TeamMembership`, User 关联到 Team
2. **核心资源加 `team_id` 列**：Influencer / Template / Mailbox / Campaign / ScrapeTask 等
3. **写入路径填 team_id**：scraper / import / template create / mailbox create
4. **读写 endpoint 全部按 team_id 过滤**（admin 可跨团队，需要新建 super-admin 角色）
5. **WebSocket 加 team-scoped broadcast**（manager.broadcast 改为 broadcast_to_team）
6. **审计 log 加 team_id 维度**

工作量估算：约 1-2 周（含数据迁移 + 全 endpoint 改 + 测试）。

## 8. 决策记录

- **2026-04-26**：B-1 review 后讨论确认走"单团队组织共享"模型，B-1 关闭为 by design。文档化避免未来 reviewer 重提。
