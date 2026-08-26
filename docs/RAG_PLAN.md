# LearnFlow RAG 检索方案（待实现）

> 设计日期：2026-07-31
> 状态：已规划，待实现（Phase 3.5 → Phase 4 → 远期）

---

## 整体架构

```
用户提问 / 关卡主题
       ↓
┌─ Query 改写与拓展 ──────────────┐  Phase 3.5
│  • 纠错、补全、同义词扩展       │
│  • 中英文关键词拓展             │
│  • 按问题复杂度动态调整 top-k   │
└──────────────┬──────────────────┘
               ↓
┌─ 多路粗召回 (L1) ──────────────┐  Phase 4
│  • 向量检索 (embedding)        │
│  • 关键词检索 (BM25/全文)      │
│  • 结构化过滤 (文件路径/目录)  │
│  • 规则筛选 (可选)             │
└──────────────┬──────────────────┘
               ↓
┌─ 精排加权融合 (L2) ────────────┐  Phase 4
│  • 各路分数归一化              │
│  • 加权融合（可调权重）        │
│  • 可选：学习排序模型          │
└──────────────┬──────────────────┘
               ↓
┌─ 语义级多路合并 (L3) ──────────┐  远期
│  • 去重、反冗余                │
│  • 语义一致性比较              │
│  • 忠诚输出 top-k              │
└────────────────────────────────┘
               ↓
          top-k chunks
```

---

## Phase 3.5 — Query 改写 + 动态召回（2-3 小时）

### Query 改写器

```python
class QueryExpander:
    """展开用户查询为多路搜索词。"""

    # 领域同义词表（持续扩充）
    SYNONYMS = {
        "梯度下降": ["gradient descent", "gd", "参数更新", "最速下降"],
        "反向传播": ["backpropagation", "backprop", "bp", "链式法则"],
        "卷积": ["convolution", "cnn", "特征提取", "filter"],
        "损失函数": ["loss function", "代价函数", "目标函数", "objective"],
        "注意力": ["attention", "self-attention", "transformer", "缩放点积"],
        # ...
    }

    def expand(self, query: str) -> List[str]:
        keywords = extract_keywords(query)
        expanded = set(keywords)
        for kw in keywords:
            if kw in self.SYNONYMS:
                expanded.update(self.SYNONYMS[kw])
        return list(expanded)
```

### 动态 top-k

```python
def dynamic_top_k(query: str, base_k: int = 15) -> int:
    """
    按问题复杂度动态调整召回数量。
    - 简单事实/概念: k=8
    - 中等过程/推导: k=15
    - 复杂多跳/对比: k=25
    """
    complexity = estimate_complexity(query)
    # 关键词数量、是否含"为什么/对比/区别"等
    return {1: 8, 2: 15, 3: 25}.get(complexity, base_k)
```

---

## Phase 4 — embedding 向量检索（1-2 天）

### 方案对比

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| 本地 `gte-small` (ONNX) | 免费，隐私 | 质量中等，~100MB | ⭐⭐⭐ |
| API 嵌入（DeepSeek/OA） | 质量高，零部署 | 有成本，依赖网络 | ⭐⭐⭐⭐⭐ |
| 本地 `bge-m3` | 质量好，多语言 | ~2GB，mac 跑不动 | ⭐⭐ |

**推荐方案**：API 嵌入（复用现有 DeepSeek key）+ 本地缓存

### 存储设计

```python
class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    id = Column(Integer, primary_key=True)
    chunk_id = Column(Integer, ForeignKey("chunks.id"), unique=True)
    embedding = Column(JSON)  # List[float]
    model = Column(String(50))  # 来源模型
```

或者更轻量：`.npy` 文件 + Redis/mmap

### 多路融合（L1 → L2）

```python
def rank_chunks(query: str, chunks: List[Chunk]) -> List[ScoredChunk]:
    scores = []
    for chunk in chunks:
        vector_score = cosine_sim(query_emb, chunk.emb) * weight_vector
        keyword_score = bm25(query, chunk.content) * weight_keyword
        struct_score = file_path_match(query_kw, chunk.file) * weight_struct
        scores.append(ScoredChunk(
            chunk=chunk,
            score=vector_score + keyword_score + struct_score,
        ))
    return sorted(scores, key=lambda x: -x.score)[:top_k]
```

---

## 远期（暂时不实现）

- **学习排序模型 (LTR)**：需要人工标注数据，暂时没条件
- **图检索**：当前数据关系不足以支撑
- **规则筛选引擎**：可选组件，需要时再加
- **语义级多路合并 (L3)**：当前多路召回的重复率低，收益不大

---

## 与现有系统集成

```
现有检索流                          RAG 增强后
──────────────────────────────────
_retrieve_relevant_chunks()   →   query_expand()
  │                                  │
  ├─ Level 1: 文件路径匹配            ├─ Level 1: Query Embedding → 向量检索
  ├─ Level 2: headings/topic_hints    ├─ Level 1: Query 关键词 → BM25
  ├─ Level 3: 全文关键词              ├─ Level 2: 文件路径 + heading 匹配 (L2 加权)
  └─ top-15                           └─ Level 3: 加权融合 → 动态 top-k
```

改动范围：只在 `lecture_agent.py` 的 `_retrieve_relevant_chunks` 方法内改造，不涉及系统架构变更。

---

## 后续考虑

- 支持对 checkpoint 的 `assigned_chunks` 做预索引，减少实时计算
- 缓存 query embedding 避免重复请求
- 讲义生成完成后，用户选中的追问内容可作为反馈数据改进检索
