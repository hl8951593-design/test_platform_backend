---
name: report-archive-export
description: Use when the user asks about report export, HTML/PDF delivery, archived reports, retention policy, historical trend, shareable report links, audit evidence, or long-term report storage.
triggers:
  - 报告导出
  - 报告归档
  - 历史趋势
  - 保留周期
  - PDF
  - HTML
  - export
  - archive
  - retention
  - trend
  - share link
  - audit evidence
routing_requires_tool:
  - real report archive
  - current report export
  - historical trend
  - report retention
  - shareable report
  - 真实报告归档
  - 当前报告导出
  - 历史趋势
  - 报告保留
  - 可分享报告
---

# Report Archive Export

## Workflow

1. Determine whether the user needs a current run summary, an export file, a historical trend, a retention policy, or immutable audit evidence.
2. Use report summaries and execution metadata before discussing real pass rate, failure trend, duration trend, or release readiness.
3. Distinguish on-demand export from persisted archive. Current platform contracts may generate export content without storing an archive file.
4. For retention, account for sensitive headers, tokens, request/response bodies, screenshots, logs, and media links. Apply redaction before sharing.
5. If PDF or archive persistence is not implemented, provide the expected contract and avoid claiming a file was generated or stored.

## Final Reply

- State whether data came from a live report, historical trend, or proposed export design.
- Include privacy and retention caveats for credentials, screenshots, and raw responses.
- Do not invent a download URL, archive id, or PDF artifact.
