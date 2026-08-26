<!-- LearnFlow 日常维护采用验证后直接 push。仅在用户明确要求 PR 或接收外部贡献时使用本模板。 -->

## What

<!-- 本 PR 改变了什么？ -->

## Why

<!-- 用户价值、问题根因或 Issue 链接。 -->

## Contract impact

<!-- 必填。如无影响，明确写 None。 -->

- [ ] None
- [ ] Agent / handoff
- [ ] Five-kernel / EvidenceEvent / Memory Graph
- [ ] Action Board / RemediationStrategy
- [ ] API / database / migration
- [ ] Architecture registry / shared documentation

Details:

## Evidence

<!-- 只写实际执行的检查；未执行的项写明原因。 -->

- [ ] `git diff --check`
- [ ] Backend: `cd backend && venv/bin/python -m pytest -q`
- [ ] Frontend: `cd frontend && npm run build`
- [ ] Architecture registry validation
- [ ] Seeded demo

Results:

## Demo

<!-- 独立复现步骤；UI 变更附截图/录屏。 -->

## Risks and rollback

<!-- 已知风险、兼容性、回滚方式。 -->

## Final checklist

- [ ] 未 force push、rebase 或改写已发布历史
- [ ] diff 不含 `.env`、token、数据库、缓存、权重或日志
- [ ] 未修改任务范围外的用户改动
- [ ] 共享契约变更已同步注册表、实现、测试和文档
