# BushfireReadyGPT 简历项目说明（v0.3.0）

- 最后同步：2026-08-22
- 项目地址：https://github.com/shuxiachai/BushfireReadyGPT
- 项目性质：个人作品集项目，基于 Apache-2.0 开源项目 WildfireGPT 进行澳洲场景重构与持续工程化

## 简历推荐版本（中文）

### 项目名称

**BushfireReadyGPT｜本地 RAG 多智能体山火准备报告系统**

### 技术栈

Python、Streamlit、Ollama、Qwen2.5-7B、EmbeddingGemma、Qdrant、BM25、RRF、
ABS/ASGS、ReportLab、python-docx、Pytest、Playwright、GitHub Actions

### 项目描述

面向澳大利亚议会、学校和社区的本地优先山火准备报告 MVP。系统将表单输入、
ABS/ASGS 社区数据、官方知识检索、多智能体分析、人工复核与可审计导出串联为一条
完整工作流；定位为准备规划和报告草拟工具，不处理实时火情、撤离命令或生命安全决策。

### 核心工作与结果

- 主导将原开源聊天助手重构为澳洲山火准备场景的表单式工作流，拆分 8 个可解释的确定性 Agent，并通过本地 Ollama/Qwen2.5 完成无云端密钥的报告生成；结构门禁失败时最多执行 2 次无状态修复。
- 实现传统混合 RAG：使用 EmbeddingGemma + Qdrant 稠密检索、BM25 与加权 RRF，加入行政区过滤、来源多样性限制、索引哈希校验、提示注入隔离和确定性拒答；9 个官方页面覆盖澳洲 8 个州/领地，84 题评测达到 Recall@5 `97.06%`、MRR `0.8922`、不可回答准确率 `100%`。
- 构建证据与治理链路：接入 ABS/ASGS 地理及社区数据，设计 O1/P2/R3/A4/U0 证据分级，展示数据年份、来源年龄和地理匹配质量；实现报告版本、人工复核重置、哈希链审计、递归修订谱系及 Markdown/PDF/DOCX/试点包导出。
- 完善交付与质量保障：合并 Windows 安装和启动检查，自动复用健康的 Python 依赖、Ollama 模型与 RAG 索引；建立 Python 3.11/3.13、Windows 启动和 Chromium E2E 的 CI，`209` 项测试通过、覆盖率 `85.36%`，8 个真实模型案例覆盖全部 6 类业务场景及安全/降级边界并通过发布门禁。

## 一页简历压缩版本

如果版面只允许 3 条，可使用：

- 将 Apache-2.0 开源聊天助手重构为澳洲山火准备报告 MVP，设计 8 个确定性 Agent + 本地 Ollama/Qwen2.5 生成链路，支持人工复核、版本化报告和 Markdown/PDF/DOCX 导出。
- 实现 EmbeddingGemma、Qdrant、BM25 与加权 RRF 组成的本地混合 RAG，覆盖澳洲 8 州/领地的 9 个官方来源；84 题评测 Recall@5 `97.06%`、MRR `0.8922`、不可回答准确率 `100%`。
- 建立数据新鲜度/地理匹配告警、证据分级与哈希链审计；通过 `209` 项测试、`85.36%` 覆盖率、4 组跨平台 CI 和 8 场景真实模型回归验证关键流程。

## English Resume Version

### BushfireReadyGPT — Local RAG Multi-Agent Bushfire Preparedness System

- Re-engineered an Apache-2.0 open-source chatbot into an Australian bushfire-preparedness reporting MVP, combining eight deterministic agents with local Ollama/Qwen2.5 generation, human review, versioned reports and Markdown/PDF/DOCX exports.
- Built a local hybrid RAG pipeline with EmbeddingGemma, Qdrant dense retrieval, BM25 and weighted reciprocal-rank fusion; added jurisdiction filtering, integrity validation and deterministic abstention across nine official sources covering all eight Australian states and territories.
- Achieved `97.06%` Recall@5, `0.8922` MRR and `100%` unanswerable accuracy on an 84-query retrieval benchmark; all eight real-model report cases passed structural, attribution, safety, contamination and degradation gates.
- Implemented evidence provenance, data-currency/geographic-match warnings and hash-linked audit lineage; validated the system with `209` automated tests, `85.36%` source coverage and CI across Python 3.11/3.13, Windows startup and Chromium E2E.

## 30 秒面试介绍

这个项目解决的是“如何让本地大模型生成的准备报告可追溯、可复核，而不只是输出一段文本”。
我把原来的聊天助手重构成表单驱动的多 Agent 工作流，用传统混合 RAG 检索澳洲官方资料，
再把 ABS/ASGS 数据、来源归属、数据新鲜度、人工复核和哈希链审计写入同一份治理报告。
项目最难的部分是同时控制本地模型上下文、RAG 归因和跨平台导出一致性，因此我增加了
结构修复门禁、真实模型场景评测和 Windows/Chromium CI。当前版本适合秋招展示和受控试点，
但不会把工程测试描述成真实政府或应急业务验证。

## 可展开的面试技术点

1. **为什么使用传统 RAG**：官方来源需要可更新、可定位和可评测，不能只依赖模型参数记忆。
2. **为什么混合检索**：稠密检索处理语义表达，BM25 保留专有名词和精确措辞，RRF 避免直接比较不同分值空间。
3. **为什么 Agent 不是多个 LLM 调用**：8 个 Agent 是职责清晰的确定性组件，仅报告叙事使用受治理的模型调用，以降低延迟、成本和不可重复性。
4. **如何避免 RAG 幻觉**：验证索引/语料哈希，限制行政区和来源占比，要求报告明确引用检索来源；无可靠结果、实时请求或越界问题时确定性拒答。
5. **如何保证修订可审计**：每次修订生成新 ID/版本，重建确定性证据并清空旧审批，通过哈希链绑定报告、复核记录、数据/许可快照和父版本。
6. **如何验证生成质量**：结构门禁与主题/污染/安全规则配合真实 Ollama 场景集；工程层再用单元、集成、Streamlit AppTest、Chromium E2E 和跨平台 CI 验证。

## 表述边界

- 外部 3–5 人受控试点尚未执行，不写“已完成用户验证”或“政府采用”。
- `97.06%` Recall@5 和其他指标只对应仓库中的 84 题回归集，不代表生产准确率。
- 8 个 Agent 是确定性流水线组件，不描述为 8 个独立自主的大模型智能体。
- 项目不预测山火，不提供实时预警、撤离路线、禁火令或生命安全决策。
- 更准确的定位是“政府试点级 MVP / 作品集原型”，不是可直接采购的生产系统。
