# 个人洞察平台 0.1.5

单用户、Windows 本机优先的证据研究平台。一个应用内核支持 technical、industry、company 三种 profile。代码、运行数据与报告分离。

代码与工作区分别部署；工作区必须位于整个 Git checkout 之外。用户入口为 `<工作区>/00-开始阅读.html`，具体工程位置在安装时配置。历史设计见 [设计基线](docs/design/baseline-v0.1.md)，实施取舍与阶段边界见 [实施 ADR](docs/implementation-adr.md)。

## 安装与运行

完整报告默认检查 `require_report_composition`：正文不能只重复章节答案，需要明确的 `narrative.conclusion`、`narrative.recommendations`，多判断报告还需来源关联的对照表、示意图、实测图表或原图。`analysis` 返回 `report_gaps` 供修订；`quality` 中的 `report_composition` 控制正式交付。这是结构性最低要求，不是对分析深度的自动评分。新增叙述字段缺省不序列化，历史报告仍可读取。

研究质量由冻结项目中的 `quality_standard` 声明：问题覆盖、发表时间、独立来源组、检索记录与隔离复核分别检查。`quality` 返回未满足项 `next_actions`；普通 `deliver` 要求检查通过，未完成研究只能使用 `deliver --draft`。缺少标准的历史输入保留但不会自动视为通过。HTTP 发表日期取自原始页面元数据，采集时间不替代发表日期，请求时间窗口不冒充观察覆盖。

宿主通过 `record-execution` 记录实际搜索和隔离模型复核；请求消耗冻结计划预算，复核完成记录必须对应当前分析及先前请求。来源组属于待核查声明，重复原件不能计为独立佐证；这些检查不保证检索穷尽、来源真正独立或模型结论正确。可选新增字段在缺省时不参与旧输入序列化，既有冻结哈希保持可读；质量评估策略为 `evidence-quality@5`，评估依据包含执行记录。

```powershell
$insightWorkspace = Join-Path ([Environment]::GetFolderPath('UserProfile')) 'InsightWorkspace'
uv sync --frozen
uv run --frozen insight --workspace $insightWorkspace init
uv run --frozen insight --workspace $insightWorkspace doctor
uv run --frozen insight --workspace $insightWorkspace reading-room
```

Python 3.13.15 由 .python-version 指定，运行库要求 SQLite >=3.51.3；本机实测为 3.53.1。不要把工作区置于网络共享盘或源码目录。依赖由 uv.lock 固定，初次运行 init 执行 Alembic 迁移，普通查询不迁移数据库。

## 一条研究如何运行

以下所有 JSON 的顶层均需 `schema_version: 1`。字段类型、合法值和未知字段规则来自 `schemas` 导出的文件；不是宽松字典约定。

| 操作 | 应用行为 |
|---|---|
| `collectors` / `collector-preflight --plan ID` | 查看能力与独立渠道缺口；不触发研究 |
| `capture-import --file capture.json` | 登记实际浏览器观察、截断状态、时间及附件哈希 |
| `project --file project.json --expected-revision 0` | 创建任务修订，定义问题、用途、地域、日期、profile、子问题 |
| `source-local --id source-id --file original.pdf --publisher ... --provenance ...` | 归档用户提供文件，保存 inbox 逻辑地址；不认证作者说法 |
| `source-import --file import.json` | 同一本地导入用例的结构化入口，原始路径和出处均放 JSON，适用于聊天接入 |
| `source-register --file source.json` | 登记具体公开 URL、频道内的单个视频或稳定 X user ID，以及身份依据 |
| `plan --file plan.json` | 冻结该项目修订下的来源、目标、材料角色、时间窗与预算 |
| `run --plan plan-id --key unique-request-key` | 建立不可变输入快照与持久作业；同幂等键不重复开跑 |
| `worker --max-jobs 20` | 在已有预算内推进采集，每次 API 分页都单独提交断点 |
| `status --run run-id` | 只读执行、材料、证据、预算与事件 |
| `document --run run-id --version source-version-id` | 读取该运行固定提取版本及页/幻灯片/文档单元 |
| `evidence --run run-id --file evidence.json` | 精确校验 source_version、提取版本、单元、字符范围与原文 |
| `context --run run-id --file context.json` | 按全部子问题组织允许的证据，导出模型/人工分析交换包 |
| `analysis --file analysis.json` | 记录结构化判断和作者；引文只能来自固定上下文 |
| `verification --file verification.json` | 按当前分析指纹记录逐条语义复核，不冒充现实独立验证 |
| `quality --run run-id` | 核验原件、引用、来源目标、语义和审阅绑定 |
| `review --file review.json` | 只记录明确的人工作品接受/修改决定，且绑定具体依据 |
| `deliver --run run-id` | 发布新不可变交付，旧交付保留；未审阅草稿有明确状态 |
| `publication-register --file publication.json` | 将PPT、逐页判断与固定研究依据登记入库；未核验稿单列保全 |
| `verify-publication --id pub_...` | 核对成品对象、结构和研究依据是否仍为当前版 |
| `verify-delivery --path projects/.../deliveries/...` | 校验全部声明文件、哈希和可移植性 |
| `resume --run run-id` / `cancel --run run-id` | 接续可恢复采集等待/取消未终结执行，终态不原地重开 |
| `reconcile` | 从数据库登记且校验通过的版本修复派生的项目入口 |

每条命令均以前述 `uv run --frozen insight --workspace ...` 开头。JSON 文件是提交入口或只读交换包，不是第二套数据库。新项目必须显式声明 collection_requirements；多渠道采集、浏览器回执与媒体依赖见 [采集器说明](docs/collectors.md)。聊天 Skill 只调这些用例。

`context.json` 请求形状：

```json
{"schema_version":1,"coverage":[{"schema_version":1,"subquestion":"与任务中的子问题完全一致","evidence_ids":["ev_returned_by_application"],"unresolved":null}],"excluded_or_truncated":[]}
```

分析模式是当前聊天或人工协作。导出的包带项目、profile、来源身份与角色、固定证据、范围、缺口和 AnalysisSubmission schema。提交后才算完成分析，不能把“采集完成”说成“报告完成”。语义复核和人工审阅分别导入，应用不会自行生成用户认可。

## 实际支持范围

详版正文使用 AnalysisSubmission 的可选 `narrative`：按问题组织章节，提供带判断引用的段落、案例表、机制图、算例图和固定原始 PDF 图页。正文、图表数据和解释均参与版本及复核指纹。完整字段由 `schemas` 导出，约束见 [研究正文契约](docs/narrative-report.md)。原图页渲染需要本机 PATH 中的 pdftoppm；没有该工具时明确报错，不伪造图页。它是报告阅读能力，不是平台操作界面或 PPT/Word 导出。

- 本地 UTF-8 文本、HTML、可提取文本的 PDF、DOCX、PPTX；空白/扫描件没有 OCR 就保留缺口。Office 图、表和视觉语义不因提取到文字就算读懂。
- 指定公开网页/文件正文读取。`freshness_rule=snapshot_at_acquisition` 表示本次快照；其他历史新鲜度要求不会因为读到当前网页就自动通过。
- 会议或 YouTube 单视频的原始投影片：pairing_page 必须真链接 material_url；视频目标还必须在同一场次页匹配视频 ID。editable_original_pptx 不能用 PDF 代替。当前不提供频道全量扫描、口述/字幕处理或抽帧。
- X API 的正文和链接元数据窗口：稳定 ID 与 handle 对应核验、明确时间边界、逐页断点、重扫去重、有限页数。当前按 2026-10-26 官方文档字段实现，模拟契约通过不能算真实授权联调；没有真实凭据时不会出网假装读取。
- 研究交付是报告、判断、引用、逐源取得、质量、原件和 manifest。没有后台自动模型调用、PPT/Word 导出、持续监控或多人服务。

X 凭据只由 OS keyring 读取，服务名 `personal-insight-platform`，账号为 credential:// 后面的引用名。不要将令牌写进来源 JSON、报告、命令参数或 Git；受控的交互式配置入口尚未列入本版 CLI。

## 运行目录

日常打开工作区根的 `00-开始阅读.html` 或 `01-研究项目/<项目>/`。项目下按任务、原始资料、证据摘录、分析核验、成果、更新记录组织；跨项目资料索引是辅助入口。使用 `uv run --frozen insight --workspace <工作区> reading-room` 刷新。新初始化的数据库、对象和系统交付默认归入 `90-平台运行/`；旧配置兼容。记录变化后须刷新，不改变权威原件、数据库或历史交付。规则、完整目录及副本边界见[分类与可读工作区](docs/readable-workspace.md)。

```text
<workspace>/
  00-开始阅读.html
  00-工作区说明.md
  01-研究项目/<project>/          任务、原件、证据、分析、成果与更新
  02-共享资料索引/               辅助浏览，不自动进入研究上下文
  workspace.toml                本机相对布局，不含凭据
  90-平台运行/
    state/insight.db             权威关系、状态和版本
    objects/sha256/              不可变原件与提取字节
    inbox/                      已导入原件
    requests/                   请求草稿与提交文件
    catalog/                    候选来源，不自动启用
    outputs/
      projects/<project>/deliveries/  不可变报告与证据包
      projects/<project>/presentations/  外部PPT及可移植索引
      reading-room/             可重建阅读版本
      exchange/                 固定证据交换包
      platform/                 工程验证与安装包
    validation/                 测试工作区
```

对象先落盘后短事务登记引用；崩溃可能留下未引用对象，不自动当垃圾删除。交付先装配和校验再更新入口，注册/入口之间的崩溃由 reconcile 接续。当前单用户发布流程建议使用一个发布者；多进程并发发布的顺序保证与后台调度在后续运维阶段验收。

## 工程验证

```powershell
uv run --frozen python tools/check.py --workspace $insightWorkspace
```

运行格式、静态类型、架构依赖和单元/契约/集成/端到端检查。报告与临时目录在工作区。真实网站联调单独留存，测试素材和研究报告不混用。阶段验收追踪见 [需求与验收](docs/acceptance.md)。

整套工作区迁移前停止写入并关闭进程，复制数据库及对象、inbox、outputs 和配置到新根，再运行 doctor、quality 与 verify-delivery。数据库备份函数只代表元数据备份，不等于全工作区一致性备份；定时备份、保留清理、跨运行增量和长期试运行仍属 M4。


安装、工作区迁移、相对 PPT 索引和安装包验证见 [可移植性](docs/portability.md)。当前修复及未实现边界见 [0.1.1 说明](docs/release-notes-0.1.1.md)。

PPT 与新增分析的登记、文件保全及升级规则见 [统一登记](docs/publication-registration.md)。schema 0002 升级前先备份；代码与工作区同步升级。
