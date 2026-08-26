# LearnFlow 比赛维护包

本目录用于比赛演示、离线验收和最终提交维护。演示入口先进入全局复习台，预置一项到期变式和一项未闭环错题；主线固定为：

```text
答错 -> 错误证据 -> 确定性纠错策略 -> 换讲法/步骤/示例
     -> 重做原题 -> 变式验证 -> EvidenceEvent 回写五核与记忆图谱
```

## 一键运行

```bash
bash start.sh demo
# 或 make demo
```

脚本会安全重建专用的 `backend/data/competition-demo.db`，不会修改日常数据库，因此每次都从相同状态开始；同时清空 LLM key、关闭外部资源搜索和自动记忆综合，seed 完成后打开 `/demo`。如果日常实例已占用 8010/5173，脚本会自动选择成对的可用端口，并让前端代理到本次 demo 后端。`/demo` 自动进入隔离演示账号并跳到 `/review`，整个取题、纠错、变式和状态写回不依赖 LLM 或网络。

## 文档索引

- `DEMO_RUNBOOK.md`：3–5 分钟讲解和故障切换。
- `SUBMISSION_CHECKLIST.md`：按比赛材料编号维护交付物。
- `USER_TEST_TEMPLATE.md`：2–3 名学生或教师试用的证据模板。
- `ETHICS_AND_DATA_TEMPLATE.md`：数据、AI 标识和学术诚信声明底稿。
- `../ARCHITECTURE_AUTHORITY.md`：架构维护边界和变更规则。
- `../FUSION_CATALOG.md`：两仓库并行参考时的能力映射与去重决策。
- `../DESKTOP_WORKSPACE_SECURITY.md`：桌面文件工作区、sidecar、路径和证据边界。

## 可复现验收

```bash
cd backend
venv/bin/python -m pytest tests/test_architecture_registry.py tests/test_remediation.py tests/test_review.py -q

cd ../frontend
npm run build
```

演示版本还应记录 `GET /api/architecture/registry` 返回的 `version` 和 `digest`。它们能证明现场运行的是哪一版 Agent/五核/能力/事件契约。

桌面内部包验收时另行记录操作系统、安装包 hash、随机 loopback 端口、目录关联、讲义版本冲突、草稿/正式提交证据边界、Markdown/PDF/image 预览、hash 冲突和删除恢复结果。浏览器 seeded demo 仍是无桌面依赖的保底演示，不能因为本地文件权限失败而失效。

比赛规则以官方最新通知为准。本维护包依据参考仓库中的 2026 比赛方案整理，提交前必须再次核对日期、命名、平台编号和盖章要求。
