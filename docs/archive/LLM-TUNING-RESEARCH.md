# LLM 调参决策层调研（LLM-TUNING-RESEARCH）

> **Archived 2026-08-13.** This survey does **not** govern the product. Live design is `docs/ADR-002-ENGINEER-SESSION-MODEL.md`.
> Kept as a literature notebook (OPRO / LLAMBO / Reflexion and similar, 2023–2025). Its conclusion that ADR-001 needed no change is itself superseded.

- 调研日期：2026-08-11 ～ 2026-08-12（时间盒 6h 内完成）
- 调研人：执行者（pi agent，新会话，按任务书 2026-08-11）
- 范围：为 hfss-mcp 的「LLM 主动分析—反思—调参」决策层提供**方法与设计原则**依据；不做 LLM 选型。
- 约束基线：ADR-001（LLM 管意图/目标/搜索空间/策略；数值内循环归确定性优化器）。文献与之相冲处见 §6。
- 证据分级：**顶会**（ICLR/NeurIPS/AAAI/ICCAD/Nature 等同行评审）、**官方实现**（作者 repo / OptunaHub 官方 registry / dblp）、**预印本**（arXiv，未评审）、**博客**（公司/个人页面）、**推断**（本调研基于上述事实的推理）。
- 每条结论格式：来源（arXiv 号或 URL）+ 发表日期 + 一句话验证方式。

---

## 0. 结论先行：设计原则清单（15 条）

| # | 原则 | 来源 | 日期 | 证据强度 | 验证方式 |
|---|------|------|------|----------|----------|
| P1 | **轨迹序列化**：把（解, 分数）对**按分数升序**放进 meta-prompt，只保留 top-N（N=20）；升序优于降序/随机（recency bias） | OPRO, arXiv:2309.03409 | 2023-09-07 (v1), ICLR 2024 | 顶会 | 打开 arxiv.org/html/2309.03409v3 搜 "sorted in the ascending order" 与 §5.3 "The order of the previous instructions" |
| P2 | **每步批量采样**：每步生成多个候选（OPRO 默认 8 个，消融 1/2/4/8/16 中 8 最优）；一次性生成 50 个远差于迭代式 | OPRO, arXiv:2309.03409 | 同上 | 顶会 | 同上，§5.1 "prompt the optimizer LLM with the meta-prompt 8 times"、§5.3 "The number of generated instructions per step"、"Comparison with one-step instruction generation" |
| P3 | **温度=探索/利用旋钮**：消融 {0, 0.5, 1.0, 1.5, 2.0}，1.0 最优；低温重复同一解（缺探索），高温忽略轨迹（缺利用） | OPRO, arXiv:2309.03409 | 同上 | 顶会 | 同上，§5.3 "Diversity per step" |
| P4 | **失败观测的用法**：低分/失败样本要参与学习但要受控——OPRO 只留 top-20 防低质轨迹扰动上下文；ExpeL 用同任务成败对对比提炼；OptunaHub 版 LLAMBO 显式加"已观测值不得再推荐" | OPRO §2.3；ExpeL arXiv:2308.10144 §4.2；hub.optuna.org/samplers/llambo | 2023-09 / 2023-08 / 2025-03 | 顶会+顶会+官方实现 | OPRO HTML 搜 "drastically affected by low-quality solutions"；ExpeL HTML 搜 "success/failure pairs"；OptunaHub 页搜 "must not be recommended again" |
| P5 | **LLM 单独逐点数值优化不可靠**：缺数值理解、维度升高性能一致下降、对输入平移/提示词格式敏感、成本远高于传统算法；可靠用法是把 LLM 放进确定性框架做候选生成器/先验/解释层 | Huang et al., "Evaluation of Large Language Models as Solution Generators in Complex Optimization", IEEE Computational Intelligence Magazine vol.20（dblp: journals/cim/cim20；Xplore doc 11200056）；OPRO 自身 Limitations 与附录 A | 2025（CIM vol.20）/ 2023-09 | 顶刊+顶会 | dblp.org/db/journals/cim/cim20.html 搜 "Huang" 得条目；IEEE innovate.ieee.org 搜 "Testing Large Language Models for Optimization"（2025-10-25 解读文）；OPRO HTML 搜 "Limitations." 与附录 A |
| P6 | **LLM warmstart**：零样本用领域知识生成初始点/可行域，在观测稀疏的早期阶段收益最大 | LLAMBO, arXiv:2402.03921 (ICLR'24)；ADO-LLM, arXiv:2406.18770 (ICCAD'24) | 2024-02-06 / 2024-06-26 | 顶会+顶会 | arxiv.org/abs/2402.03921 摘要 "effective at zero-shot warmstarting... especially in the early stages"；abs/2406.18770 摘要 "rapidly generate viable design points" |
| P7 | **LLM 代理/采样模块必须即插即用、可降级**：LLAMBO 按设计模块化；OptunaHub 官方实现遇错自动回退随机采样，并把数值参数与类别参数分流 | LLAMBO 摘要 "modular by design"；hub.optuna.org/samplers/llambo（"Gracefully falls back to random sampling"） | 2024-02 / 2025-03-28（registry 更新） | 顶会+官方实现 | abs/2402.03921 摘要；OptunaHub 页 "Thread Safety and Error Handling" 节 |
| P8 | **反思=文本，存情景记忆，窗口 1–3 条**：Reflexion 把自评反馈转成自然语言反思存入 episodic memory buffer，实际上限 Ω=1–3 条；ALFWorld +22%、HotpotQA +20%、HumanEval pass@1 91%（GPT-4 单发 80%） | Reflexion, arXiv:2303.11366 (NeurIPS'23) | 2023-03-20 (v1) | 顶会 | arxiv.org/html/2303.11366v4 搜 "usually set to 1-3" 与 Table 1 |
| P9 | **反思必须挂在可信评估信号上**：Reflexion 消融表明去掉自生成测试后只剩盲目试错，反思反而做不出改进（52% < 基线 60%）；评估器可以是启发式/单元测试/LLM 判官 | Reflexion, arXiv:2303.11366, §4.3 Ablation | 同上 | 顶会 | 同上，Table 3 "Self-reflection omission" 行与正文解读 |
| P10 | **跨运行经验要提炼成带投票的 insight 池，而不是堆原始反思**：ExpeL 用 ADD/EDIT/UPVOTE/DOWNVOTE 维护 insight 集合（新 insight 初始票 2，票 0 删除）；消融证明把原始反思直接喂给提炼环节**降低**性能（29.0 vs 39.0） | ExpeL, arXiv:2308.10144 (AAAI'24) | 2023-08-20 (v1) | 顶会 | arxiv.org/html/2308.10144v3 搜 "DOWNVOTE"；Table 3 "Insights with reflections" 行 |
| P11 | **经验检索按任务相似度**：ExpeL 用 Faiss+mpnet 按任务相似度取 top-k 成功轨迹最优；随机采样显著掉点 | ExpeL, arXiv:2308.10144, §4.2/§5.6 | 同上 | 顶会 | 同上，搜 "all-mpnet-base-v2" 与 Table 3 下半 |
| P12 | **只有被验证的知识才进长期库**：Voyager 技能库只收通过 self-verification 的程序；消融显示去掉自验证发现量 −73%；4 轮不收敛就换任务（防死磕） | Voyager, arXiv:2305.16291 | 2023-05-25 (v1) | 顶会（TMLR/NeurIPS 系发表；此处按 arXiv+官方站） | arxiv.org/html/2305.16291v2 搜 "commit the program to the skill library"、"−73%"、"stuck after 4 rounds" |
| P13 | **≤10 trial 极小预算下 LLM+BO 混合优于单一**：LLM 出语义先验（warmstart/候选/失败解读），代理模型+采集函数出数值利用；LLAMBO 在观测稀疏早期增益显著，ADO-LLM 在模拟 sizing 实测改进效率 | LLAMBO arXiv:2402.03921；ADO-LLM arXiv:2406.18770（"the first work integrating LLMs with Bayesian Optimization for analog design optimization"） | 2024-02 / 2024-06 | 顶会+顶会 | 两篇 abs 页；ADO-LLM 亦见 dl.acm.org/doi/10.1145/3676536.3676816（ICCAD'24） |
| P14 | **候选求解失败 = 策略数据**：消耗预算、弃置该移动、记录并继续，不中断 run；本仓库 probe 实测（t5_fy 求解失败后容错恢复，最终 PASS）与 Voyager「卡住就换任务」、RFAmpDesigner「资源分配中间件降维」同构 | 本仓库 runs/run_probe_main/report.json（2026-07-29 实录）；Voyager §2.3；RFAmpDesigner arXiv:2605.10093 | 2026-07-29 / 2023-05 / 2026-05 | 仓库实测+顶会+预印本 | report.json 的 failed_trials 与 status=PASS；Voyager HTML 搜 "4 rounds"；arxiv.org/abs/2605.10093 摘要 |
| P15 | **领域知识走 prompt/任务描述通道，别指望模型内部知识**：OptunaHub LLAMBO 提供 custom_task_description；ADO-LLM 用 design instructions 注入；RFAmpDesigner 明确论证 RF sizing 靠 LLM 内部知识不够；WiseEDA 靠 prompt engineering 注入 RF 知识 | hub.optuna.org/samplers/llambo；ADO-LLM；RFAmpDesigner arXiv:2605.10093；WiseEDA (ScienceDirect S1879239125000566) | 2025-03 / 2024-06 / 2026-05 / 2025 | 官方实现+顶会+预印本+期刊 | OptunaHub 页搜 "custom_task_description"；arxiv.org/abs/2605.10093 引言三挑战；sciencedirect.com 搜 "WiseEDA: LLMs in RF Circuit Design" |

---

## 1. 问题 1：LLM-as-optimizer 设计原则

### 1.1 优化轨迹怎么序列化喂给模型（OPRO 的做法）

OPRO（Optimization by PROmpting）的 meta-prompt 由两部分组成（arXiv:2309.03409，ICLR 2024）：

1. **优化问题描述**：目标与约束的自然语言说明（meta-instruction，如"生成一条准确率更高的新指令"），可加非正式正则（"解要简洁"）；prompt 优化场景还带 3 个随机抽的任务样例（消融：3 个够用，10 个不更好反而稀释轨迹）。
2. **优化轨迹**：历史（解, 分数）对，**按分数升序排列**，只保留**最好的 20 条**（受上下文长度约束）。数值优化（线性回归 w,b）同样是"历史最优 20 对 + 排序分数"。

关键实证（均出自论文消融，§5.3）：
- 升序 > 降序 > 随机：假设是 LLM 对 prompt 末端更敏感（recency bias）。
- 显示分数 > 只显示顺序：分数帮模型理解质量差异（默认整数化；分 20 桶更差）。
- **迭代远胜一步到位**：一次性生成 50 条指令显著差于每步 8 条的迭代优化（GSM8K：64.4 vs 78.2 训练准确率 @第 5 步）。
- 稳定性设计：低质轨迹会剧烈扰动 in-context 输出（优化初期尤甚）→ 每步多采样（8 个）+ 只留 top-20。

### 1.2 meta-prompt 结构要点（可迁移到调参 Skill）

- 任务描述（含变量语义、指标定义、约束）→ 对应我们的 manifest 白名单+指标规格的文本化。
- 轨迹（参数向量, S11 指标）升序保留 top-N → 对应 trial journal 的摘要投影。
- 输出格式强约束（OPRO 要求方括号包裹新解）→ 对应"完整参数向量 JSON"结构化输出（hfss-mcp 的 trial_start 本就要求完整向量）。

### 1.3 温度与采样数

- 优化器温度 1.0（消融 0/0.5/1.0/1.5/2.0 中最优）；评分/执行侧用温度 0（贪心）。
- 每步 8 个候选（1/2/4/8/16 消融）——注意 OPRO 的"评估"是廉价的（scorer LLM 推理）；HFSS 单次求解 ~346s，**每步候选数必须降到 1–2，把预算花在"步数×反思"上**（这是本场景与 OPRO 的关键差异，属于推断，见 §5）。
- Voyager 全部温度 0，只有课程生成用 0.1 鼓励多样性（arXiv:2305.16291 §3.1）。

### 1.4 失败观测怎么利用

四条路线（都有出处）：
1. OPRO：失败/低分解留在轨迹里但只保留 top-N，防止污染上下文（§2.3）。
2. Reflexion：失败→自评信号→自然语言反思→注入下一次尝试（arXiv:2303.11366）。
3. ExpeL：同任务**成功/失败轨迹对**对比提炼 insight（arXiv:2308.10144 §4.2）。
4. OptunaHub LLAMBO：工程化防重复——已观测值显式列入"不得再推荐"清单，并防止 LLM 模仿 few-shot 里随机采样的分布（hub.optuna.org/samplers/llambo）。

本仓库已有的失败观测实例：run_probe_main 的 t5_fy（候选区域求解失败，容错=消耗预算+弃置+继续，最终 PASS）——这正是第 4 类用法的数据基础。

### 1.5 已公开的失败模式（领导抽查重点）

1. **OPRO 自述（附录 A，4 类）**：① 幻觉计算值（"f(5,3)=15"而真实不是）；② 无视"给一个与上文都不同的新解"的指令、重复生成已有解；③ 黑盒优化卡在非全局非局部最优点（上下文解共享某坐标或方向相反时）；④ 崎岖地形（Rosenbrock）卡在 (0,0) 附近。——验证：arxiv.org/html/2309.03409v3 附录 A "Some Failure Cases"（p.24）。
2. **OPRO 自述（Limitations）**：上下文窗口装不下高维问题；地形太崎岖时提不出正确下降方向；TSP n≥20 后 farthest insertion 启发式优于所有 LLM，n=50 无 LLM 找到最优（Table 3）。——验证：同上 §3.2 "Limitations."。
3. **IEEE CIM 2025 系统评测**（Huang, Wu, Zhou, Wu, Feng, Cheng, Tan）：LLM 不理解字符串数值（精度加多反而更差）；维度指数增长时性能一致下降；输入平移导致性能剧烈波动；强依赖 prompt 结构；探索/利用平衡落后传统算法、计算成本显著更高；"当前乐观结果多来自小规模问题或最优解靠近特殊值"；**有效模式是 LLM 在遗传算法框架里只负责生成个体**。——验证：dblp.org/db/journals/cim/cim20.html 搜 "Evaluation of Large Language Models as Solution Generators"；IEEE Xplore document 11200056；IEEE innovate 解读文（2025-10-25）。
4. **Reflexion 自述**：WebShop 上 4 次试验无反思收益即放弃——需要大多样性探索的局部最优逃不出去；自评能力随模型强弱差距大（HotpotQA：GPT-4 0.51 vs GPT-3.5 0.38）。——验证：arxiv.org/html/2303.11366v4 附录 B.1 与 Table 5。
5. **Voyager 自述**：课程会幻觉不存在的物品；代码会调用不存在的 API；self-verification 也会误判。——验证：arxiv.org/html/2305.16291v2 §4 Limitations。

---

## 2. 问题 2：反思与经验机制（Reflexion / ExpeL / Voyager）

### 2.1 三者机制对照（全部来自原文核对）

| 维度 | Reflexion（arXiv:2303.11366，2023-03-20，NeurIPS'23） | ExpeL（arXiv:2308.10144，2023-08-20，AAAI'24） | Voyager（arXiv:2305.16291，2023-05-25） |
|---|---|---|---|
| 反思存哪 | 情景记忆 buffer（episodic memory，长期记忆=反思文本；短期=当前轨迹），滑窗上限 Ω=1–3 条（决策任务 3 条、编程任务 1 条） | 两级：①经验池（成功/失败轨迹，Faiss 向量库+mpnet 嵌入）②insight 池（自然语言规则，带投票计数） | 技能库（可执行代码为值，代码描述嵌入为键，向量库；检索 top-5） |
| 何时触发 | 评估器判 fail 后：Self-Reflection 模型读（轨迹,奖励）生成反思→注入下一 trial；直到 pass 或达最大 trial（HotpotQA 连败 3 次止） | 训练阶段批量：先 Reflexion 式收集（每任务最多 Z 次重试），再对成败对与成功列表批量提炼；推理阶段单发、不重试 | 每轮代码执行后：环境反馈+执行错误+自验证批评注入下一轮；自验证通过才入库；4 轮不过就换任务 |
| 如何防重复犯错 | 反思文本显式给出"下次应做的不同动作"，直接进下一 trial 的上下文 | insight 投票机制（ADD/EDIT/UPVOTE/DOWNVOTE，新 insight 初始 2 票，0 票删除）+ 按任务相似度检索最相关的成功经验做 few-shot | 只存**验证通过**的技能；检索复用旧技能避免重写；失败任务记录在案，课程稍后再试 |
| 关键消融证据 | 去掉测试生成的盲目反思 52%<基线 60%；反思+测试=68%（HumanEval-Rust 最难 50 题） | 往提炼里掺原始反思反而掉点（29.0 vs 39.0）；LLM 学的 insight > 手写（39 vs 32）；任务相似度检索 > 随机 | 去掉自验证发现量 −73%；去掉课程 −93%；去掉技能库后期平台化 |

### 2.2 对「单次 trial 4–6 分钟」昂贵场景的适用性判断

- **反思本身几乎免费**（一次 LLM 调用），三者都适用；贵的是**为反思买数据的重试**。
- Reflexion 的**任务内多次重试**在本仓库不划算：6 trial 预算 ≈ 35 分钟墙钟，同一点重试最多留 1 次；Reflexion 的正确用法是把反思挂在 **run 级**（trial 失败后反思一次、修正后续策略），而不是 trial 级循环。其"评估器"在我们这里天然是结构化的（thresholds_met、error code、S11 频点漂移），比 ALFWorld 的启发式判停更可信（P9 的前提满足）。
- ExpeL 的**跨任务提炼**与 benchmark 的多 case 演进天然匹配：每跑完一个 case（或一次 run），把成败对喂给提炼环节，产出"S11_min 频点高于目标频 → 增大 xx 类尺寸"这类可复用 insight；insight 池放仓库全局（不进 case 目录、不碰答案册）。注意其反面教训：**原始反思不能直接入池**（幻觉会污染，消融 −10 个点）。
- Voyager 的技能库映射到本仓库 = **策略即代码/策略即参数化模板**（如"坐标下降探针""频点回拉规则"）；入库前必须有验证门——我们的验证门就是 benchmark 的 PASS/FAIL 判定（P12）。

---

## 3. 问题 3：≤10 trial 下 LLM 与 BO/代理模型的分工

### 3.1 LLAMBO（arXiv:2402.03921，ICLR'24）三件套与可移植性

LLAMBO 把 BO 问题自然语言化，LLM 在上下文内（不微调）承担三个**可独立拆装**的角色（摘要自述 "modular by design"；官方 repo github.com/tennisonliu/LLAMBO，实验用 gpt-3.5-turbo）：

1. **Warmstart**（零样本）：用问题的自然语言描述让 LLM 提初始候选。→ **可移植**：不依赖历史，对 ≤10 trial 最值——第 1–2 个 trial 就能带上天线物理先验（例如"S11_min 频点偏高 → 谐振结构偏小"类常识）。
2. **Candidate sampling**：以历史观测+问题描述为条件让 LLM 批量提候选点（论文配 Thompson-sampling 式采集）。→ **有条件可移植**：需要 ≥2–3 个观测后才有意义；OptunaHub 官方实现默认 num_candidates=10、num_prompt_variants=2（两套 few-shot 模板增多样性）。
3. **Surrogate**（LLM 当代理模型）：生成式（判"是否 top-k%"）或判别式（直接吐性能数值）。→ **谨慎移植**：5 变量、≤10 个样本时，经典 GP/RBF 代理更稳；LLM 代理的价值在"观测极稀疏+有强领域语义"时（论文自述 "especially in the early stages of search when observations are sparse"）。OptunaHub 实现里判别式还带 bootstrapping/recalibration 选项来稳预测。

**Optuna 集成（已核实，官方 registry）**：OptunaHub 收录 `samplers/llambo`——LLAMBOSampler（作者含原论文作者 Tennison Liu 等；最后更新 2025-03-28；验证 Optuna 4.1.0；MIT）。关键工程细节（都可当落地参考）：先 n_initial_samples=5 个随机点再进 LLM 引导；类别参数交给随机采样；数值参数按类型格式化（float 保小数位、int 禁小数）；"已观测值不得再推荐"防重复；限流器；出错自动回退随机采样；成本估算 n_trials=30 约 $0.05–0.10（GPT-4o-mini，2025-03 价）——**相对一次 346s 的 HFSS 求解，LLM 调用成本可忽略**。验证：hub.optuna.org/samplers/llambo。

### 3.2 模拟电路 sizing 的 LLM+BO 工作

- **ADO-LLM（查证存在）**：Yuxuan Yin, Yu Wang, Boxun Xu, Peng Li，"ADO-LLM: Analog Design Bayesian Optimization with In-Context Learning of Large Language Models"，arXiv:2406.18770（v1 2024-06-26，v2 2025-04-03），**ICCAD 2024**（dl.acm.org/doi/10.1145/3676536.3676816；arXiv 页有 Journal reference 与 related DOI 双证据）。自述"the first work integrating LLMs with Bayesian Optimization for analog design optimization"。分工：LLM 以电路定义+设计规格+设计指令为初始化，用领域知识**快速生成可行初始设计点**，补 BO 代理在有限覆盖下找高价值区域的低效；反过来，BO 迭代采样的结果成为 LLM 的高质量示范，BO 的探索多样性防 LLM 重复建议。两类模拟电路实测改进设计效率与效果。验证：arxiv.org/abs/2406.18770（页面含 ICCAD 期刊引用字段）。
- **配套证据（同域，说明这是活跃且收敛的方向）**：
  - "LLM-based AI Agent for Sizing of Analog and Mixed Signal Circuit…"，arXiv:2504.11497（2025-04）：LLM agent+外部仿真器+数据分析函数做 AMS sizing；对比多家 LLM（Claude 3.5 Sonnet 成功率最高、迭代最少、方差最小，2024-09 实测）。预印本。
  - WiseEDA（ScienceDirect，2025）：RFIC 设计中 LLM 负责拓扑选择+用 prompt 工程注入知识，PSO 做网表数值优化——又是"LLM 意图层+数值优化器内循环"。
  - RFAmpDesigner，arXiv:2605.10093（2026-05，预印本）：明确论证三点——参数空间高维强耦合、数值知识无法编码进语言、已有设计管线不该推倒重来——因此用"工具中间件把电路优化抽象为资源分配"降维，LLM 只做调度。与 ADR-001 同构（§6）。

### 3.3 ≤10 trial 的分工结论

- 数值内循环（在给定搜索空间内选下一个数值点）：交给 BO/代理/采集函数（hfss-mcp 的 run_optimizer 插槽），理由=P5/P13。
- LLM 负责：①warmstart 初始点与初始搜索空间（P6）；②每次 trial 后的语义解读（频点漂移方向→变量假设）；③失败候选的区域排除（P4）；④搜索空间/策略变更建议（经服务端裁决后生效，ADR-001）。
- 预算分配建议（推断）：6 trial ≈ 1 baseline + 1 warmstart 点（LLM 先验）+ 3–4 个 BO/规则点；LLM 在每步只做"读结果、改假设、批/否候选方向"，不直接吐裸数值点（除非 warmstart）。

---

## 4. 问题 4：领域先例盘点（2023–2026，EM/天线/RF/微波）

### 4.1 直接结论

**LLM/agent 直接驱动 HFSS（或同级全波 EM 求解器）做参数调优闭环的公开发表 = 空白**（检索式与日期见 §8）。最接近的三样东西：

1. **LADS / LEAM（antenna + LLM + EM 软件，但没闭环调优）**："Large Language Model-Based Intelligent Antenna Design System"，arXiv:2504.18271（2025-04-25），Tao Wu, Kexue Fu, Qiang Hua, Xinxin Liu, Bo Liu。自述"the first LLM-based antenna modeling tool"：LLM 工具链把文本/图片描述变成 CST Microwave Studio 宏（建模），再**配置并运行 SB-SADEA 优化器**（代理辅助进化，非 LLM 数值优化）完成参数优化；HFSS / MATLAB Antenna Toolbox 支持列为 future work。→ 意义：证明"LLM 建模/意图 + 数值优化器调参"在天线域已有先行者，且与我们架构同构；但它不做"已有失配工程的调参恢复"，也不是 HFSS。预印本；代码 github.com/TaoWu974/LEAM。验证：arxiv.org/abs/2504.18271 与 HTML 页。
2. **Atlas RF Studio（Arena Physica，工业产品 beta）**："agentic workflows to generate, simulate, and iterate on candidate designs" 的 AI 逆向 RF 设计沙箱，明确把"猜—仿真—调—重复"作为要自动化的对象。→ 证据强度：**公司发布页（博客级）**，无论文细节；只作产业信号引用。验证：arenaphysica.com/publications/rf-studio。
3. **FAS 视觉论文**："Large Language Model Empowered Design of Fluid Antenna Systems…"，arXiv:2506.14288（2025-06-17）：LLM 用于流体天线系统的端口选择/预编码组合优化（通信系统级，非 EM 仿真）。预印本，仅作"天线域 LLM 渗透中"的旁证。

另注：Ansys 官方 `ansys/pyaedt-mcp` 是 HFSS+LLM 的**交互式助手**（无策略层/无状态机），本仓库 ADR-001（2026-07-20 复评 main@eb2fd03）已详析，属"最近的 HFSS-LLM 工件"，不在 2023–2026 研究先例之列。

### 4.2 最邻近领域的可迁移点（与"领域先例"严格分开论证）

**A. 模拟/RF 电路 sizing（最可迁移，同为"昂贵仿真+少数连续参数+S 参数/性能指标"）**
- ADO-LLM（ICCAD'24，见 §3.2）：LLM warmstart + BO 内循环的完整可行性证据。
- WiseEDA（2025，期刊）：LLM 拓扑选择+知识注入，PSO 数值优化。
- RFAmpDesigner（arXiv:2605.10093，2026-05）、RF-Agent（arXiv:2607.18772，2026-07，教科书知识蒸馏+SFT/RAG 基准）、MenTeR（arXiv:2505.22990，2025-05，端到端 RF/analog 网表多智能体流水线；后经 CircuitLM arXiv:2601.04505 的引用列表见到，未单独核原文，标注为**二手**）、AMS sizing agent（arXiv:2504.11497，2025-04）。
- 可迁移点：领域知识注入通道（prompt/中间件/蒸馏数据集）、"LLM 不直接碰数值内循环"的一致性结论、样本效率是核心指标。

**B. 光子逆设计（同为麦克斯韦方程正/逆问题）**
- "An Agentic Framework for Autonomous Metamaterial Modeling and Inverse Design"，Lu/Malof/Padilla，arXiv:2506.06935（v1 2025-06-07），**ACS Photonics 2025, 12(11):6071–6080**：Planner+Input Verifier+Forward Modeler+Inverse Designer 多智能体，自动完成"正向代理模型训练→逆向设计"全流程，自带内部反思与决策回退。→ 最接近我们想要的"agent 编排 EM 计算"形态（但代理模型是神经网络，不是全波求解）。顶刊（ACS Photonics）+预印本双证据。
- "MCP-Enabled LLM for Meta-optics Inverse Design"，arXiv:2508.10277（2025-08）：**用 MCP 把 LLM 接到 meta-optics 逆设计**——与我们"MCP 工具面+LLM 决策层"的选型直接同构（预印本，未核全文，摘要级引用）。
- "Optimizing Photonic Structures with Large Language Model Driven Algorithm Discovery"，arXiv:2503.19742（2025-03-25）：LLaMEA 框架让 LLM **进化出优化算法**再用于 Bragg 镜/椭偏逆分析/减反膜——"LLM 生成算法、确定性评估"的又一形态。

**C. 超材料**
- "Can Large Language Models Learn the Physics of Metamaterials?"，arXiv:2404.15458（2024-04）：微调 GPT-3.5 做几何→光谱回归与逆向，比常规 ML 基线误差低。→ 说明"LLM 当 EM 代理模型"可行但走微调路线，与我们的 in-context 路线不同（预印本）。

**D. 化学自主实验（最贵的"物理评估"先例）**
- Coscientist，Boiko/MacKnight/Collins/Gomes，**Nature 624, 570–578 (2023)**，doi:10.1038/s41586-023-06792-0（2023-12-20 在线）：GPT-4 智能体自主设计、规划并执行真实化学实验（含钯催化偶联反应条件优化），工具=网页/文档检索+代码执行+机器人 API。→ 证明"LLM 编排昂贵真实评估"在顶刊层面成立；其教训（计划与执行分层、每步可解释）可迁移。

**E. 非 LLM 但同问题的基线语境**
- 微波腔体滤波器自动调参是成熟领域，样本效率是公认瓶颈：Model-Based RL for Cavity Filter Tuning（L4DC 2023，PMLR v211，Ericsson）用 MBRL 把样本复杂度降 4–10 倍。→ 支撑"任何新决策层都要先证明样本效率"的验收标准。

---

## 5. 问题 5：落地建议（映射到 hfss-mcp）

> 以下为基于 §1–§4 证据+仓库现状（25 个类型化工具、manifest 白名单 trial、SQLite job/run、checkpoint、benchmark）的设计建议；标注证据来源。

### 5.1 Skill 里 Agent 每步该看到什么

每次决策（trial 之间）注入：
1. **任务语义**：case 目标文本化（指标名、阈值、频带、白名单变量+量纲+边界）——= OPRO 的 meta-instruction 部分（P1）；边界来自 manifest，绝不来自 LLM 记忆（P15）。
2. **轨迹摘要**：按 S11 升序的（参数向量, 三指标, 求解耗时, 成败）表，top-N（N≈全部，因为 ≤10 条；若超 N 学 OPRO 截断，P1）。**不给原始 Touchstone**（长数值序列对 LLM 无益且烧 token，P5：LLM 处理数值串能力差）。
3. **失败记录**：失败 trial 的参数+错误码（solve_failed 等），以及"此区域已证不可解"的排除集（P4/P14）。
4. **反思与 insight**：本 run 的反思（≤3 条，P8）+ 全局 insight 池按 case 相似度检索的 top-k（P11）。
5. **预算状态**：剩余 trial 数、墙钟余量、是否已达 threshold（提前停）。

### 5.2 反思记在哪（现有机制能否承载）

- **能承载**：trial/run 的 journal 已是追加式结构化记录（report.json 证明），反思文本作为 run 级附加字段/日志行追加即可，不需要动 benchmark 的 case/答案册（白名单约束）。
- Reflexion 式情景记忆：挂 run 级，滑窗 ≤3（P8）。
- ExpeL 式 insight 池：跨 run/跨 case 的**全局**追加表（带投票字段，P10），只由决策层读写，服务端状态机不依赖它。
- 硬教训：原始反思先过滤/提炼再入池（ExpeL 消融 −10 点，P10）；insight 必须可被人审阅（ExpeL 的可解释性优势）。

### 5.3 策略层与服务端状态机各管什么（贴 ADR-001 划分）

| 层 | 职责 | 依据 |
|---|---|---|
| LLM/Skill 策略层 | 意图与假设（"min 频点 62.9→目标 60，谐振结构偏大还是偏小"）、搜索空间变更**建议**、候选方向批/否、反思/insight 生成、停时建议 | ADR-001 第 1 条；OPRO/ADO-LLM 的 LLM 角色 |
| 服务端 policy broker + 状态机 | 白名单/边界强制、预算与停时、幂等、checkpoint/恢复、候选向量合法性校验（**LLM 出的任何数值都必须过 manifest_validate 才进 trial**）、journal 落盘 | ADR-001 第 2/3 条；OptunaHub 版 LLAMBO 的"过滤越界/重复候选"同款工程（P7） |
| 数值优化器 | 候选点生成的内循环（BO/规则），LLM 只 warmstart 与否决 | ADR-001 第 4 条；P5/P13 |

### 5.4 与现有 probe 策略的关系

- **probe 保留为兜底与基线**：它是确定性、可复现、已 PASS 的（report.json，6 trial +1.73dB）。LLM 层上线后形成 A/B：同 case 同预算比 PASS/改善幅度。
- **建议形态**：LLM 层做"上层策略"——先用领域先验给 warmstart 点（P6），数值循环卡住/失败区域出现时做反思与方向修正（P8/P14），probe 的坐标下降作为数值循环的一个可选算子；LLM 不可用/超时自动降级 probe（P7 的可降级原则）。

---

## 6. 与 ADR-001 的张力

- **张力点在 OPRO**：OPRO 主张 LLM **直接逐点生成数值解**（线性回归/TSP 实验即 LLM 直接吐 (w,b)），这与 ADR-001"数值内循环交给确定性优化器"相反。
- **证据的裁决方向支持 ADR-001**：① OPRO 自己的 Limitations/附录 A 表明纯 LLM 数值循环在高维、崎岖地形、数值精度上失败（§1.5）；② IEEE CIM 2025 的系统评测给出同向结论并明确"LLM 只当候选生成器时才有效"（P5）；③ 领域内活下来的系统（ADO-LLM、LLAMBO、WiseEDA、RFAmpDesigner、LADS）全部采用"LLM 语义层 + 数值优化器内循环"混合体（§3–§4）；④ 本仓库 probe 的 t5_fy 失败样例说明候选合法性/失败容错必须由服务端保证，不能靠 prompt（P14）。
- **结论**：不需要修改 ADR-001；把 OPRO 的价值限定在**轨迹序列化/温度/批量采样的提示工程方法**（P1–P3），其"LLM 直接吐数值点"仅在 warmstart 场景保留（P6），且候选一律过 manifest 校验。
- 另一处小张力：Reflexion/ExpeL 的"重试买数据"假设与昂贵求解冲突——已在 §2.2 改为 run 级反思+全局 insight，不改 ADR-001。

---

## 7. 参考清单（按首次引用顺序）

1. OPRO — Yang et al., "Large Language Models as Optimizers", arXiv:2309.03409, v1 2023-09-07 / v3 2024-04-15, ICLR 2024. 代码 github.com/google-deepmind/opro.（顶会；abs 页与 HTML 全文均已核）
2. LLAMBO — Liu, Astorga, Seedat, van der Schaar, "Large Language Models to Enhance Bayesian Optimization", arXiv:2402.03921, v1 2024-02-06, ICLR 2024 poster. 官方 repo github.com/tennisonliu/LLAMBO（已核）；OpenReview forum?id=OOxotBmGol.
3. LLAMBO Optuna 集成 — OptunaHub registry "samplers/llambo", hub.optuna.org/samplers/llambo, 最后更新 2025-03-28, 作者 Jinglue Xu, Tennison Liu 等, MIT, 验证 Optuna 4.1.0.（官方实现）
4. Reflexion — Shinn et al., "Reflexion: Language Agents with Verbal Reinforcement Learning", arXiv:2303.11366, v1 2023-03-20, NeurIPS 2023. HTML v4 全文已核.
5. ExpeL — Zhao et al., "ExpeL: LLM Agents Are Experiential Learners", arXiv:2308.10144, v1 2023-08-20, AAAI-24（abs 页 comments 自述）. HTML v3 全文已核.
6. Voyager — Wang et al., "Voyager: An Open-Ended Embodied Agent with Large Language Models", arXiv:2305.16291, v1 2023-05-25. 官方站 voyager.minedojo.org. HTML v2 全文已核.
7. LLM-as-optimizer 系统评测 — Huang, Wu, Zhou, Wu, Feng, Cheng, Tan, "Evaluation of Large Language Models as Solution Generators in Complex Optimization", IEEE Computational Intelligence Magazine, vol. 20, 2025（dblp key journals/cim/cim20 卷目录内；IEEE Xplore doc 11200056）. 配套解读：innovate.ieee.org "Testing Large Language Models for Optimization"（2025-10-25）.（顶刊）
8. ADO-LLM — Yin, Wang, Xu, Li, "ADO-LLM: Analog Design Bayesian Optimization with In-Context Learning of Large Language Models", arXiv:2406.18770, v1 2024-06-26, ICCAD 2024（DOI 10.1145/3676536.3676816）.（顶会）
9. LADS/LEAM — Wu et al., "Large Language Model-Based Intelligent Antenna Design System", arXiv:2504.18271, 2025-04-25. 代码 github.com/TaoWu974/LEAM.（预印本）
10. AMS sizing agent — "LLM-based AI Agent for Sizing of Analog and Mixed Signal Circuit…", arXiv:2504.11497, 2025-04.（预印本）
11. WiseEDA — "WiseEDA: LLMs in RF Circuit Design", ScienceDirect（pii S1879239125000566）, 2025.（期刊，摘要级）
12. RFAmpDesigner — arXiv:2605.10093, 2026-05.（预印本，摘要/引言级）
13. RF-Agent — arXiv:2607.18772, 2026-07.（预印本，abs 页级）
14. MenTeR — arXiv:2505.22990, 2025-05（经 CircuitLM arXiv:2601.04505 引用列表见到，**二手**，未核原文）.
15. 光子 agentic 逆设计 — Lu, Malof, Padilla, "An Agentic Framework for Autonomous Metamaterial Modeling and Inverse Design", arXiv:2506.06935（v1 2025-06-07）; ACS Photonics 2025, 12(11), 6071–6080.（顶刊+预印本）
16. MCP 光子逆设计 — "MCP-Enabled LLM for Meta-optics Inverse Design", arXiv:2508.10277, 2025-08.（预印本，摘要级）
17. LLaMEA 光子 — Yin et al., "Optimizing Photonic Structures with Large Language Model Driven Algorithm Discovery", arXiv:2503.19742, 2025-03-25.（预印本）
18. 超材料 FT-LLM — "Can Large Language Models Learn the Physics of Metamaterials?", arXiv:2404.15458, 2024-04.（预印本）
19. Coscientist — Boiko, MacKnight, Collins, Gomes, "Autonomous chemical research with large language models", Nature 624, 570–578 (2023), doi:10.1038/s41586-023-06792-0, 2023-12-20.（顶刊）
20. 腔体滤波器 MBRL — Nimara et al., "Model-Based Reinforcement Learning for Cavity Filter Tuning", L4DC 2023（PMLR v211）.（顶会；非 LLM 语境基线）
21. FAS LLM 视觉文 — Wang et al., arXiv:2506.14288, 2025-06-17.（预印本）
22. Atlas RF Studio — arenaphysica.com/publications/rf-studio.（公司发布页，博客级）
23. 本仓库实录 — benchmark/cases/siw_feed_l1/runs/run_probe_main/report.json（2026-07-29，6 trial PASS）；docs/ADR-001-AUTONOMY-EXECUTION-MODEL.md（2026-07-20）.

## 8. 检索记录与局限

- 检索引擎：AnySearch（api.anysearch.com，匿名访问）+ arXiv/dblp/OptunaHub/IEEE/出版社页面直接抓取（web_fetch）。日期：2026-08-11 ～ 2026-08-12。
- 主要检索式（Q4 领域盘点用）：
  1. `large language model antenna design optimization arXiv`
  2. `LLM agent HFSS electromagnetic simulation antenna`
  3. `large language model microwave filter design optimization`
  4. `LLM RF circuit design optimization agent 2024 2025`
  5. `LLM large language model photonic inverse design agent 2024 2025 arXiv`
  6. `large language model photonic inverse design metamaterial`
  辅助：`ADO-LLM analog circuit optimization large language model`；`critique large language models as optimizers OPRO limitations numerical`；`IEEE Computational Intelligence Magazine large language models optimization evaluation 2025`；`LLAMBO Optuna Bayesian optimization integration`；`Coscientist autonomous chemical research large language model Nature Boiko`。
- **空白声明**：检索式 1–4 未发现「LLM/agent 直接驱动 HFSS 或同级全波 EM 求解器、以 S 参数为目标做闭环参数调优」的公开发表（截至 2026-08-12）；最近的是 LADS（CST 建模+外部优化器）与工业产品 Atlas RF Studio（无论文）。
- 局限：① 2026 年预印本（2601/2605/2607 号段）未经同行评审，只作方向信号；② MenTeR 为二手引用；③ WiseEDA/RFAmpDesigner/RF-Agent 只核到摘要/引言级；④ IEEE CIM 评测文全文在 Xplore 付费墙后，结论经 dblp 条目+IEEE 官方解读文交叉验证；⑤ 未做 LLM 选型调研（任务书明确排除）。
