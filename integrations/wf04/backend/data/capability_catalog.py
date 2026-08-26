"""计算机信息技术专业群能力目录。

该目录为非正式接入方向提供可审查的参考路径。正式 Java 能力图仍由
``goal_graph.py`` 负责，目录不会把参考路径伪装成已验证课程标准。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


FORMAL_SUPPORT_LEVEL = "validated_graph"
REFERENCE_SUPPORT_LEVEL = "reference_catalog"


def _path(prefix: str, topics: tuple[tuple[str, str], ...]) -> list[dict[str, Any]]:
    """Build a deterministic dependency path from curated topic definitions."""

    nodes: list[dict[str, Any]] = []
    previous = ""
    for index, (slug, name) in enumerate(topics, start=1):
        node_key = f"{prefix}-{slug}"
        prerequisites = [previous] if previous else []
        nodes.append(
            {
                "node_key": node_key,
                "knowledge_point_name": name,
                "knowledge_type": "project" if index == len(topics) else "practice",
                "prerequisites": prerequisites,
                "goal_connection": f"{name}是完成该专业方向真实任务的第 {index} 个能力环节。",
                "learning_outcome": f"能够独立完成{name}对应的操作，并提交可检查产物。",
                "video_context_keywords": [name, name.replace("与", " ")],
            }
        )
        previous = node_key
    return nodes


_SOFTWARE_PATH = _path(
    "software",
    (
        ("foundation", "软件工程与开发环境基础"),
        ("requirements", "需求分析与验收规则"),
        ("frontend", "前端页面与交互实现"),
        ("backend", "后端接口与数据建模"),
        ("integration", "前后端联调与接口契约"),
        ("testing", "软件测试与缺陷管理"),
        ("delivery", "版本管理与持续交付"),
        ("project", "软件项目综合实战"),
    ),
)

_APPLICATION_PATH = _path(
    "application",
    (
        ("foundation", "计算机系统与办公环境基础"),
        ("os", "操作系统安装与配置"),
        ("hardware", "计算机硬件识别与维护"),
        ("network", "终端网络配置与排障"),
        ("database", "常用数据管理与备份"),
        ("security", "终端安全与权限管理"),
        ("service", "用户支持与运维记录"),
        ("project", "信息系统部署维护综合任务"),
    ),
)

_NETWORK_PATH = _path(
    "network",
    (
        ("foundation", "网络体系结构与设备认知"),
        ("ip-subnet", "IP 地址与子网规划"),
        ("switching", "交换、VLAN 与二层冗余"),
        ("routing", "静态路由与动态路由基础"),
        ("services", "DHCP、DNS 与常用网络服务"),
        ("security", "访问控制与网络安全基线"),
        ("automation", "网络自动化与配置核验"),
        ("troubleshooting", "网络故障定位与恢复"),
        ("project", "园区网络部署验收综合任务"),
    ),
)
# 综合任务必须显式依赖自动化和故障处理，避免退化成单线章节目录。
_NETWORK_PATH[-1]["prerequisites"] = ["network-automation", "network-troubleshooting"]

_BIG_DATA_PATH = _path(
    "bigdata",
    (
        ("foundation", "Linux、Python 与数据工程基础"),
        ("modeling", "数据建模与数据质量规则"),
        ("collection", "批量与流式数据采集"),
        ("storage", "分布式存储与数据湖基础"),
        ("spark", "Spark 计算模型与任务开发"),
        ("warehouse", "数据仓库分层与指标加工"),
        ("governance", "数据治理、安全与血缘"),
        ("project", "大数据工程综合交付"),
    ),
)

_AI_PATH = _path(
    "ai",
    (
        ("foundation", "Python、线性代数与概率基础"),
        ("data", "数据准备、标注与特征处理"),
        ("ml", "机器学习模型训练与评估"),
        ("deep-learning", "深度学习网络与训练流程"),
        ("evaluation", "误差分析与模型验证"),
        ("deployment", "模型服务化与推理部署"),
        ("governance", "人工智能安全与合规"),
        ("project", "人工智能应用综合项目"),
    ),
)


_PACKS: tuple[dict[str, Any], ...] = (
    {
        "pack_id": "PACK-COMPUTER-APPLICATION",
        "professional_id": "computer-application",
        "professional_name": "计算机应用技术",
        "professional_code": "510201",
        "title": "计算机应用与系统维护参考能力包",
        "support_level": REFERENCE_SUPPORT_LEVEL,
        "support_label": "参考能力目录",
        "content_status": "reference_ready",
        "content_notice": "需结合院校课程标准、设备环境与正式题库复核。",
        "keywords": ("计算机应用技术", "系统维护", "计算机维护", "信息系统维护"),
        "nodes": _APPLICATION_PATH,
    },
    {
        "pack_id": "PACK-COMPUTER-NETWORK",
        "professional_id": "computer-network",
        "professional_name": "计算机网络技术",
        "professional_code": "510202",
        "title": "计算机网络部署与运维参考能力包",
        "support_level": REFERENCE_SUPPORT_LEVEL,
        "support_label": "参考能力目录",
        "content_status": "reference_ready",
        "content_notice": "需补充真实设备拓扑、厂商命令与验收依据。",
        "keywords": ("计算机网络技术", "网络运维", "交换路由", "园区网络"),
        "nodes": _NETWORK_PATH,
    },
    {
        "pack_id": "PACK-JAVA-FORMAL",
        "professional_id": "software-technology",
        "professional_name": "软件技术",
        "professional_code": "510203",
        "title": "Java 面向对象正式能力图",
        "support_level": FORMAL_SUPPORT_LEVEL,
        "support_label": "正式能力图",
        "content_status": "validated",
        "content_notice": "正式内容由目标能力图和确定性测评链提供。",
        "keywords": ("Java 面向对象", "Java OOP"),
        "nodes": (),
    },
    {
        "pack_id": "PACK-SOFTWARE-ENGINEERING",
        "professional_id": "software-technology",
        "professional_name": "软件技术",
        "professional_code": "510203",
        "title": "软件开发与测试参考能力包",
        "support_level": REFERENCE_SUPPORT_LEVEL,
        "support_label": "参考能力目录",
        "content_status": "reference_ready",
        "content_notice": "需按具体技术栈补充来源、任务和测评题。",
        "keywords": ("软件技术", "前端开发", "软件测试", "软件工程"),
        "nodes": _SOFTWARE_PATH,
    },
    {
        "pack_id": "PACK-BIG-DATA",
        "professional_id": "big-data-technology",
        "professional_name": "大数据技术",
        "professional_code": "510206",
        "title": "大数据工程参考能力包",
        "support_level": REFERENCE_SUPPORT_LEVEL,
        "support_label": "参考能力目录",
        "content_status": "reference_ready",
        "content_notice": "需接入真实数据集、集群环境与数据质量标准。",
        "keywords": ("大数据技术", "Spark 数据工程", "大数据工程", "数据仓库"),
        "nodes": _BIG_DATA_PATH,
    },
    {
        "pack_id": "PACK-AI-APPLICATION",
        "professional_id": "ai-application",
        "professional_name": "人工智能技术应用",
        "professional_code": "510209",
        "title": "人工智能技术应用参考能力包",
        "support_level": REFERENCE_SUPPORT_LEVEL,
        "support_label": "参考能力目录",
        "content_status": "reference_ready",
        "content_notice": "需按应用场景补充数据、模型、算力和安全验收依据。",
        "keywords": ("人工智能技术应用", "机器学习", "模型训练", "人工智能应用"),
        "nodes": _AI_PATH,
    },
)


def is_formal_support_level(value: str) -> bool:
    return str(value or "").strip() == FORMAL_SUPPORT_LEVEL


def match_capability_pack(text: str) -> dict[str, Any] | None:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return None
    matches: list[tuple[int, int, dict[str, Any], list[str]]] = []
    for index, pack in enumerate(_PACKS):
        matched = [
            keyword
            for keyword in pack["keywords"]
            if str(keyword).lower() in normalized
        ]
        if matched:
            score = sum(len(keyword) for keyword in matched)
            matches.append((score, -index, pack, matched))
    if not matches:
        return None
    _score, _order, selected, matched_keywords = max(matches, key=lambda item: item[:2])
    result = deepcopy(selected)
    result["matched_keywords"] = matched_keywords
    return result


def reference_path_nodes(
    pack: dict[str, Any] | None,
    goal_name: str = "",
    target_outcome: str = "",
) -> list[dict[str, Any]]:
    if not pack or is_formal_support_level(str(pack.get("support_level") or "")):
        return []
    nodes = deepcopy(list(pack.get("nodes") or []))
    if goal_name:
        normalized_goal = goal_name.strip()
        for node in nodes:
            node["goal_connection"] = (
                f"{node['knowledge_point_name']}直接服务于学习目标“{normalized_goal}”，"
                "并为后续工作任务提供前置能力。"
            )
    if nodes and target_outcome:
        nodes[-1]["learning_outcome"] = f"完成并验收：{target_outcome.strip()}"
    return nodes


def public_capability_catalog() -> dict[str, Any]:
    programs: dict[str, dict[str, Any]] = {}
    for pack in _PACKS:
        code = str(pack["professional_code"])
        program = programs.setdefault(
            code,
            {
                "professional_id": pack["professional_id"],
                "professional_name": pack["professional_name"],
                "professional_code": code,
                "capability_packs": [],
            },
        )
        program["capability_packs"].append(
            {
                key: deepcopy(pack[key])
                for key in (
                    "pack_id",
                    "title",
                    "support_level",
                    "support_label",
                    "content_status",
                    "content_notice",
                )
            }
        )
    return {
        "status": "ok",
        "catalog_id": "computer-information-technology-cluster-v1",
        "programs": list(programs.values()),
    }
