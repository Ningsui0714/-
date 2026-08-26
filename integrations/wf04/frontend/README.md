# 统一学习前端

该前端对应两个独立的星辰工作流：

- `测验后个性化错误讲解工作流_v4.yml`
- `连续学习个性化讲解工作流_v4.yml`

页面分为：

- 学习中心：消费连续学习工作流返回的学习路径、教学策略、内容块、资源和阶段检查请求。
- 测验讲解：消费测验讲解工作流返回的错误证据、针对性讲解、重做提示和恢复状态。
- 学习记录：展示讲解会话和练习作答记录。
- 设置：保存教学方式、讲解深度和无障碍偏好。

顶部通知和学生账户、学习路径收起与节点切换、收藏、结构化来源、题目筛选均有真实交互。测验页的“换种讲法”通过后端创建新讲解会话；“重做原题”和“变式题”通过题目服务生成题目、展示输入区并保存作答，答错后自动进入纠错讲解。

## 运行

```powershell
python backend\server.py
```

访问 `http://127.0.0.1:4173/`。不要直接打开 `file:///.../index.html`，因为本地文件页面无法调用后端 API。

## 前后端连接

`api.js` 监听页面派发的 `workflow-request` 事件，并调用：

- `/api/workflows/learning`
- `/api/workflows/review`
- `/api/workflows/review/resume`
- `/api/explanations`
- `/api/practice/questions`
- `/api/question-instances/{id}/attempts`
- 学生通知、记录、设置、收藏和来源接口

后端会补齐学生、学习目标、薄弱点、路径和教学历史，再调用星辰工作流。响应交给 `window.personalizedLearningUI.applyWorkflowResult()`，动态渲染学习路径、教学内容、资源和测验讲解。

教学方式和测验讲解方式不会在请求完成前修改选中状态。前端以服务返回的 `delivery_mode` 为准，失败时保留原内容与原选择。

默认使用 `mock` 模式并自动写入一条上游演示数据。接入真实星辰工作流的方法见 `backend/README.md`。
