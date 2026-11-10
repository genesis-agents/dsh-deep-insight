---
description: "Evidence-based research workspaces for DeepSeek Harness."
kind: package-reference
---

# Deep insight

English | [中文](README.zh.md)

## Summary

Deep insight adds a research workflow to the current DeepSeek Harness conversation: collect sources, retain originals, extract evidence, analyze findings and export readable reports. This is an experimental plugin; failed acquisition and incomplete evidence remain visible.

## Table of contents

- [Install](#install)
- [Use](#use)
- [Model experience](#model-experience)
- [Limitations](#limitations)
- [Development](#development)

<a id="install"></a>

## Install

Requires Node 24.9 or newer, DeepSeek Harness 0.2.2-rc.1, uv and Python 3.13. Install the prebuilt tarball from this repository's Releases through the supported DSH plugin manager; replace the archive path below with the downloaded file.

```sh
dsh plugin --profile web add /absolute/path/dsh-deep-insight-0.2.0-alpha.33.tgz
dsh plugin --profile web exec node node_modules/dsh-deep-insight/scripts/setup-engine.mjs --profile web
dsh --profile web
```

The setup command verifies the bundled engine files, copies them into a versioned writable profile directory and runs uv sync with the frozen lockfile. Existing explicit deep-insight.json settings remain unchanged; modified runtime files cause an error. Add --media to setup for the optional video-download dependency. PDF page rendering additionally requires pdftoppm.

If pnpm reports ERR_PNPM_IGNORED_BUILDS, allow the two named dependencies in the installed profile's pnpm-workspace.yaml. Remove the failed package entry with `dsh plugin --profile web remove dsh-deep-insight`, then repeat installation; this also restores bundle activation after a partial install:

```yaml
allowBuilds:
  onnxruntime-node: true
  protobufjs: true
```

<a id="use"></a>

## Use

Ask the agent to research a question. The deep_insight tool's guide action describes the workflow and input schemas. The conversation's Deep insight tab shows saved sources, evidence, analysis and delivery checks. Each conversation has a separate research workspace; the profile's configured engine can be shared.

Node details scroll independently and close by folding the docked sidebar. Titles use 20px, section headings 18px, body text and quotations 16px, and metadata 14px. Execution history has a central entry. Reports link evidence with sentence-level superscripts; original figures accompany explanations. The readable project folder contains the task, original materials, evidence, analysis, deliverables, update history and an overview.

Knowledge structuring displays saved nodes and directed relations as an interactive graph with relationship and circle layouts. Node size reflects connection count; selecting a node highlights its neighborhood. Relation labels can be toggled, and fullscreen places evidence details beside the graph. Search node labels or relations, zoom and pan, and select a node or relation to inspect its evidence. The node selector and list provide keyboard access, full labels and isolated nodes. If graph rendering fails, retry or use the list; existing results do not require regeneration. Generated relations remain unreviewed analysis.

Each evidence quotation renders as one quote block with its original wording. Long quotations collapse to four lines and can be expanded. Source context opens separately through the original-evidence link.

<a id="model-experience"></a>

## Model experience

The standard DSH tool and optional native-agent MCP bridge share the research schema. Tool identity, model selection and permissions come from the executing agent. Research actions write through the bundled Python engine. Enrichment uses the host's configured model and web services; embedding models may download on first use. Subscription operations require the host scheduler. Native-agent completion enforcement is available only on hosts that provide the optional bridge.

<a id="limitations"></a>

## Limitations

YouTube embedding can be restricted by platform policy or host configuration; original-video links remain available. Captions alone do not establish visual understanding. Email acquisition needs an actual connected collector. Missing credentials, blocked sources and unmet review requirements do not count as successful research. The plugin does not provide automatic self-evolution of the PIES application.

<a id="development"></a>

## Development

Run npm test and npm run build:client in this package. The engine-manifest.json hashes cover the bundled engine runtime; changes to that runtime require a new verified manifest and writable runtime directory. Research data and credentials do not belong in this repository or release archives.

## Dev note

The optional PIES integration retains existing session workspace locations for compatibility.
