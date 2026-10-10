# 贡献指南

## 提交前请先读

- [`AI_POLICY.md`](AI_POLICY.md) —— 本项目要求**披露 AI 参与**

## 基本要求

- **一个问题一个 PR**，说明动机（为什么改）与验证方式（怎么确认改对了）
- 遵循现有代码风格与结构；优先保持脚本**纯标准库**依赖
  （`scripts/manual_download_loop.py` 是唯一例外，它需要 `playwright`）
- 新增脚本请在 `SKILL.md` 的脚本表、必要时在 `references/` 中登记

## 两条硬红线

1. **绝不提交凭证。**
   仓库用 `.gitignore` 拦截了 `credentials.json` / `*.token` / `*.key` / `.env`，
   但**不要依赖它**——请自己确认提交内容里没有 token、key、cookie。
   凭证应只存在于环境变量或 `~/.paper-fetch/credentials.json`。

2. **绝不提交下载的论文。**
   论文有版权，`.gitignore` 已拦截 `*.pdf` 等。本仓库只放工具，不放内容。

## AI 辅助

**允许**，但须按 [`AI_POLICY.md`](AI_POLICY.md) 在 commit 中披露，
并对提交内容负全部责任（自行审查、理解、打磨）。

## 报告安全问题

**不要开公开 issue。** 见 [`SECURITY.md`](SECURITY.md)。
