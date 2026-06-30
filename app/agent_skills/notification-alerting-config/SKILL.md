---
name: notification-alerting-config
description: Use when the user asks to configure, design, or diagnose notifications, alerts, email, SMTP, webhook callbacks, failure alerts, run completion notifications, readiness alerts, or release gate messaging for TestAuto.
triggers:
  - 通知
  - 告警
  - 邮件
  - SMTP
  - webhook
  - 回调
  - 失败通知
  - 完成通知
  - readiness alert
  - alert
  - notification
  - 消息推送
routing_requires_tool:
  - real notification config
  - current SMTP config
  - webhook delivery result
  - alert history
  - failed notification
  - 真实通知配置
  - 当前SMTP配置
  - webhook投递结果
  - 告警历史
  - 通知失败
---

# Notification Alerting Config

## Workflow

1. Identify the trigger: plan completion, run failure, release gate failure, flaky trend, readiness issue, worker stale run, or manual report sharing.
2. For real notification settings or delivery failures, require config evidence, report/run evidence, or tool output before naming a cause.
3. Define recipients, channel, severity threshold, deduplication, retry policy, silence window, and report/deep-link content.
4. Treat SMTP passwords, webhook secrets, chat tokens, and signed URLs as secrets. Never print them.
5. If no notification write or delivery tool exists, provide the configuration contract and do not claim the alert was created or sent.

## Final Reply

- State whether this is a proposed notification design or a confirmed platform configuration.
- Include what event should trigger the alert, who receives it, and what evidence should be attached.
- Do not invent delivery ids, webhook responses, email logs, or configured recipients.
