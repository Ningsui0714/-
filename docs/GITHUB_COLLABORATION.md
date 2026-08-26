# LearnFlow 直接推送与双仓并行准则

> 适用对象：LearnFlow 维护者及进入本仓库工作的 Codex
>
> 权威关系：本文负责 GitHub 发布方式与参考仓库边界；根目录 `AGENTS.md` 负责 Codex 的完整工作约束。三类主 Agent、五核、工具和事件仍以架构注册表与架构文档为准。

## 1. 当前维护模式

LearnFlow 采用个人维护、完成即提交并直接推送的模式：

- 日常任务不要求 GitHub Issue、功能分支、Draft PR、Review 或审批。
- 当前检出的分支就是默认发布目标；不要仅为了流程另建分支。
- 当前分支为 `main` 时可以直接推送 `main`；当前分支为其他分支时直接推送该分支。
- 用户明确要求实现、修改、修复、增加、删除或更新仓库内容，即视为授权在验证后 commit 并 push 当前分支。
- 用户只要求分析、诊断、讲解、评审或状态报告时，不得自动修改文件或远程状态。
- PR 仅用于用户明确要求的评审、外部贡献或临时比较，不是完成任务的前置条件。

## 2. 每次任务的固定流程

### 开工

```bash
git status -sb
git remote -v
git branch --show-current
```

1. 完整阅读根目录 `AGENTS.md`；涉及 GitHub、推送或双仓参考时同时完整阅读本文。
2. 确认当前分支和远程，识别已有未提交改动。
3. 已有改动默认属于用户；不得覆盖、删除、重置或顺手格式化任务外文件。
4. 直接按用户任务推进，不为了补齐形式而创建 Issue、分支或 PR。

### 修改与验证

- 先理解现有实现和权威契约，再做最小完整修改。
- 新工具、产品技能、工作台、能力或重要事件必须同步更新架构注册表、测试和文档。
- 改动三类主 Agent、五核、`EvidenceEvent`、Action Board 或 `RemediationStrategy` 时，必须保持确定性策略和统一证据写入链。
- 按改动范围运行最小充分测试；不得用删除断言、跳过关键测试或弱化安全边界换取通过。
- UI、API、迁移、桌面权限或 seeded demo 的实质变化应在最终报告中给出复现或回滚信息。

### 提交与直接推送

```bash
git diff --check
git status -sb
git fetch origin
```

1. 检查完整 diff，并只暂存本任务文件；工作树混合时不得使用无差别暂存。
2. Commit 使用简洁的 Conventional Commit，例如 `feat:`、`fix:`、`docs:`、`refactor:`、`test:` 或 `chore:`。
3. 推送前检查当前分支相对远程跟踪分支是否落后。
4. 若远程领先，使用普通 merge 同步远程分支，解决冲突后重新测试。
5. 执行 `git push origin HEAD`。推送失败就报告原因，不使用强制参数绕过。
6. 最终报告必须说明 commit、目标分支、push 结果、已执行测试和未执行项。

## 3. 永久安全底线

- 禁止 force push、rebase、`git reset --hard` 和改写已发布历史。
- 禁止提交 `.env`、密钥、token、真实数据库、缓存、模型权重、虚拟环境、`node_modules`、构建输出或本地日志。
- 禁止删除或覆盖任务范围外的用户工作。
- 禁止未经明确请求合并其他分支、关闭历史 PR、删除远程分支、迁移真实数据或修改 GitHub 仓库设置。
- 删除文件、破坏兼容性或进行不可逆迁移前，必须验证精确范围和恢复方案。
- `main` 和长期工作分支都应保持可运行、可测试；CI 失败必须如实报告并修复。

## 4. 两个仓库并行，而不是融合

LearnFlow 与参考仓库 [killoppen/-](https://github.com/killoppen/-) 独立演进：

- 两个仓库拥有独立的 Git 历史、发布节奏、架构权威、数据库和 Agent 上下文。
- 参考仓库默认只读，用于观察学习流程、IDE 交互、前端操作和新的产品创意。
- LearnFlow 只吸收经过筛选的思想，并按自身三类主 Agent、五核、确定性纠错和证据边界重新实现。
- 不把参考仓库添加为需要持续合并的上游，不建立 submodule，不自动同步文件或运行数据。
- 禁止为了跟随参考仓库而自动 merge、rebase、cherry-pick 或批量复制代码。
- 如需复制具体代码、设计资源或文案，先确认许可证、作者归属和兼容性；一般优先独立实现并在提交说明中记录灵感来源。
- 参考实现与 LearnFlow 契约冲突时，以 `AGENTS.md`、`architecture_registry.py` 和架构权威文档为准。

这意味着“两仓并行参考”只共享灵感，不共享状态权威，也不要求功能逐项一致。

## 5. 架构热点的直接推送要求

以下文件或契约发生变化时，不需要 PR 审批，但必须同步更新实现、测试、文档并报告 `Contract impact`：

- `backend/app/services/architecture_registry.py`
- `backend/app/services/learning_runtime.py`
- `backend/app/services/memory_graph.py`
- `backend/app/models/learning.py`
- `backend/app/api/architecture.py`
- `backend/app/services/action_board.py`
- `docs/ARCHITECTURE_AUTHORITY.md`
- `docs/AGENT_ARCHITECTURE_GUIDE.md`
- 三类主 Agent handoff、五核、`EvidenceEvent`、Action Board、`RemediationStrategy` 的 schema 或状态机

涉及本地代码 Agent / Broker 时，还必须验证固定参数、隔离副本、联网边界、两次确认、基础 hash、删除/移动确认、批量回滚和零 kernel target。它始终是 Tutor 的工具，不是第四类主 Agent。

## 6. 最小验证矩阵

所有修改：

```bash
git diff --check
```

后端：

```bash
cd backend
venv/bin/python -m pytest -q
```

前端：

```bash
cd frontend
npm run build
```

架构注册表：

```bash
cd backend
venv/bin/python -m pytest tests/test_architecture_registry.py -q
```

本地 Agent Broker：

```bash
cd backend
venv/bin/python -m pytest tests/test_local_agent_broker.py tests/test_workspace.py tests/test_architecture_registry.py -q
```

比赛或 demo：

```bash
bash start.sh demo
```

只执行与改动相关的检查；未执行的项目必须明确写“未执行”及原因。

## 7. 给任意 Codex 的首条消息

```text
你正在个人维护的 LearnFlow 仓库工作。开始前完整阅读根目录 AGENTS.md 和
docs/GITHUB_COLLABORATION.md，并执行 git status -sb。已有改动视为用户所有。
本仓库日常任务不建 Issue、不强制建分支、不建 PR；用户要求修改或实现时，完成适用测试后
直接 commit 并 push 当前分支。禁止 rebase、force push、reset --hard、提交秘密或覆盖任务外改动。
LearnFlow 与 https://github.com/killoppen/- 独立演进，只读参考灵感，不自动合并、同步或
cherry-pick。涉及三类主 Agent、五核、EvidenceEvent、Action Board 或 RemediationStrategy 时，
遵守架构权威，并同步更新注册表、实现、测试和文档。最终报告提交、推送和真实测试结果。
```

## 8. 完成定义

任务只有同时满足以下条件才算完成：

- 实现符合用户任务和验收标准，没有无授权扩展。
- 三类主 Agent、五核、事件链和确定性教学边界保持成立。
- 新能力已登记，代码、测试、文档和注册表无漂移。
- 适用检查已实际执行，失败或未执行项已如实记录。
- diff 不含秘密、本地数据、无关改动或用户工作损失。
- 变更已 commit 并直接 push 当前分支，最终报告足以复现和回滚。
