---
name: summaries
description: Generate daily, weekly, and monthly spending summaries
version: 0.1.0
author: hushmoney
metadata:
  hermes:
    tags: [Summaries, Reporting]
    category: hushmoney
    requires_tools: [terminal]
    blueprint:
      - cron: "0 20 * * *"   # daily at 20:00
        trigger: daily_summary
      - cron: "0 9 * * 1"    # weekly on Monday at 09:00
        trigger: weekly_summary
      - cron: "0 9 1 * *"    # monthly on the 1st at 09:00
        trigger: monthly_summary
---

# Summaries

## When to Use
On schedule (daily / weekly / monthly) or when the user requests a summary on demand.

## Procedure
1. TODO

## Pitfalls
- TODO

## Verification
- TODO
