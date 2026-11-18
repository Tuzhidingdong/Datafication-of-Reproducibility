# DOR 真实数据科学发现报告

- 运行目录：`<LOCAL_RUNS_DIR>/dor_scientific_discovery_20261118_01`
- Runtime：`f361564edca7bbd68b2cda73b595e8943978f11f`（engine 1.3.0），Python 3.13.9
- 数据：现有 66,405 行 CSV / 2,345 篇论文 JSON / 已审查 Canonical Bundle（SHA `d8236772…`），未重新抽取文献，未修改任何原始文件
- 本次只执行一次 `dor discover-opportunities`（默认阈值，未提供未经批准的 Semantic Registry），耗时 28.88 秒，退出码 0

---

## 首页：四个必答问题

### 第一：从数据中最值得研究的 3–5 个科学问题是什么？
1. **Q1 / Q2（同一关系的两个方向）**：在同一 Study 内、跨不同 canonical System，`FEAT_ECORR`（V）与 `FEAT_ICORR`（mA cm-2）的秩关联是否一致？DOR 给出 rho = **-1.0**，7 个独立 Study 方向一致（7/7 负），p = q = **0.015625**，CI95 = [-1.0, -0.9487]（证据 ID：`OPP-3E4ECC3E829A`、`OPP-FC09138862D5`）。**但两条记录的 System 级数值是精确互换的，疑似定义性/构造性关系，不应视为两项独立发现。**
2. **Q3（描述性优先）**：`FEAT_LIFE_SYM`（h）的跨 Study 异质性有多大？333 个 Study 的 study median 范围 16.5–8,000 h，中位数 600 h——**仅描述性，无 p/q**。
3. **Q4（描述性优先）**：`FEAT_CAP_RET`（%）的跨 Study 变异：322 个 Study，中位数 81.7%，范围 17.8–101%——**仅描述性**。
4. **Q5（描述性优先）**：`FEAT_IONIC_COND`（mS cm-1）的跨 Study 变异：262 个 Study，中位数 17.3，范围 0.000545–501——单位与量纲跨度极大，提示定义/协议不一致。
5. **Q6（描述性优先）**：`FEAT_OVERPOT_PLAT`（mV）跨 Study 变异：204 个 Study，中位数 65.95 mV，范围 8–1,303.5 mV。

> 实际只有 **2 个**机会带推断统计；其余是覆盖/描述性线索。没有为了凑数而把描述性信号写成“机会”。

### 第二：目前有哪些交互作用候选？哪一个证据最强？
- 现有 Cohort 只有一个 Feature Binding（`FEAT_ENG_DENS`, Wh kg-1）、没有已批准的交互候选对，**因此未运行 `discover-interactions`**（避免擅自创造预测目标）。本次交付的是**可识别性线索**，不是 DOR 预测性交互模型结果。
- 数据驱动候选共 6 对 + 用户指定的 7 对审查（见 `interaction_candidates.csv`）。**结构可识别性最强的是 `FEAT_ECORR`(V) × `FEAT_ICORR`(mA cm-2)**：78 个 Study 共同覆盖、73 个 Study 同 Experiment 共观测、49 个 Study 存在 Study 内交叉变化、142 个不同数值组合（等级 A*）。**但 A* 的关键警告是：两量疑似定义性互逆，统计上的“强交互/强关联”不能分离出独立效应。**
- 次强结构候选：`FEAT_ENG_DENS`(Wh kg-1) × `FEAT_CAP_RET`(%)，45 个共同 Study、30 个同 Experiment、**仅 1 个 Study 有交叉变化**（等级 B，证据弱）。
- 用户指定的 7 个问题中：仅 RQ1（电流密度×粗糙度）有有限的同 Experiment 共观测（3 Study，交叉变化 0，等级 C），其余 6 个因缺少字段（单次面容量、锌厚度/库存、基底材料、盐浓度、CE 协议、温度）为 **D：不可识别**。

### 第三：哪些看起来有关系的变量实际上无法区分独立效应？
1. `FEAT_ECORR` ↔ `FEAT_ICORR`：每条 System 的 condition_value 与 outcome_median 精确互换（例如 1.35↔-0.99），rho=-1.0 且 CI 上界 -0.9487；这是数值互换的证据，不是两个独立变量的可分离效应。
2. `FEAT_LIFE_SYM` × `FEAT_OVERPOT_PLAT`：92 个 Study 共观测，但 DOR 标记为 `CO_OBSERVATION_ONLY_NOT_AN_INTERACTION`；同 Experiment 共现不能推出交互。
3. `FEAT_CAP_RET`、`FEAT_CE` 等 66 条“target=condition”关系：已在统计前排除（`SAME_CANONICAL_ATTRIBUTE`），其表观关联是定义性自关联。
4. `FEAT_IO`（mA cm-2）被当作“电流密度”候选，但 canonical ID 没有已批准语义；它与 `FEAT_ICORR`（腐蚀电流）单位相同但含义不同，不能混用。
5. 缺失元数据不能被解释为“无语义关联”：本次无 approved Semantic Registry（`status=NOT_SUPPLIED`，applied_record_count=0），所有机会均保留 `CANONICAL_IDENTIFIERS_ONLY_REQUIRES_DOMAIN_SEMANTIC_REVIEW`。

### 第四：最值得做的下一组实验是什么？为什么能区分竞争解释？
在**同一电池体系、同一协议**下，对每个独立 Study 同时、独立测量 `FEAT_ECORR` 与 `FEAT_ICORR`，并做**within-System 重复测量**（改变一个量而保持另一个不变），同时完整记录材料组成、基底粗糙度、盐浓度、面容量与温度。
- 若独立测量后 rho 明显偏离 -1.0、且 within-System 操控一个量可改变另一个，则支持真实电化学耦合；
- 若两量始终为数值互换或随体系定义一起变化，则确认是构造性/定义性关系，应从机会列表剔除；
-  factorial 的“电流密度 × 粗糙度”实验需同时记录基底材料与协议，才能把 RQ1 从 C 提升到 A/B。

---

## 1. 数据审计与身份核验
- 原始 CSV：`consolidated_zinc_battery_database.csv`（**32,123,467 B**，SHA `232d7f44…`），66,405 行 × 27 列，短行 0 / 长行 0。字段覆盖：`paper_id`/`batch_id`/`reconciliation_id`/`feature_id`/`target_system` 1.000；`doi`/`title` 0.9967；`resolved_value` 仅 **0.1069**（7,102 有效数值）；`resolved_unit` 0.1351；`worker_a_value` 0.6030；`relative_difference` 0.1337；`table_reference_*` <0.05。
- 对应 JSON：`consolidated_zinc_battery_database.json`（**68,284,939 B**，SHA `187853dd…`），顶层 `metadata`/`papers`；`unique_papers_count=2,345`、`total_observations_count=66,405`；`papers` 为 2,345 条数组，每条含 `paper_id/doi/title/batch_id/observations_count/observations`。
- **未找到**任务中提到的 `research_corpus_paired.csv` 或任何 field dictionary / approved Semantic Registry 文件；Source Inventory 明确引用的是上述 `consolidated_*` 文件，按其 SHA-256 与相互引用确定版本（非按文件名猜测）。
- 既有 Canonical Bundle：`...\consolidated_vquery_early_acceptance_20261117\03_canonical\canonical_bundle.json`（1,085,716,120 B，SHA `d8236772…`），`validate-bundle`：`valid=true`、0 errors、115,050 条结构性警告（`REPORTED_WITHOUT_RAW_VALUE`）。
- 既有 Mapping Plan / Build Spec / Source Inventory / Cohort / Modeling Task 均存在且被引用；Mapping 已在此前用户审查流程中完成，本任务未改动或重新批准。
- 实体规模：JSON 2,345 篇论文 → Canonical 2,213 Studies / 44,209 Systems / 44,209 Experiments / 66,405 Observations。**论文数 ≠ Study 数；Observation 行数 ≠ 独立样本数。**

## 2. Discovery 运行与统计审计
- 286 signals：`CONDITION_COVERAGE` 177、`CO_OBSERVED_TARGET_PAIR` 77、`CROSS_STUDY_DESCRIPTIVE_VARIATION` 30、`WITHIN_STUDY_BETWEEN_SYSTEM_NUMERIC_CONDITION_TREND` 2；284 条无 screen_status（非推断），2 条 FDR screen positive。
- 分析家族：paired contrast **0**、between-system categorical contrast **0**（44 对候选，合格 Study 0）、within-system numeric trend **235**（独立 Study 均为 0）、between-system numeric trend **65**（其中 2 条有 Study 支持与 p/q）。`numeric_trend_fdr_test_count=2`。
- 排除：`SAME_CANONICAL_ATTRIBUTE` **66**，其余原因 0；`mirror_duplicates=0`；`related_opportunity_group_count=1`（两条互逆机会被归为相关组而非删除）。
- BH-FDR：2 个非空 p 值均 0.015625，q 均 0.015625；独立重算完全一致。置信区间由 1,000 次 Study-level bootstrap（seed 42）生成。
- 混杂审查：两条机会均为 `POTENTIAL_CO_EXPOSURE_REQUIRES_DOMAIN_REVIEW`，分别检查 55/58 个结构化 condition 类型；机会 1 发现 3 条完全单调共变（FEAT_EA、FEAT_OVERPOT_NUC、FEAT_OVERPOT_PLAT，各 1 个 Study），机会 2 发现 1 条（FEAT_EA）。多数协变量覆盖不完整（complete_numeric_coverage_study_count=0），未记录域包括材料/组成、协议/实验室/批次、未测量变量。**这是筛查而非协变量调整，也未证明混杂不存在。**

## 3. 逐项科学问题（详见 scientific_questions.csv）
Q1/Q2（上文）各有 7 个独立 Study，study rho 分别为 -1.0 与 -0.9487（不同 Study 的具体数值见 `evidence_map.csv`）；每条机会 7 条账本记录、每条记录 4–5 个 System。支撑 Study ID：`DOR_1FDCD4F502DA2076D89D`、`DOR_5E60FD1AC423CAE01DA0`、`DOR_6C1108DB5DA69A8E07B3`、`DOR_7E3F3B8D75F49D239ED4`、`DOR_9B62170B2106A8EF14A5`、`DOR_A38B09DD6BD454C750BC`、`DOR_CA0C5A8D6BC537DA3E9C`。
Q3–Q6 为跨 Study 描述性中位数范围（无 p/q）；Q7–Q8 为共观测覆盖事实。所有 canonical ID 原样保留，领域含义待人工审核。

## 4. 交互作用与可识别性（详见 interaction_candidates.csv 与 interaction_coverage/）
- 未运行 DOR 预测性交互模型，原因：既有 Modeling Task（`TASK_FEAT_CAP_RET`）仅绑定 1 个 Feature（`FEAT_ENG_DENS`，Wh kg-1），且没有已选交互候选对；强行运行会违反“不得自行创造预测目标”。
- 用户指定 7 个科学问题中，6 个因字段缺失不可识别（D），1 个（电流密度×粗糙度）仅有 3 个 Study 的同 Experiment 共观测、0 个 Study 内交叉变化（C）。
- 数据驱动候选：`FEAT_ECORR×FEAT_ICORR`（A*，疑似构造性）、`FEAT_ENG_DENS×FEAT_CAP_RET`（B）、`FEAT_ICORR×FEAT_ROUGH_RA`（B，1 Study 交叉）、`FEAT_ICORR×FEAT_CAP_RET`（C）、粗糙度与 CE/容量对（C）。
- 等级 A/B/C/D 是实验设计可识别性等级，不是 DOR q 值，也不是 PASS 等级。正向预测改善即便未来出现，也只能称候选预测性交互，不能称因果协同或物理机制。

## 5. 证据强度与解释边界
- 强证据（统计层面）：Q1/Q2 有 7 独立 Study、方向一致、p/q=0.015625、完整账本引用、BH 一致。
- 但科学证据强度为**探索性**：效应疑似定义性互换、语义未批准、协变量覆盖不足、为跨 System 横断面关联。**不得表述为因果、机制或可复现物理规律。**
- 描述性信号（Q3–Q8）不能与推断结果混为一谈；其 study median 跨度大，部分反映单位/协议/定义不一致（如 `FEAT_IONIC_COND` 从 0.000545 到 501 mS cm-1，`FEAT_CONTACT_ANGLE` 存在 `degree (°)`/`degree`/`°` 三种单位字符串）。

## 6. 不可识别与排除（详见 excluded_or_unidentifiable.csv）
- 66 条同名自关联在统计前排除；7 个用户指定交互问题中 6 个 D 级、1 个 C 级。
- 无添加剂基准对照组：**不可识别**。源 CSV 27 列和 Canonical condition_type 均无 additive / baseline / control / protocol / salt concentration / temperature 字段；无法界定基准子集，也无法按盐种/溶剂/构型/协议分层。未把添加剂实验组混入任何基准效应估计。
- 619 条条件指派歧义被排除；115,050 条结构性警告提示大量 reported observation 缺 raw_value，数值覆盖仅 7,102/66,405。

## 7. 产物清单
- DOR 原生输出：`discovery/`（15 项标准产物）。
- 派生交付：`scientific_questions.csv`（8 行）、`interaction_candidates.csv`（13 行）、`excluded_or_unidentifiable.csv`（77 行）、`evidence_map.csv`（14 行账本映射）、`interaction_coverage/`（`coverage_matrix_q1.csv`、`coverage_matrix_d6_opportunity.csv`、`coverage_overview.svg`）、`input_manifest.json`（输入/输出 SHA-256、参数、Runtime 版本）。
- 审计与运行记录：`audit/`（DOR 原生 CSV/JSON 结构审计）、`support/`（执行命令、stdout、提取/核查脚本与中间结果）。

## 8. 执行边界与停止条件
只执行一次 Discovery；未修改原始数据/代码/Schema/阈值；未合并 System；未重新抽取 PDF/SI；未批准任何映射或 Modeling Task；未运行完整 Interaction Discovery、BAT、Worker、模型或 Gate；未提交/push。完成后已停止，等待用户审阅。

**最终科学结论**：现有数据能稳定产出“跨 Study 横断面秩关联”这一层次的探索性证据，但不足以产出可分离独立效应、可解释机制或可推广规律的科学机会；最关键的缺口是变量定义/语义批准、within-System 重复测量设计，以及盐浓度/面容量/协议/温度等核心实验条件的结构化记录。
