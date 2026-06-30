---
name: media-evidence-management
description: Use when the user asks to upload, attach, review, explain, troubleshoot, or manage screenshots, media evidence, MinIO objects, defect attachments, signed URLs, image format validation, media cleanup, or evidence redaction.
triggers:
  - media
  - MinIO
  - screenshot
  - attachment
  - signed URL
  - evidence
  - image
  - 媒体
  - 截图
  - 附件
  - 证据
  - 图片
  - 预签名
  - 对象存储
routing_requires_tool:
  - current media evidence
  - real attachment
  - current defect media
  - 当前媒体证据
  - 真实附件
  - 当前缺陷附件
---

# Media Evidence Management

## Workflow

1. For evidence collection, redaction, attachment naming, and media troubleshooting advice, answer directly.
2. If the user asks for real media objects, signed URLs, or defect attachments, use available read tools first and state when no media-specific tool exists.
3. If the user asks to upload, delete, attach, detach, or regenerate signed URLs, only claim completion when a dedicated backend tool succeeds.
4. For defect work, coordinate with `defect-triage` and keep media evidence separate from defect persistence.

## Evidence Rules

- Accept only safe image/media types declared by the platform, and explain when SVG or executable content should be rejected.
- Redact secrets, cookies, tokens, private personal data, and production identifiers before sharing evidence.
- Treat MinIO object keys and signed URLs as sensitive operational details; do not invent them.
- Explain non-atomic MinIO/MySQL failure modes: orphan object, stale metadata, delete retry, and lifecycle cleanup.

## Final Reply

- State whether media was actually read/changed or whether this is a checklist.
- Provide evidence naming, redaction, and attachment steps without exposing secrets.
