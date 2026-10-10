# 安全政策

## 报告漏洞或凭证泄漏

**不要开公开 issue。** 请使用 GitHub 的私密漏洞报告
（仓库页面 → **Security** → **Report a vulnerability**），或直接联系维护者。

以下情形尤其请私下报告：

- 脚本的凭证处理缺陷（例如把 token 写进日志、输出或异常信息）
- `.gitignore` 未能覆盖的凭证落盘路径
- 任何已泄漏的 API key / TDM token
- 绕过 `manual_download_loop.py` 默认关闭开关的方式（若你认为该开关形同虚设）

## 本项目的凭证处理原则

- 仓库**不含任何真实凭证**，只有 `credentials.example.json` 占位模板
- 运行时凭证只从**环境变量**或 `~/.paper-fetch/credentials.json` 读取，优先级前者更高
- 脚本**不应打印**凭证；报错信息如需指认，只显示前 4 位 + 后 4 位
- 提交前请自查：`git diff --cached` 里不该出现任何形如长随机串的值

## 关于下载的内容

本仓库是**工具**，不包含也不应包含下载的论文（版权原因，`.gitignore` 已拦截）。
若你发现有人通过 issue / PR / wiki 上传了受版权保护的内容，请一并私下告知。
