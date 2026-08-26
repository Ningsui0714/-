# 概念考察设计研究札记

状态：研究中。本文件记录设计约束，不代表最终题型目录。

## 当前结论

1. 先定义细粒度学习目标，再明确需要观察到什么证据，随后设计能引出证据的任务和解释规则。题目的表面形式不能代替认知与证据设计。
2. 单选、多选、判断、代码推演只是响应形式。相同形式可以承载不同认知要求，不应按形式凑题量或推断掌握。
3. 形成性题目应尽量只检查少量明确概念，使错误能映射到可补救的知识缺口。一次答错只能形成待确认缺口，不能直接判定稳定误解。
4. 代码追踪是计算机学习中的一个特定构念。只有关卡目标需要追踪执行语义时才使用；执行器只能校验输出正确性，不能证明该题与学习目标对齐。
5. 干扰项若要代表“常见误解”，需要来自开放回答、访谈、历史作答或已验证研究。仅由模型生成的干扰项只能视为待验证假设。

## 首版实现边界

- 当前响应形式：`single`、`multi`、`judge`、`code_output`。
- 每题保存 `learning_target`、`evidence_claim`、`target_concepts`、`source_chunk_ids` 与 `response_format`。
- `code_output` 必须与来源中的代码内容相关，并通过执行器确定正确输出；旧数据中的 `wwpd`、`wwpp` 只做兼容读取。
- 后续应基于真实作答数据研究题族、干扰项质量、评分规则、迁移效度和不同辅助强度下的证据解释。

## 研究依据

- National Research Council, *Knowing What Students Know*: assessment triangle uses cognition, observation and interpretation, and warns that item format does not determine cognitive demand. https://www.nationalacademies.org/read/10019/chapter/9
- Basu, Rutstein, Tate, *Applying a Principled Approach to Develop and Use K-12 Computer Science Formative Assessments*: define learning target, evidence, task and evaluation before writing items. https://files.eric.ed.gov/fulltext/ED615769.pdf
- Nelson, Hu, Xie, Ko, *Towards validity for a formative assessment for language-specific program tracing skills*: formative use needs granular constructs and scoring that can guide remediation. https://faculty.washington.edu/ajko/papers/Nelson2019TracingValidity.pdf
- Caceffo et al., *Developing a Computer Science Concept Inventory for Introductory Programming*: diagnostic distractors require evidence from learner responses and instructor analysis. https://dl.acm.org/doi/10.1145/2839509.2844559
