# 对话问答工作流 · 调试说明

工作流资产：`workflows/current/对话问答工作流.yml`
调试输入：`workflows/current/debug-data/对话问答工作流.json`

## 工作流结构

```text
开始 → 解析并规范化请求 → 是否请求学习资料
                         ├─ 是 → 知识库_1 → 代码_1 ┐
                         └─ 否 → 代码_2             ├→ 生成对话回答 → 校验回答输出 → 结束
```

`知识库_1` 使用查询模式 `request_type=3`，只读检索，不写入知识库。插件超时 20 秒并返回空资源；模型超时 60 秒并进入统一降级。回答校验节点负责非法 JSON、空回答、来源数量和敏感信息脱敏。

## AGENT_USER_INPUT

```json
{
  "message": "请结合学习资料说明 getter 返回数组副本的原因",
  "student_id": "STU-WF-001",
  "request_id": "REQ-WF-001",
  "project_id": "PROJECT-JAVA-001",
  "session_id": "SESSION-WF-001",
  "student_profile": {"learning_style": "example_driven"},
  "history_memory": [],
  "kb_text": "",
  "local_context": {},
  "local_sources": [],
  "source_summary": "",
  "assistant_mode": "education",
  "use_learning_materials": true
}
```

`use_learning_materials=true` 进入知识库查询分支；为 `false` 时直接进入空资料分支。缺少或为空的 `message` 返回 `invalid_input`，不会调用模型。

## 结果契约

结束节点输出 `result_json` 字符串，内容结构如下：

```json
{
  "status": "ok",
  "message": "回答正文",
  "ai_generated": true,
  "sources": [],
  "original_question": "原始问题"
}
```

插件、模型或回答解析失败时返回 `fallback`；不伪造来源，不输出 API Key、Token、Secret 等敏感信息。
