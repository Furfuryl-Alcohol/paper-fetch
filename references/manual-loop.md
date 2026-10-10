# 可选扩展：人工下载循环（manual_download_loop.py）

> **默认关闭。** 需要显式启用。它不是本 skill 的默认路径，而是"官方通道都走不通、
> 只剩人工"时的辅助件。

## 它是什么 / 不是什么

对**无官方自助通道**的出版商（RSC / IOP / ACS / 权益未开的 Elsevier / 不在订阅内的 Wiley），
本 skill 的正路是 `make_checklist.py` 出一份清单、由人逐篇下载。本扩展把这件事变顺：
**人在浏览器里点下载，脚本负责翻页、判定、归档命名。**

| 它**不**做 | 它**做** |
|---|---|
| ❌ 不下载任何东西 —— **每一篇都必须由人亲手点** | ✅ 把浏览器导航到下一篇 DOI 落地页 |
| ❌ 不破验证码、不绕 Cloudflare、不伪造身份 | ✅ 读浏览器自己的下载记录，判断"人下完了没有" |
| ❌ 不抓取页面内容、不存凭证 | ✅ 把下好的文件归档到目标目录并按「将命名」改名 |
| ❌ 不绕付费墙 —— **识别到无权限反而跳过** | ✅ 识别付费墙，快速跳过（省去干等） |

**吞吐量被人手点击封顶，快不过一个真人手工下载。**

### 但它是灰色地带 —— 所以默认关闭

Elsevier TDM 协议 2.2、IOP 的反 systematic downloading 条款，**明文禁止"自动化程序
访问其网站"**。本扩展确实**驱动浏览器访问这些站点**，落在这句话的射程内。

因此：**启用 = 用户声明"我对这些内容有访问权，并自担使用风险"。**

## 启用方法（二选一）

```jsonc
// ~/.paper-fetch/settings.json
{ "manual_browser_loop_enabled": true }
```

或运行时加 `--enable-manual-loop`。未启用时脚本会拒绝运行并打印上述说明（退出码 3）。

> skill 的规则：**不主动推荐、不默认使用**本扩展。只在用户明确要求、且已启用时才用。

## 用法

```bash
# 1) 独立 profile 启动 Edge（Chromium 136+ 禁止对默认 profile 开调试端口）
"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
  --remote-debugging-port=9222 \
  --user-data-dir="%USERPROFILE%/.paper-dl/edge-profile" \
  --no-first-run --no-default-browser-check
#    在该窗口登录机构访问，或确保在机构网段（IP 鉴权）

# 2) 跑循环（目标目录默认取清单头部的「目标目录」行）
python scripts/manual_download_loop.py --list "待下载清单.txt"
```

交互：**回车**推进 · **s** 跳过 · **q** 退出。进度存 `dl_state.json`，可断点续跑。

| 参数 | 说明 |
|---|---|
| `--dest` | 覆盖清单里的目标目录 |
| `--timeout` | 单篇无下载的最长等待（默认 180s） |
| `--no-access-grace` | 识别无权限后再等几秒才跳过（默认 20s） |
| `--limit` / `--dry-run` / `--no-input` | 只跑 N 篇 / 只看计划 / 关掉回车兜底 |

## 依赖与迁移

- 只依赖 **`playwright`** 一个第三方包（其余全标准库）。
- **不需要** `playwright install` —— 连的是现成的 Edge，不用 Playwright 自带浏览器。
- Edge profile 路径用 `Path.home()/".paper-dl"/"edge-profile"`，不写死本机路径。
- 换设备：拷这一个 `.py` + `pip install playwright` + 启动 Edge 调试端口即可。
  **注意**清单里的「目标目录」是绝对路径，换机器要改或 `--dest` 覆盖。
- 实测环境：Windows 11 + Edge 155。macOS/Linux 未测（启动命令不同）。

## 实测坑（全是踩出来的，别重走）

这四条是**反直觉但实测如此**的，构成了整个设计：

1. **Playwright 经 `connect_over_cdp` 会劫持下载**：把它重定向到
   `%TEMP%/playwright-artifacts-*/`，**GUID 命名、无 `.pdf` 后缀**。
   表现为"文件打不开 / 不知存到哪" —— **文件本身是好的**。

2. **CDP 下载事件不可靠**。`Browser.downloadProgress` 经 Playwright 的 `CDPSession`
   **收不到**；而 Playwright 的 `download` 事件时灵时不灵 —— 取决于人在**哪个标签**
   点的下载。**所以绝不能拿下载事件当判定。**

3. **唯一可靠的判定 = 轮询浏览器下载记录库**：
   `~/.paper-dl/edge-profile/Default/History` 的 `downloads` 表。
   `journal_mode=delete` → 实时；以 `file:...?immutable=1` 只读打开。
   `state=1` 即完成，带 `target_path`，**与保存位置、与谁接管无关**。
   基线取"进入本篇前的 max(id)"。

4. **付费墙信号只在 ePDF 页，落地页上没有**（实测 Wiley：落地页 marker=None，
   `/doi/epdf/` 页才有）。所以必须**扫所有标签**；且**每篇开始前要清掉上一篇残留的
   标签**，否则上一篇的标记会污染这一篇（连环误判）。
   另外 `has_pdf_link`（页面里有 `/doi/pdf/` 链接）**不能**当有权限判据 ——
   无权限时也有。命中后**再等 grace 才跳过、且不记完成**（跳过可恢复）。

细节注意：脚本用 `python -u` 跑（否则输出被块缓冲藏住）；Playwright sync API 的等待
循环必须用 `page.wait_for_timeout()`（纯 `time.sleep` 不派发事件）。
