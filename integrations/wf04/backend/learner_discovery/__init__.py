"""Learner State Discovery 模块（backend/learner_discovery）。

实现《LEARNER_STATE_DISCOVERY_AGENT_BRIEF.md》描述的"学习信息快速获取模块"：
- EvidenceEvent -> five_kernel_reducer -> KernelMutation -> KernelState -> MemoryGraph
- 权威链与边界见 docs/ARCHITECTURE_AUTHORITY.md
- 事件/能力/工具/工作台注册表见 registry.py

设计取向（对应任务书第 17 节）：
- 优先形成可运行证据闭环：每个有效交互立刻产生事件 -> Reducer -> 投影，下一轮基于新投影决策；
- 判题确定性：选择题用确定性判题；开放题/理由只作为候选观察，不强行二分；
- 幂等：client_event_id 同一 learner 内唯一，重复提交不重复计分。
"""

from backend.learner_discovery.models import (
    EvidenceEvent,
    KernelMutation,
    KernelProjection,
    NextInteraction,
    Observation,
    Scope,
)
from backend.learner_discovery.registry import (
    CAPABILITIES,
    EVENT_REGISTRY,
    PRODUCT_SKILLS,
    TOOLS,
    WORKBENCHES,
)
from backend.learner_discovery.session import DiscoveryService

__all__ = [
    "DiscoveryService",
    "EvidenceEvent",
    "KernelMutation",
    "KernelProjection",
    "NextInteraction",
    "Observation",
    "Scope",
    "CAPABILITIES",
    "EVENT_REGISTRY",
    "PRODUCT_SKILLS",
    "TOOLS",
    "WORKBENCHES",
]
