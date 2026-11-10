---
description: "DeepSeek Harness 的循证研究工作区。"
kind: package-reference
---

# 深度洞察

[English](README.md) | 中文

## 概要

深度洞察在当前 DeepSeek Harness 对话中加入研究流程：采集来源、保留原件、提取证据、分析发现并导出可读报告。这是实验性插件；采集失败与证据缺口会明确保留。

## 目录

- [安装](#install)
- [使用](#use)
- [模型体验](#model-experience)
- [限制](#limitations)
- [开发](#development)

<a id="install"></a>

## 安装

需要 Node 24.9 或更新版本、DeepSeek Harness 0.2.2-rc.1、uv 和 Python 3.13。通过 DSH 插件管理器安装已发布的 npm 包，也可使用 Releases 中的压缩包。

```sh
dsh plugin --profile web add dsh-deep-insight@0.2.0-alpha.34
dsh plugin --profile web exec node node_modules/dsh-deep-insight/scripts/setup-engine.mjs --profile web
dsh --profile web
```

安装脚本校验附带内核的文件，将其复制到配置目录内带版本的可写位置，并按冻结锁文件运行 uv sync。已有 deep-insight.json 显式配置保持不变；运行时文件被修改时会报错。需要视频下载依赖时，在安装命令后加 --media。PDF 原始页面渲染另需 pdftoppm。

如果 pnpm 报 ERR_PNPM_IGNORED_BUILDS，请在所用配置目录的 pnpm-workspace.yaml 中允许以下两个依赖的安装脚本。用 `dsh plugin --profile web remove dsh-deep-insight` 移除失败的包记录，再重新安装，以恢复安装中断后的插件启用：

```yaml
allowBuilds:
  onnxruntime-node: true
  protobufjs: true
```

<a id="use"></a>

## 使用

向 Agent 提出研究问题。deep_insight 工具的 guide 操作提供流程与输入格式。对话的“深度洞察”页呈现已保存的来源、证据、分析和交付检查。各对话使用独立研究工作区，配置中的内核可供同一配置下的对话共用。

节点详情独立滚动，关闭时折叠停靠侧栏。主标题 20px、小节标题 18px、正文与引文 16px、辅助信息 14px。执行历史有统一入口。报告通过句内角标链接证据，原始图表放在说明旁。可读研究目录包含任务、原始资料、证据、分析、成果、更新记录和概览。

知识结构化将已保存的节点和有向关系呈现为交互图谱，提供关联布局与环形布局。节点大小表示关联数量，选择节点后高亮其邻接关系。关系文字可以切换显示，全屏时证据详情与图谱并排呈现。可以搜索节点名称或关系，缩放、平移，并选择节点或关系查看其证据。节点选择框和列表支持键盘操作，保留完整名称与孤立节点。图谱渲染失败时可以重试或使用列表；已有结果无需重新生成。生成的关系仍属于未经独立复核的分析。

每条证据引文直接呈现为一个引用块，保留原文措辞。长引文默认收起为四行，可以展开；来源上下文通过原文详情入口单独查看。

同一项目和来源的多次采集，在原件字节和提取文档相同时共用一个材料目录，每次采集的来源记录仍保留在材料历史中；内容变化的版本单独保留。刷新时，旧阅读副本归档到 outputs/reading-room/superseded-material-views，原件、数据库记录和不可变阅读版本保持保留。

<a id="model-experience"></a>

## 模型体验

标准 DSH 工具与可选的原生 Agent MCP 桥接共用研究输入格式。调用身份、模型与权限来自实际执行的 Agent。研究写入通过附带的 Python 内核完成。增强分析使用宿主配置的模型和网页服务；嵌入模型可能在首次使用时下载。订阅操作需要宿主调度服务。原生 Agent 完成条件强制检查仅在提供可选桥接的宿主上可用。

<a id="limitations"></a>

## 限制

YouTube 内嵌播放可能受平台策略或宿主配置限制，仍提供原视频链接。字幕不能单独证明理解了视频画面。邮箱采集需要实际连接的采集器。缺少凭据、来源被阻止或审阅未通过，都不计为研究成功。此插件不提供 PIES 应用的自动自我进化。

<a id="development"></a>

## 开发

在本包目录运行 npm test 和 npm run build:client。engine-manifest.json 的哈希覆盖附带的内核运行文件；修改内核时需要生成新的校验清单和可写运行目录。研究数据与凭据不得进入源码仓库或发布压缩包。

## 开发说明

可选 PIES 集成保留已有会话工作区位置，以保持兼容。
