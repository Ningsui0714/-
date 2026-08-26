"""
Seed: PyTorch 训练循环入门（试探项目）

在 LearnFlow 中创建一个完整课程：
- 闯关图：5 个 checkpoint（Tensor → autograd → nn.Module → 训练循环 → 实验）
- 每个 checkpoint：讲义 sections + 概念题 + 代码练习
- CP4 是多文件项目（data.py / model.py / train.py 填空），
  支持保存代码 + 本地自动配环境（venv + torch）运行 + stdout 判题

用法:
    cd backend
    venv/bin/python scripts/seed_training_loop.py
重复运行是幂等的（按项目名查找，存在则更新）。
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.db.database import async_session, init_db
from app.models.project import (
    Project, Roadmap, Checkpoint, Lecture, Exercise, ConceptQuestion,
)


# ══════════════════════════════════════════════════════════════════
# 讲义内容（来自 docs/05-PyTorch与训练循环讲义.md）
# ══════════════════════════════════════════════════════════════════

LECTURE_CP1 = [{
    "title": "Tensor：PyTorch 的基本单位",
    "content": """**Tensor = 多维数组 + 自动求导能力**。形状和 numpy 一样，但多了两个关键能力：能搬到 GPU、能自动算梯度。

```python
import torch

a = torch.tensor([1.0, 2.0, 3.0])        # 一维
b = torch.zeros(2, 3)                     # 2×3 全 0
c = torch.randn(4, 2)                     # 4×2 标准正态随机数

print(c.shape)        # torch.Size([4, 2])
print(c.dtype)        # torch.float32
print(c.device)       # cpu 或 mps

x = torch.randn(3, 4)
w = torch.randn(4, 5)
y = x @ w             # 矩阵乘, 结果是 (3, 5)
```

**关键习惯：每写一行，心里过一遍形状**。训练循环 90% 的 bug 是形状不匹配。

标量 (0 维 tensor) 和 Python float 的区别：

```python
s = x.sum()
print(s)              # tensor(1.2345)
print(s.item())       # 1.2345  ← 打印 loss 时用 .item()
```

**安装与环境**（MacBook Air / Apple Silicon）：

```bash
pip install torch scikit-learn
```

```python
import torch
print(torch.__version__)                      # 版本号
print(torch.backends.mps.is_available())      # True 说明可以用 GPU(MPS)
```

`device` 概念：tensor 有 device 属性，数据在哪个设备上，就必须和模型在同一个设备。""",
    "keywords": ["tensor", "shape", "dtype", "device", "MPS"],
    "questions": ["Tensor 和 numpy 数组的核心区别是什么？", "为什么每写一行都要想形状？"],
}, {
    "title": "autograd：自动求导",
    "content": """PyTorch 最核心的魔法：**你只写 forward（正向计算），backward（反向求梯度）自动完成**。

```python
x = torch.tensor([2.0], requires_grad=True)   # 声明: 我要对 x 求导
w = torch.tensor([3.0], requires_grad=True)
b = torch.tensor([1.0], requires_grad=True)

y = w * x + b          # forward: 每个运算被记录到"计算图"上
loss = (y - 5.0) ** 2  # 假设真实值是 5

loss.backward()        # 反向传播: 自动用链式法则算梯度
print(x.grad)          # tensor([-12.])  ← 梯度存在 .grad 里
```

要点：

- `requires_grad=True`：告诉 PyTorch"这个 tensor 是叶子节点，我要它的梯度"
- **计算图**：从输入到 loss 的每个运算，PyTorch 都记了一笔账。`backward()` 顺着账本从 loss 往回走，用链式法则算出每个叶子节点的梯度
- 梯度存在 `.grad` 里，不是返回值
- 你**不需要也不应该**手写梯度。你的职责是写对 forward，backward 是免费的

> 类比：forward 是"按菜谱做菜"，backward 是"根据最终味道自动追溯每步放了多少盐"。你只管做菜。""",
    "keywords": ["autograd", "requires_grad", "backward", "计算图", "链式法则"],
    "questions": ["backward() 到底做了什么？", "梯度存在哪里？"],
}]


LECTURE_CP2 = [{
    "title": "nn.Module：把网络组织成对象",
    "content": """手写矩阵运算太原始了。PyTorch 用 `nn.Module` 把"网络"组织成一个对象：**它替你管理参数**。

```python
import torch.nn as nn

class MLP(nn.Module):
    def __init__(self, input_dim, hidden_dim, output_dim):
        super().__init__()
        self.fc1 = nn.Linear(input_dim, hidden_dim)   # 线性层: 权重 + 偏置
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(hidden_dim, output_dim)

    def forward(self, x):
        h = self.relu(self.fc1(x))   # 数据流: 输入 → 线性 → 激活 → 线性
        out = self.fc2(h)
        return out
```

拆解：

- `nn.Linear(in, out)` 内部持有两个参数：权重 `weight` (out, in) 和偏置 `bias` (out)。`y = x @ Wᵀ + b`
- `__init__`：**建层**（定义网络有什么零件）
- `forward`：**定义数据怎么流**（零件怎么组装）
- 调用：`model(x)` 会自动调 `forward(x)`——**模型对象本身可调用**

参数管理是 Module 的核心价值：

```python
model = MLP(2, 16, 2)
for name, param in model.named_parameters():
    print(name, param.shape)
# fc1.weight torch.Size([16, 2])
# fc1.bias   torch.Size([16])
# fc2.weight torch.Size([2, 16])
# fc2.bias   torch.Size([2])
```

`model.parameters()` 返回所有参数——**这就是优化器要更新的东西**。""",
    "keywords": ["nn.Module", "nn.Linear", "forward", "parameters"],
    "questions": ["__init__ 和 forward 各负责什么？", "为什么说 Module 替你管理参数？"],
}, {
    "title": "损失函数与优化器",
    "content": """```python
criterion = nn.CrossEntropyLoss()            # 分类损失
optimizer = optim.Adam(model.parameters(), lr=1e-3)   # 优化器
```

两个关键理解：

**1. CrossEntropyLoss 内部自带 softmax**。模型输出的是 logits（未归一化的分数, 比如 [2.0, -1.5]），直接喂进去。不要再手动 softmax——这是新手最常见的坑。

**2. 优化器 = "拿着梯度去更新参数"的执行者**。`optimizer.step()` 做的事，等价于（对 SGD 而言）：

```
param = param - lr * param.grad
```

Adam 只是把 `lr * grad` 换成更聪明的更新量（自适应学习率），但骨架一样：**读 .grad → 更新参数**。""",
    "keywords": ["CrossEntropyLoss", "logits", "optimizer", "Adam", "step"],
    "questions": ["CrossEntropyLoss 内部自带什么？", "optimizer.step() 做了什么？"],
}]


LECTURE_CP3 = [{
    "title": "训练循环五步法（核心）",
    "content": """所有深度学习训练，不管什么模型，都是这个骨架：

```python
for epoch in range(NUM_EPOCHS):
    for x_batch, y_batch in dataloader:
        # ① forward    用模型算预测
        pred = model(x_batch)

        # ② loss       预测和真实的差距 (一个标量)
        loss = criterion(pred, y_batch)

        # ③ zero_grad  清空上一次的梯度
        optimizer.zero_grad()

        # ④ backward   算梯度: 从 loss 反传, 填满每个参数的 .grad
        loss.backward()

        # ⑤ step       用梯度更新参数
        optimizer.step()
```

**逐行讲**：

- **① `pred = model(x_batch)`**：调用 `forward`。`x_batch` 形状 (B, 2)，`pred` 形状 (B, 2)
- **② `loss = criterion(pred, y_batch)`**：算一个**标量**。为什么必须标量？因为 `backward()` 需要从"一个数"开始反传
- **③ `optimizer.zero_grad()`**：**最重要的一行，顺序也最关键**。PyTorch 的梯度是**累加**的（`param.grad += 新算的梯度`）。不清空的话，上一个 batch 的梯度会叠到这一个 batch 上。顺序必须是 `zero_grad → backward → step`
- **④ `loss.backward()`**：顺着计算图反传，用链式法则把梯度填进每个参数的 `.grad`
- **⑤ `optimizer.step()`**：读每个参数的 `.grad`，更新参数：`param ← param − lr · grad`

**epoch / batch / step 的关系**：

```
epoch  = 完整过一遍所有数据
step   = 处理一个 batch（执行一次 ①-⑤）
steps per epoch = len(数据) / batch_size
```

例：1000 个样本，batch_size=64，一个 epoch 约 16 个 step。100 个 epoch = 1600 次参数更新。

**batch_size 是 trade-off**：越大，每个 step 的梯度估计越准（loss 曲线更平滑），但一次占用内存越大；越小，更新越频繁、噪声越大。""",
    "keywords": ["训练循环", "forward", "loss", "zero_grad", "backward", "step", "epoch", "batch"],
    "questions": ["为什么 zero_grad 必须放在最前？", "为什么 loss 必须是标量？", "epoch/step/batch 的关系？"],
}, {
    "title": "数据流水线：Dataset 与 DataLoader",
    "content": """```python
dataset = torch.utils.data.TensorDataset(X, y)          # (特征, 标签) 打包
dataloader = torch.utils.data.DataLoader(
    dataset,
    batch_size=64,
    shuffle=True,          # 每个 epoch 打乱顺序, 防止模型学到样本顺序
)
```

- `DataLoader` 每次迭代吐出一个 **batch**：`(x_batch, y_batch)`
- `shuffle=True`：每个 epoch 开始前打乱数据——否则模型可能记住顺序而非规律
- 为什么分批而不是一次全喂：内存限制 + 小 batch 的梯度噪声有正则化效果""",
    "keywords": ["Dataset", "DataLoader", "batch", "shuffle"],
    "questions": ["shuffle=True 为什么重要？", "为什么要分批训练？"],
}]


LECTURE_CP4 = [{
    "title": "完整代码走读：线性回归（最小可运行示例）",
    "content": """用最简单的任务（拟合 y = 2x + 1）把整个流程串一遍。这段**故意**不用 nn.Module，让你看到训练循环的最小本质——**循环里就只有那五步**：

```python
import torch

# ---- 数据: y = 2x + 1 + 噪声 ----
x = torch.randn(200, 1)
y_true = 2 * x + 1 + 0.1 * torch.randn(200, 1)

# ---- 参数: 手动创建, 声明要梯度 ----
w = torch.randn(1, 1, requires_grad=True)
b = torch.zeros(1, 1, requires_grad=True)

lr = 0.05
for epoch in range(500):
    # ① forward
    y_pred = x @ w + b

    # ② loss: 均方误差 (标量!)
    loss = ((y_pred - y_true) ** 2).mean()

    # ③④⑤
    w.grad = None   # 手动清空 (等价于 optimizer.zero_grad())
    b.grad = None
    loss.backward()          # ④ 算梯度
    with torch.no_grad():    # ⑤ 更新参数
        w -= lr * w.grad
        b -= lr * b.grad

    if epoch % 100 == 0:
        print(f"epoch {epoch:3d} | loss {loss.item():.4f} | w {w.item():.2f} b {b.item():.2f}")
```

跑一下，你会看到 w 从随机值一路逼近 2，b 逼近 1。**这就是深度学习的全部本质**：一个循环，五步动作，反复执行。""",
    "keywords": ["线性回归", "走读", "训练循环本质"],
    "questions": ["这段代码里哪几步对应五步法？"],
}]


LECTURE_CP5 = [{
    "title": "三个实验：用身体记住超参",
    "content": """做完练习项目后，动手做这三个实验（每个都在项目里改一行/删一行，跑一次，记录现象）：

### 实验 A：lr 从 1e-2 改成 1.0

**预期**：loss 不降反升，甚至变成 nan（无穷大）。

**为什么**：学习率是"每步走多远"。步子太大，直接跨过最低点，越走越远，最后梯度爆炸。loss 曲线震荡/发散 = lr 太大。

### 实验 B：删掉 `optimizer.zero_grad()`

**预期**：loss 乱跳，不收敛。

**为什么**：梯度累加。第 n 个 batch 的梯度 = 前 n 个 batch 梯度之和，参数被"历史旧账"拖着走，完全偏离真实梯度方向。

### 实验 C：batch_size 改成 1 和 256 各跑一次

**预期**：batch=1 时 loss 曲线剧烈抖动；batch=256 时曲线平滑但收敛可能更慢/更稳。

**为什么**：batch 越小，每次梯度越"噪音大"；越大越接近真实梯度方向。""",
    "keywords": ["学习率", "zero_grad", "batch_size", "实验"],
    "questions": ["lr 太大有什么症状？", "删掉 zero_grad 为什么发散？"],
}, {
    "title": "验收：费曼测试",
    "content": """能不看任何资料回答这三个问题，就算过：

1. **`backward()` 做了什么？** —— 从 loss 出发，沿计算图用链式法则反向传播，算出每个参数的梯度，存进 `.grad`。你只写 forward，backward 自动完成。
2. **`step()` 做了什么？** —— 读每个参数的 `.grad`，执行 `param ← param − lr × grad`（Adam 则是更聪明的更新量）。
3. **为什么每个 batch 前要 `zero_grad()`？** —— PyTorch 的梯度是累加的（`.grad += 新梯度`），不清空的话旧 batch 的梯度会污染本次更新。

再加一个动手验收：不看讲义，从零写一个训练循环（哪怕是线性回归）。""",
    "keywords": ["验收", "费曼测试"],
    "questions": ["backward/step/zero_grad 各做了什么？"],
}]


# ══════════════════════════════════════════════════════════════════
# 填空练习文件
# ══════════════════════════════════════════════════════════════════

DATA_PY = '''"""数据准备：生成二分类数据。（只读文件，不需要改）"""
from sklearn.datasets import make_moons
import torch


def make_data(n_samples=1000, noise=0.1, seed=42):
    """返回 (X, y): X 形状 (1000, 2), y 形状 (1000,)"""
    X, y = make_moons(n_samples=n_samples, noise=noise, random_state=seed)
    X = torch.tensor(X, dtype=torch.float32)   # 特征: float32
    y = torch.tensor(y, dtype=torch.long)      # 标签: long (CrossEntropyLoss 要求)
    return X, y
'''

MODEL_PY = '''"""两层 MLP 模型。

你的任务: 填 TODO 1 (两处 `...`)。其余都是完整的。
"""
import torch.nn as nn


class MLP(nn.Module):
    def __init__(self, input_dim=2, hidden_dim=16, output_dim=2):
        """
        input_dim:  输入特征维度 (make_moons 是 2)
        hidden_dim: 隐藏层宽度
        output_dim: 输出类别数 (二分类是 2)
        """
        super().__init__()

        # ===== TODO 1a: 定义第一层线性层 =====
        # 目标: 输入 input_dim 维 → 输出 hidden_dim 维
        # 提示: nn.Linear(输入维度, 输出维度)
        self.fc1 = nn.Linear(...)

        self.relu = nn.ReLU()

        # ===== TODO 1b: 定义第二层线性层 =====
        # 目标: 输入 hidden_dim 维 → 输出 output_dim 维
        self.fc2 = nn.Linear(...)

    def forward(self, x):
        # ===== TODO 1c: 前向传播 =====
        # 数据流: x → fc1 → relu → fc2
        # 提示: 先过 fc1, 再过 relu, 最后过 fc2
        out = ...
        return out
'''

TRAIN_PY = '''"""训练循环主脚本。

你的任务: 填 TODO 2, 3, 4。其余都是完整的。
运行: python train.py
"""
import torch
import torch.nn as nn
import torch.optim as optim

from model import MLP
from data import make_data


# ===== 超参数 =====
LR = 1e-2
EPOCHS = 100
BATCH_SIZE = 64


def main():
    # --- 1. 数据 (完整, 不用改) ---
    X, y = make_data()
    dataset = torch.utils.data.TensorDataset(X, y)
    dataloader = torch.utils.data.DataLoader(
        dataset, batch_size=BATCH_SIZE, shuffle=True
    )

    # --- 2. 模型 / 损失 / 优化器 (完整, 不用改) ---
    model = MLP()
    criterion = nn.CrossEntropyLoss()          # 分类损失, 内部自带 softmax
    optimizer = optim.Adam(model.parameters(), lr=LR)

    # --- 3. 训练循环 ---
    for epoch in range(EPOCHS):
        total_loss = 0.0
        for x_batch, y_batch in dataloader:
            # ===== TODO 2: 前向传播 =====
            # 目标: 用模型算预测 logits
            # 提示: model(x_batch) 会自动调 forward
            pred = ...

            # ===== TODO 3: 计算损失 =====
            # 目标: 预测和真实标签的差距 (标量)
            # 提示: criterion(pred, y_batch), 注意 CrossEntropyLoss 内部自带 softmax
            loss = ...

            # ===== TODO 4: 梯度三件套 (顺序非常重要!) =====
            # 提示: 顺序是 zero_grad → backward → step
            optimizer.zero_grad()   # ① 清空上一次的梯度 (为什么? 想一想)
            ...                     # ② 反向传播: 从 loss 一路算回每个参数的梯度
            ...                     # ③ 更新参数: param ← param - lr * grad

            total_loss += loss.item() * len(x_batch)

        avg_loss = total_loss / len(dataset)
        print(f"epoch {epoch+1:3d}/{EPOCHS} | avg loss {avg_loss:.4f}")

    # --- 4. 评估: 打印准确率 (完整, 不用改) ---
    with torch.no_grad():
        pred = model(X)
        acc = (pred.argmax(dim=1) == y).float().mean().item()
    print(f"test accuracy: {acc:.2%}")


if __name__ == "__main__":
    main()
'''

# 完整答案（用于 solution 字段，也方便验证）
MODEL_PY_SOLUTION = MODEL_PY.replace(
    "self.fc1 = nn.Linear(...)", "self.fc1 = nn.Linear(input_dim, hidden_dim)"
).replace(
    "self.fc2 = nn.Linear(...)", "self.fc2 = nn.Linear(hidden_dim, output_dim)"
).replace(
    "out = ...\n        return out", "out = self.fc2(self.relu(self.fc1(x)))\n        return out"
)

TRAIN_PY_SOLUTION = TRAIN_PY.replace(
    "pred = ...", "pred = model(x_batch)"
).replace(
    "loss = ...", "loss = criterion(pred, y_batch)"
).replace(
    "optimizer.zero_grad()   # ① 清空上一次的梯度 (为什么? 想一想)\n            ...                     # ② 反向传播: 从 loss 一路算回每个参数的梯度\n            ...                     # ③ 更新参数: param ← param - lr * grad",
    "optimizer.zero_grad()   # ① 清空上一次的梯度 (为什么? 想一想)\n            loss.backward()        # ② 反向传播: 从 loss 一路算回每个参数的梯度\n            optimizer.step()       # ③ 更新参数: param ← param - lr * grad",
)


# ══════════════════════════════════════════════════════════════════
# 概念题
# ══════════════════════════════════════════════════════════════════

CONCEPTS = {
    "cp1": [
        {
            "question": "Tensor 和 numpy 数组的核心区别是什么？",
            "options": ["Tensor 支持 GPU 和自动求导", "Tensor 形状永远可变",
                        "numpy 不能做矩阵乘法", "没有区别"],
            "answer_indexes": [0], "q_type": "single", "difficulty": "easy",
            "explanation": "Tensor = 多维数组 + 两个超能力：device（GPU/MPS）和 requires_grad（自动求导）。",
        },
        {
            "question": "判断：训练循环里 90% 的 bug 是形状不匹配，所以每写一行都要想清楚 tensor 的形状。",
            "options": ["正确", "错误"], "answer_indexes": [0],
            "q_type": "judge", "difficulty": "easy",
            "explanation": "对。shape 是 tensor 的第一属性，debug 时先看形状。",
        },
        {
            "question": "打印 loss 时用 loss.item() 而不是直接 print(loss)，为什么？",
            "options": ["item() 把标量 tensor 变成普通 Python 数，输出更干净",
                        "item() 会触发反向传播",
                        "print 不能打印 tensor",
                        "item() 能把 loss 变成 0"],
            "answer_indexes": [0], "q_type": "single", "difficulty": "easy",
            "explanation": "loss 是 0 维 tensor，print 会输出 tensor(0.123)，item() 得到纯数字。",
        },
    ],
    "cp2": [
        {
            "question": "backward() 到底做了什么？",
            "options": ["从 loss 出发沿计算图用链式法则反向传播，算出每个 requires_grad 参数的梯度并存入 .grad",
                        "自动更新所有参数",
                        "清空计算图",
                        "计算 loss 的均值"],
            "answer_indexes": [0], "q_type": "single", "difficulty": "medium",
            "explanation": "backward 只算梯度，不更新参数。更新参数是 step() 的活。",
        },
        {
            "question": "optimizer.step() 做了什么？",
            "options": ["读取每个参数的 .grad，执行 param ← param − lr × grad",
                        "重新计算 forward",
                        "清空梯度",
                        "保存模型"],
            "answer_indexes": [0], "q_type": "single", "difficulty": "medium",
            "explanation": "step = 用梯度更新参数。zero_grad 是另一个独立动作。",
        },
        {
            "question": "为什么每个 batch 前要 optimizer.zero_grad()？",
            "options": ["因为 PyTorch 的梯度是累加的（.grad += 新梯度），不清空旧梯度会污染本次更新",
                        "因为 backward 会失败",
                        "为了省内存",
                        "为了让 loss 变小"],
            "answer_indexes": [0], "q_type": "single", "difficulty": "medium",
            "explanation": "梯度累加是设计特性（支持梯度累积），所以每个 batch 前必须手动清零。",
        },
    ],
    "cp3": [
        {
            "question": "nn.Module 的 __init__ 和 forward 各负责什么？",
            "options": ["__init__ 建层（定义零件），forward 定义数据流（组装）",
                        "__init__ 算梯度，forward 更新参数",
                        "两者都是算 loss",
                        "没有区别"],
            "answer_indexes": [0], "q_type": "single", "difficulty": "easy",
            "explanation": "__init__ 声明网络有哪些层，forward 决定数据怎么流过这些层。",
        },
        {
            "question": "CrossEntropyLoss 内部自带什么？所以模型输出应该是什么？",
            "options": ["自带 softmax；模型输出 logits（未归一化分数）直接喂入",
                        "自带反向传播；模型输出概率",
                        "自带优化器；模型输出 loss",
                        "什么都不带"],
            "answer_indexes": [0], "q_type": "single", "difficulty": "medium",
            "explanation": "新手最常见的坑：手动 softmax 后再喂 CrossEntropyLoss，双重 softmax 会破坏梯度。",
        },
        {
            "question": "model.parameters() 返回的是什么？",
            "options": ["模型所有可训练参数（优化器更新的对象）",
                        "训练数据",
                        "模型结构字符串",
                        "损失函数"],
            "answer_indexes": [0], "q_type": "single", "difficulty": "easy",
            "explanation": "optimizer = optim.Adam(model.parameters(), lr=...) 就是拿全部参数去更新。",
        },
    ],
    "cp4": [
        {
            "question": "训练循环五步法的正确顺序是？",
            "options": ["forward → loss → zero_grad → backward → step",
                        "zero_grad → forward → loss → step → backward",
                        "backward → step → forward → loss → zero_grad",
                        "loss → forward → step → zero_grad → backward"],
            "answer_indexes": [0], "q_type": "single", "difficulty": "medium",
            "explanation": "先算预测和 loss，再清空旧梯度，然后 backward 算梯度，最后 step 更新。",
        },
        {
            "question": "为什么 loss 必须是标量？",
            "options": ["因为 backward() 需要从\"一个数\"开始反传，梯度方向才唯一",
                        "因为标量更快",
                        "因为 loss 是 0 维才合法",
                        "其实可以是向量"],
            "answer_indexes": [0], "q_type": "single", "difficulty": "medium",
            "explanation": "向量 loss 的梯度方向不唯一，无法直接反传。分类任务 CrossEntropyLoss 输出就是标量。",
        },
        {
            "question": "1000 个样本，batch_size=64，一个 epoch 大约多少个 step？",
            "options": ["16", "64", "1000", "100"],
            "answer_indexes": [0], "q_type": "single", "difficulty": "easy",
            "explanation": "1000 / 64 ≈ 15.6，向上取整约 16 个 step（最后一个 batch 不满）。",
        },
    ],
    "cp5": [
        {
            "question": "实验 A：把 lr 从 1e-2 改成 1.0，最可能看到什么？",
            "options": ["loss 不降反升甚至变成 nan（步子太大跨过最低点，梯度爆炸）",
                        "训练变快且 loss 更低",
                        "没有任何变化",
                        "模型直接不训练"],
            "answer_indexes": [0], "q_type": "single", "difficulty": "easy",
            "explanation": "学习率是步长。太大 → 震荡/发散/nan；太小 → 收敛极慢。",
        },
        {
            "question": "实验 B：删掉 optimizer.zero_grad()，最可能看到什么？",
            "options": ["loss 乱跳不收敛（梯度累加，参数被历史旧账拖着走）",
                        "训练正常",
                        "loss 变成负数",
                        "内存溢出"],
            "answer_indexes": [0], "q_type": "single", "difficulty": "medium",
            "explanation": "梯度累加导致更新方向完全偏离真实梯度。",
        },
    ],
}


# ══════════════════════════════════════════════════════════════════

CHECKPOINTS = [
    {
        "key": "cp1",
        "title": "Tensor 与 autograd",
        "description": "PyTorch 的基本单位 + 自动求导。看懂 .shape / .grad / backward()",
        "lecture": LECTURE_CP1,
        "concepts": "cp1",
        "exercises": [
            {
                "title": "Tensor 基础练习",
                "description": "补全代码：创建一个 3×4 的随机 tensor x 和一个 4×2 的随机 tensor w，计算 y = x @ w，打印 y 的形状和 y.sum() 的数值。\n\n注意：代码开头已经固定了随机种子 torch.manual_seed(0)，这样每次运行结果一致，判题才能精确匹配。",
                "starter_code": "import torch\n\ntorch.manual_seed(0)  # 固定随机种子，保证判题可复现\n\n# TODO: 创建 x (3,4) 和 w (4,2) 的随机 tensor\n# 提示: torch.randn(行, 列)\nx = ...\nw = ...\n\n# TODO: 矩阵乘\n# 提示: x @ w\ny = ...\n\nprint(\"y shape:\", tuple(y.shape))\nprint(\"y sum:\", round(y.sum().item(), 4))\n",
                "solution": "import torch\n\ntorch.manual_seed(0)\n\nx = torch.randn(3, 4)\nw = torch.randn(4, 2)\n\ny = x @ w\n\nprint(\"y shape:\", tuple(y.shape))\nprint(\"y sum:\", round(y.sum().item(), 4))\n",
                "test_cases": [
                    {"input": "", "expected": "y shape: (3, 2)\ny sum: -1.4325"},
                ],
                "hints": ["torch.randn(3, 4) 创建随机 tensor", "矩阵乘用 @ 而不是 *（* 是逐元素乘）"],
                "order": 0,
            },
            {
                "title": "autograd 小实验",
                "description": "补全：x 的梯度应该是多少？给定 y = 3x + 1，loss = (y - 7)²，对 loss.backward() 后 x.grad 应该等于 12。运行验证。",
                "starter_code": "import torch\n\nx = torch.tensor([2.0], requires_grad=True)\n\n# TODO: 计算 y = 3*x + 1\ny = ...\n\n# TODO: 计算 loss = (y - 7)**2\nloss = ...\n\n# TODO: 反向传播\n...\n\nprint(\"x.grad:\", x.grad.item())\n",
                "solution": "import torch\n\nx = torch.tensor([2.0], requires_grad=True)\n\ny = 3 * x + 1\nloss = (y - 7) ** 2\nloss.backward()\n\nprint(\"x.grad:\", x.grad.item())\n",
                "test_cases": [
                    {"input": "", "expected": "x.grad: 12.0"},
                ],
                "hints": ["y = 3 * x + 1", "loss = (y - 7) ** 2", "loss.backward()"],
                "order": 1,
            },
        ],
    },
    {
        "key": "cp2",
        "title": "nn.Module 与损失/优化器",
        "description": "把网络组织成对象。Linear / forward / CrossEntropyLoss / Adam",
        "lecture": LECTURE_CP2,
        "concepts": "cp2",
        "exercises": [
            {
                "title": "定义 MLP 模型",
                "description": "补全 MLP：两层线性层（2→16, 16→2）+ ReLU。模型定义后打印参数量。",
                "starter_code": "import torch.nn as nn\n\nclass MLP(nn.Module):\n    def __init__(self):\n        super().__init__()\n        # TODO: 第一层: 2 → 16\n        self.fc1 = ...\n        self.relu = nn.ReLU()\n        # TODO: 第二层: 16 → 2\n        self.fc2 = ...\n\n    def forward(self, x):\n        # TODO: x → fc1 → relu → fc2\n        return ...\n\nmodel = MLP()\ntotal = sum(p.numel() for p in model.parameters())\nprint(\"param count:\", total)\n",
                "solution": "import torch.nn as nn\n\nclass MLP(nn.Module):\n    def __init__(self):\n        super().__init__()\n        self.fc1 = nn.Linear(2, 16)\n        self.relu = nn.ReLU()\n        self.fc2 = nn.Linear(16, 2)\n\n    def forward(self, x):\n        return self.fc2(self.relu(self.fc1(x)))\n\nmodel = MLP()\ntotal = sum(p.numel() for p in model.parameters())\nprint(\"param count:\", total)\n",
                "test_cases": [
                    {"input": "", "expected": "param count: 82"},
                ],
                "hints": ["nn.Linear(2, 16) 参数 = 16*2 + 16 = 48", "fc2 参数 = 2*16 + 2 = 34，合计 82"],
                "order": 0,
            },
        ],
    },
    {
        "key": "cp3",
        "title": "训练循环五步法",
        "description": "核心！forward → loss → zero_grad → backward → step。看懂 epoch/batch 关系",
        "lecture": LECTURE_CP3,
        "concepts": "cp3",
        "exercises": [
            {
                "title": "填空：完整的 MLP 训练循环（项目模式）",
                "description": "这是一个多文件项目：data.py（只读）、model.py（TODO 1）、train.py（TODO 2/3/4）。\n\n填完所有 TODO 后，点「💾 保存」再点「▶ 运行」：首次运行会自动准备环境（安装 torch + scikit-learn，约 1-2 分钟），之后秒跑。\n\n验收标准：loss 稳定下降，最后准确率 > 90%，然后点「📋 提交判题」。\n\n🔒 锁头 = 只读文件，不能改（data.py）。\n\n任务清单：\n- model.py TODO 1a/1b: 两层 nn.Linear\n- model.py TODO 1c: forward 数据流\n- train.py TODO 2: pred = model(x_batch)\n- train.py TODO 3: loss = criterion(pred, y_batch)\n- train.py TODO 4: backward + step（zero_grad 已给）",
                "starter_code": MODEL_PY,
                "solution": MODEL_PY_SOLUTION + "\n\n# ===== train.py =====\n" + TRAIN_PY_SOLUTION,
                "test_cases": [],
                "hints": ["nn.Linear(输入维, 输出维)", "criterion(pred, y_batch)", "顺序: zero_grad → backward → step"],
                "order": 0,
                "files": [
                    {"name": "data.py", "content": DATA_PY, "read_only": True},
                    {"name": "model.py", "content": MODEL_PY, "read_only": False},
                    {"name": "train.py", "content": TRAIN_PY, "read_only": False},
                ],
                "entrypoint": "train.py",
                "requirements": ["torch", "scikit-learn"],
                "judge_mode": "stdout_check",
                "judge_config": {"pattern": r"accuracy: (\d+\.\d+)%", "min_accuracy": 90.0},
            },
        ],
    },
    {
        "key": "cp4",
        "title": "完整走读：最小训练循环",
        "description": "线性回归走读：看清训练循环的本质就是五步反复执行",
        "lecture": LECTURE_CP4,
        "concepts": None,
        "exercises": [
            {
                "title": "线性回归：手动更新参数",
                "description": "补全一个最小线性回归训练循环（不用 nn.Module）。w 和 b 已经声明了 requires_grad=True，你只需要补 forward、loss、backward 和手动更新。",
                "starter_code": "import torch\n\nx = torch.randn(200, 1)\ny_true = 2 * x + 1 + 0.1 * torch.randn(200, 1)\n\nw = torch.randn(1, 1, requires_grad=True)\nb = torch.zeros(1, 1, requires_grad=True)\n\nlr = 0.05\nfor epoch in range(500):\n    # TODO: forward: y_pred = x @ w + b\n    y_pred = ...\n\n    # TODO: loss = 均方误差 (标量)\n    loss = ...\n\n    # 清空梯度\n    w.grad = None\n    b.grad = None\n\n    # TODO: 反向传播\n    ...\n\n    # TODO: 手动更新 (用 torch.no_grad() 包住)\n    with torch.no_grad():\n        w -= ...\n        b -= ...\n\n    if epoch % 100 == 0:\n        print(f\"epoch {epoch:3d} | loss {loss.item():.4f} | w {w.item():.2f} b {b.item():.2f}\")\n\nprint(f\"final: w={w.item():.2f} (期望≈2.0), b={b.item():.2f} (期望≈1.0)\")\n",
                "solution": "import torch\n\nx = torch.randn(200, 1)\ny_true = 2 * x + 1 + 0.1 * torch.randn(200, 1)\n\nw = torch.randn(1, 1, requires_grad=True)\nb = torch.zeros(1, 1, requires_grad=True)\n\nlr = 0.05\nfor epoch in range(500):\n    y_pred = x @ w + b\n    loss = ((y_pred - y_true) ** 2).mean()\n\n    w.grad = None\n    b.grad = None\n\n    loss.backward()\n\n    with torch.no_grad():\n        w -= lr * w.grad\n        b -= lr * b.grad\n\n    if epoch % 100 == 0:\n        print(f\"epoch {epoch:3d} | loss {loss.item():.4f} | w {w.item():.2f} b {b.item():.2f}\")\n\nprint(f\"final: w={w.item():.2f} (期望≈2.0), b={b.item():.2f} (期望≈1.0)\")\n",
                "test_cases": [],
                "hints": ["y_pred = x @ w + b", "loss = ((y_pred - y_true) ** 2).mean()", "w -= lr * w.grad"],
                "order": 0,
                "files": [
                    {"name": "main.py", "content": None, "read_only": False},  # placeholder, filled below
                ],
                "entrypoint": "main.py",
                "requirements": ["torch"],
                "judge_mode": "stdout_check",
                "judge_config": {"pattern": r"final: w=(\d+\.\d+) \(期望≈2\.0\), b=(\d+\.\d+) \(期望≈1\.0\)", "min_accuracy": 0.0},
            },
        ],
    },
    {
        "key": "cp5",
        "title": "实验与验收",
        "description": "三个实验：lr 过大 / 删 zero_grad / 改 batch size。然后费曼验收",
        "lecture": LECTURE_CP5,
        "concepts": "cp5",
        "exercises": [
            {
                "title": "实验：观察超参的影响",
                "description": "这是 CP3 那个训练项目的副本，用来做实验。\n\n实验 A：把 train.py 里 LR 改成 1.0，运行，观察 loss（预期：不降反升甚至 nan）。看完改回 1e-2。\n\n实验 B：把 optimizer.zero_grad() 删掉，运行，观察 loss（预期：乱跳不收敛）。看完加回来。\n\n实验 C：把 BATCH_SIZE 改成 1 和 256 各跑一次，对比 loss 曲线平滑度。\n\n做完后运行一次（LR=1e-2, 有 zero_grad, BATCH_SIZE=64）确保恢复，然后提交判题（只检查能否正常跑出训练结果）。",
                "starter_code": MODEL_PY,
                "solution": MODEL_PY_SOLUTION + "\n\n# ===== train.py =====\n" + TRAIN_PY_SOLUTION,
                "test_cases": [],
                "hints": ["实验完记得把超参改回来", "把实验现象记到你的学习笔记里"],
                "order": 0,
                "files": [
                    {"name": "data.py", "content": DATA_PY, "read_only": True},
                    {"name": "model.py", "content": MODEL_PY, "read_only": False},
                    {"name": "train.py", "content": TRAIN_PY, "read_only": False},
                ],
                "entrypoint": "train.py",
                "requirements": ["torch", "scikit-learn"],
                "judge_mode": "stdout_check",
                "judge_config": {"pattern": r"epoch\s+\d+/", "min_accuracy": 0.0},
            },
        ],
    },
]


# ══════════════════════════════════════════════════════════════════

PROJECT_NAME = "PyTorch 训练循环入门"
PROJECT_DESCRIPTION = "试探项目：从 Tensor 到完整训练循环。讲义 + 填空练习 + 闯关图，代码可保存、本地自动配环境运行。"


async def seed():
    await init_db()
    async with async_session() as db:
        # 1. Find or create project
        proj = (await db.execute(
            select(Project).where(Project.name == PROJECT_NAME)
        )).scalar_one_or_none()
        if not proj:
            proj = Project(name=PROJECT_NAME, description=PROJECT_DESCRIPTION,
                           user_level="beginner")
            db.add(proj)
            await db.flush()
            print(f"[seed] created project #{proj.id}: {PROJECT_NAME}")
        else:
            print(f"[seed] project exists #{proj.id}, updating...")

        # 2. Find or create roadmap
        roadmap = (await db.execute(
            select(Roadmap).where(Roadmap.project_id == proj.id)
        )).scalar_one_or_none()
        if not roadmap:
            roadmap = Roadmap(project_id=proj.id, raw_json={})
            db.add(roadmap)
            await db.flush()
            print(f"[seed] created roadmap #{roadmap.id}")

        # 3. Checkpoints (闯关图)
        for i, cp_def in enumerate(CHECKPOINTS):
            title = cp_def["title"]
            cp = (await db.execute(
                select(Checkpoint).where(
                    Checkpoint.roadmap_id == roadmap.id,
                    Checkpoint.title == title,
                )
            )).scalar_one_or_none()
            if not cp:
                cp = Checkpoint(
                    roadmap_id=roadmap.id,
                    title=title,
                    description=cp_def["description"],
                    order=i,
                    prerequisites=list(range(1, i)) if i > 0 else [],  # 1-indexed ids filled below
                )
                db.add(cp)
                await db.flush()
                print(f"[seed] created checkpoint #{cp.id}: {title}")
            else:
                cp.description = cp_def["description"]
                cp.order = i
                print(f"[seed] checkpoint exists #{cp.id}: {title}")

            # prerequisites: fix after all ids known (second pass below)

            # 4. Lecture
            existing_lecture = (await db.execute(
                select(Lecture).where(Lecture.checkpoint_id == cp.id)
            )).scalar_one_or_none()
            if existing_lecture:
                existing_lecture.sections = cp_def["lecture"]
                existing_lecture.status = "published"
            else:
                db.add(Lecture(checkpoint_id=cp.id, sections=cp_def["lecture"],
                               status="published"))
                print(f"[seed] created lecture for cp#{cp.id}")

            # 5. Concept questions
            concept_key = cp_def.get("concepts")
            if concept_key:
                for q in CONCEPTS[concept_key]:
                    existing_q = (await db.execute(
                        select(ConceptQuestion).where(
                            ConceptQuestion.checkpoint_id == cp.id,
                            ConceptQuestion.question == q["question"],
                        )
                    )).scalar_one_or_none()
                    if not existing_q:
                        db.add(ConceptQuestion(
                            checkpoint_id=cp.id,
                            question=q["question"],
                            options=q["options"],
                            answer_indexes=q["answer_indexes"],
                            q_type=q["q_type"],
                            difficulty=q["difficulty"],
                            explanation=q["explanation"],
                            order=0,
                        ))

            # 6. Exercises
            for ex_def in cp_def["exercises"]:
                ex_title = ex_def["title"]
                ex = (await db.execute(
                    select(Exercise).where(
                        Exercise.checkpoint_id == cp.id,
                        Exercise.title == ex_title,
                    )
                )).scalar_one_or_none()

                files = ex_def.get("files", [])
                # CP4 placeholder file: use starter_code as main.py content
                if files and files[0].get("content") is None:
                    files = [{"name": "main.py", "content": ex_def["starter_code"], "read_only": False}]

                if not ex:
                    ex = Exercise(
                        checkpoint_id=cp.id,
                        title=ex_title,
                        description=ex_def["description"],
                        starter_code=ex_def["starter_code"],
                        solution=ex_def["solution"],
                        test_cases=ex_def.get("test_cases", []),
                        hints=ex_def.get("hints", []),
                        order=ex_def.get("order", 0),
                        files=files,
                        entrypoint=ex_def.get("entrypoint", ""),
                        requirements=ex_def.get("requirements", []),
                        judge_mode=ex_def.get("judge_mode", "test_cases"),
                        judge_config=ex_def.get("judge_config", {}),
                    )
                    db.add(ex)
                    print(f"[seed] created exercise: {ex_title}")
                else:
                    ex.description = ex_def["description"]
                    ex.starter_code = ex_def["starter_code"]
                    ex.solution = ex_def["solution"]
                    ex.test_cases = ex_def.get("test_cases", [])
                    ex.hints = ex_def.get("hints", [])
                    # ⚠️ 不覆盖已保存的用户代码: 只在用户从未保存过时写入初始 files
                    if not (ex.files or []):
                        ex.files = files
                    ex.entrypoint = ex_def.get("entrypoint", "")
                    ex.requirements = ex_def.get("requirements", [])
                    ex.judge_mode = ex_def.get("judge_mode", "test_cases")
                    ex.judge_config = ex_def.get("judge_config", {})

        await db.commit()

        # 7. Fix prerequisites (checkpoint ids) — need a second query
        cps = (await db.execute(
            select(Checkpoint).where(Checkpoint.roadmap_id == roadmap.id).order_by(Checkpoint.order)
        )).scalars().all()
        id_by_title = {c.title: c.id for c in cps}
        for cp in cps:
            idx = next(i for i, d in enumerate(CHECKPOINTS) if d["title"] == cp.title)
            prereq_ids = [id_by_title[CHECKPOINTS[j]["title"]] for j in range(idx) if CHECKPOINTS[j]["title"] in id_by_title]
            if cp.prerequisites != prereq_ids:
                cp.prerequisites = prereq_ids
        await db.commit()

        print(f"\n✅ 完成！项目 #{proj.id}: {PROJECT_NAME}")
        print(f"   闯关图: {len(cps)} 个 checkpoint")
        print(f"   打开前端 → 首页 → {PROJECT_NAME}")


if __name__ == "__main__":
    asyncio.run(seed())
