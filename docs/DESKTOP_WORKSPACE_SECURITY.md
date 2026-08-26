# LearnFlow 桌面工作区与安全边界

本文是 Tauri 2 桌面工作区的安全契约。桌面工作区扩展文件操作能力，但不改变三类主 Agent、五核、学习对象权威或正式判题链。

## 1. 信任模型

- 浏览器部署的 `DESKTOP_MODE` 必须保持 `false`，本地文件接口对浏览器返回 404。
- Tauri 每次启动生成新的高熵桌面令牌，并在随机 loopback 端口启动 FastAPI sidecar。
- 每个文件请求同时校验登录会话、项目 `learner_id` 归属和 `X-LearnFlow-Desktop-Token`。
- 桌面版“模型设置”也要求登录会话和本次启动令牌；配置保存在应用数据目录的 `settings.env`，不写入仓库或项目工作区。
- 浏览器继续使用 HTTP-only cookie。由于 Tauri WebView 与 loopback sidecar 可能跨站，只有桌面令牌校验成功的登录/注册请求才会额外返回桌面 Bearer；Bearer 仅保存在该窗口的 `sessionStorage`，服务端接受它时仍要求本次启动令牌。
- WebView 只有目录选择能力，没有 `$HOME/**` 或任意文件系统权限。真正的项目根约束由 FastAPI 再次执行。
- sidecar 只允许绑定 `127.0.0.1`、`::1` 或 `localhost`；桌面令牌不得写入仓库、日志或数据库。

桌面工作区本身不提供 Python 解释器、终端、编译或任意代码运行能力。普通 `.py` 与其他 UTF-8 文本一样，只能查看和轻量编辑；本地代码 Agent 由独立 Broker 在隔离副本中执行。

## 本地 Agent Broker

- Profile 只保存允许登记的 adapter、可执行文件、任务类型、能力、优先级、沙箱和联网策略，不接受任意 shell 模板。
- 首版 Codex adapter 固定以参数数组执行 `codex exec --json --sandbox workspace-write -C <isolated> -`，不经过 shell；复用本机 Codex 登录，不读取或保存明文凭据。
- 沙箱与联网是两条独立权限边界。Codex adapter 首版联网策略必须标为 `unmanaged`；若无法真正保证断网，UI 明确显示“未受管”。seeded fake adapter 才登记为可验证的 `managed_off`。
- Git 项目在独立 clone 中覆盖当前安全磁盘快照；非 Git 项目复制后初始化临时 Git。`.learnflow`、`.git` 内容、`.env`、密钥、符号链接/reparse point、缓存和构建目录不进入任务快照。
- 子 Agent 不能访问真实工作区、学习对象、五核或数据库。结果仅形成事件、测试、风险和文本 diff。
- 第一次确认启动隔离任务；第二次确认才应用。删除/移动逐项确认，基础 hash 变化会把结果标记为 `stale`，批量失败恢复真实文件快照。
- Broker 操作事件没有 kernel target；它们不是学习证据。

## 2. 权威数据

每个 `ProjectWorkspace` 只关联一个真实本地目录。普通文件以磁盘为权威；讲义、练习和判题规则仍以数据库为权威。

```text
<ProjectRoot>/
  用户文件
  .learnflow/
    project.lfproject
    checkpoints/cp-<id>/
      lectures/lecture-<id>.lflecture
      exercises/exercise-<id>.lfexercise
    history/
    trash/
```

`.lflecture` 与 `.lfexercise` 只保存 schema、对象 ID、摘要、版本和摘要 hash。它们不能代替数据库正文，也不能通过普通文件 API 读取或改写。

## 参考来源与项目文件分离

- GitHub 仓库、网页 URL 和用户上传的文件都是项目的参考来源，不属于链接的项目工作区。
- GitHub/URL 处理产生的图片、Markdown 等派生缓存保存在应用数据目录的来源缓存中；用户上传的原件保存在独立的来源上传目录中。
- 来源缓存和上传原件不会写入项目目录，也不会被工作区文件树当作普通项目文件展示。工作区只管理用户项目文件和 `.learnflow` 下的讲义/练习受管描述文件。

## 3. 路径约束

文件服务在每次访问时执行以下检查：

1. 路径必须是相对于已登记项目根的 UTF-8 逻辑路径。
2. 拒绝绝对路径、盘符、NUL、`.`、`..` 和越界后的真实路径。
3. 从根到目标的每一层都拒绝符号链接；Windows 同时拒绝 junction/reparse point。
4. `.learnflow` 与 `.git` 对普通文件 API 始终受保护。
5. Agent 额外禁止 `.env`、凭据、私钥和常见密钥后缀。
6. 文本编辑只接受 UTF-8，单文件上限 2 MB；大型或二进制文件只返回元数据。

目录关联时会验证既有 `project.lfproject`。同一目录不能登记给两个 LearnFlow 项目，也不能覆盖属于另一项目的 marker。

## 4. 写入与恢复

- 人工编辑保存时必须携带所读版本的 SHA-256；文件已变化时返回冲突，不覆盖新内容。
- Agent 提案必须绑定当前学习者、项目、关卡和 Tutor session，保存统一 diff 后等待用户明确确认。
- 删除、重命名和移动均使用 `WorkspaceOperation`；删除进入 `.learnflow/trash/op-<id>/`，不做永久删除。
- 覆盖前的内容进入 `.learnflow/history/op-<id>/`；同一幂等键或同一确认重复调用只应用一次。
- 提案默认 30 分钟过期；基础 hash 变化后状态变为 `stale`，必须重新读取和提案。

桌面 Explorer 将数据库权威的“关卡资料”和磁盘权威的“项目文件”分成两个逻辑组，不展示 `.learnflow`。普通文本由 Monaco 打开，可使用多标签、最多三个编辑组、Vim 键位和 `⌘S/Ctrl+S`；Markdown 提供安全的预览/源码/分屏，工作区相对图片通过带桌面令牌的 blob 请求载入，不渲染不安全 HTML；图片和 PDF 内置预览，其他二进制显示元数据并可由系统打开。创建、重命名、移动、删除、恢复及 Finder/Explorer 定位都经同一受控 API。

文件系统与 SQLite 无法形成跨介质原子事务，因此磁盘变更先产生回滚快照，再登记 applied 状态和事件。异常操作保留 `failed/stale` 记录，不能伪装成功。

## 5. 学习文件播放器与证据边界

- `.lflecture/.lfexercise` 是只读引用描述符，双击分别打开讲义播放器和练习播放器，普通文件 API 无权读取或修改它们。
- 讲义保存必须携带 `base_version`；冲突返回 409，保存前的内容进入 `LectureVersion`，批注随正文重定位，无法唯一定位的进入“未定位笔记”。
- 练习题面、标准答案、测试和判题规则保持受保护；用户只保存个人答案、代码、草稿和批注。`Exercise.files` 继续作为兼容虚拟子文件。
- 草稿与练习“运行”不产生 `LearningAttempt` 或 `EvidenceEvent`；正式提交才判题并写证据。
- 正式提交携带 `client_submission_id`，重复请求返回同一 `LearningAttempt`，不会重复写评估事件。

## 6. 五核与证据

`workspace_linked` 和 `workspace_change_applied` 是 `kernel_targets=()` 的操作事件。它们用于审计，不产生 `KernelMutation`，也不能证明学习者掌握了知识或具备独立实践能力。

只有学习对象播放器里的正式提交判题结果可以进入 `LearningAttempt/EvidenceEvent`。打开、编辑、保存草稿和运行成功都不是掌握证据；首版不允许普通项目文件直接作为练习答案提交。

## 7. 验收命令

```bash
cd backend
PYTHONPATH=. python -m pytest tests/test_workspace.py tests/test_architecture_registry.py -q

cd ../frontend
npm run build
```

`.github/workflows/desktop-internal.yml` 在 macOS 14 与 Windows 2022 运行后端契约测试、前端构建、sidecar 打包和 Tauri 内部包构建，并上传未签名产物。签名和商店凭据不属于本轮仓库内容。
