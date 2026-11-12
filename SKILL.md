---
name: bilibili-subtitle-download
description: Download Bilibili video subtitles/transcripts (including AI-generated 字幕) as SRT/JSON/TXT, or convert existing vCaptions/Bilibili subtitle JSON to SRT. Use when the user wants 下载 B 站字幕、导出字幕、批量导出多 P 视频字幕、把 vCaptions 的 .json 转成 .srt, or asks how to obtain subtitles for a course/collection.
---

# Bilibili Subtitle Download

## Goal

拿到 Bilibili 视频（含多 P 课程）的字幕，保存为可检索的 `.srt`、原始 `.json` 或纯文本 `.txt`。不下载视频本身。

## Required inputs

必须确认：

- 视频 URL 或 BV 号
- 输出目录

以下情况才追问：

- 多 P 视频：只下当前 P，还是全部 P
- 需要哪种语言；默认优先中文
- 是否需要 `.json` / `.txt` 附加产物

## Default behavior

- 默认只下当前 P（URL 带 `?p=N` 就取第 N P），中文优先。
- `--all-pages` 才批量下多 P。
- 默认同时保留 `.srt` 与 `.json`；`--txt` 额外写纯文本。
- 不把 Cookie 写进命令历史；优先读文件或环境变量。
- 不用浏览器自动化去点页面；直接走 Bilibili 公开 API。

## Workflow

1. **确认环境**
   ```bash
   python3 --version   # >= 3.10；脚本只用标准库
   ```
2. **确认链接与目录**
   - 没有链接先要链接；没有目录先要目录，不要默认当前目录。
3. **先列字幕**
   ```bash
   python3 scripts/bili_subtitles.py 'https://www.bilibili.com/video/BV1c4411d7jb/' \
     --cookie-file ~/.config/bili-cookies.txt --list
   ```
   如果 `subtitles` 为空，通常是未登录或该视频没有开放字幕，见「登录」。
4. **下载**
   ```bash
   python3 scripts/bili_subtitles.py 'https://www.bilibili.com/video/BV1c4411d7jb/' \
     -o temp/bili-subtitles/BV1c4411d7jb --all-pages --txt
   ```
5. **验收**
   - 检查生成的 `.srt` 数量与页数一致
   - 抽查首尾时间轴、空字幕页
   - 输出目录中保留 `_ai-zh.json` 等原始 JSON，便于回溯

## 登录（AI 字幕必需）

Bilibili 的 AI 字幕接口通常要求登录态；只带 UA/Referer 时 `x/player/wbi/v2` 的 `subtitles` 会是空数组。脚本会自动从 `x/frontend/finger/spi` 补取 `buvid3`/`buvid4`（取不到则忽略），并发送 `Origin` / `Sec-Fetch-Site: same-origin` 等视频页同源请求头；不手工计算 WBI 签名。

支持三种方式，按优先级：

1. `--cookie-file`：浏览器导出的 **Netscape cookies.txt**（推荐）
2. `BILI_COOKIE` 环境变量：完整 Cookie 字符串（如 `SESSDATA=...; bili_jct=...`）
3. `--cookie`：直接字符串（会进 shell 历史，不推荐）

获取方式：

- Chrome/Edge 安装 “Get cookies.txt LOCALLY” 一类扩展，导出 `bilibili.com` 的 cookies.txt
- 或 DevTools → Application → Cookies → 复制 `SESSDATA`，写成 `SESSDATA=...`

安全规则：

- **不要向用户索要账号密码。**
- **不要回显 Cookie 值**，也不要把 cookies.txt 提交到仓库。
- Cookie 失效时 API 返回空字幕，不要把它当成“视频没有字幕”。

## Commands

```bash
# 单个 P
python3 scripts/bili_subtitles.py BV1c4411d7jb -o out --cookie-file cookies.txt

# 多 P 全量，中文优先，额外生成 txt
python3 scripts/bili_subtitles.py 'https://www.bilibili.com/video/BV1qG41197E4/?p=1' \
  -o out --all-pages --txt --cookie-file cookies.txt

# 列出可用字幕语言
python3 scripts/bili_subtitles.py BV1c4411d7jb --list --cookie-file cookies.txt

# 指定语言；--all-langs 下载全部语言
python3 scripts/bili_subtitles.py BV1c4411d7jb -o out --lang zh-Hans --cookie-file cookies.txt
python3 scripts/bili_subtitles.py BV1c4411d7jb -o out --all-langs --cookie-file cookies.txt

# 已有 vCaptions / Bilibili AI 字幕 JSON，仅转 SRT
python3 scripts/bili_subtitles.py --from-json temp/wangzhuo_ds/001_前言_ai-zh.json -o out

# 批量转换目录
python3 scripts/bili_subtitles.py --from-json temp/wangzhuo_ds --glob '*_ai-zh.json' -o out
```

## Output naming

沿用课程整理习惯：

```text
001_第01周a--前言_ai-zh.json
001_第01周a--前言_ai-zh.srt
001_第01周a--前言_ai-zh.txt   # 仅 --txt
```

- 页码三位补零
- 标题做文件名安全化（去掉 `/\:*?"<>|`，空白压成 `_`）
- 语言后缀取 API 的 `lan`（如 `ai-zh`、`zh-Hans`）
- 不覆盖已存在文件，除非 `--force`

## Stop points

- 没有链接或输出目录
- 需要用户提供 cookies.txt / SESSDATA
- 视频没有字幕，或字幕接口持续返回空
- API 返回 `-101`/`-403` 且确认是登录态问题

## Important rules

- 只下载字幕，不下载音视频；需要视频用 `bilibili-video-download`。
- `subtitle_url` 可能是 `//...`，必须补 `https:`。
- 多 P 的 `cid` 来自 `x/web-interface/view` 的 `data.pages[]`，不要拿 `aid` 当 `cid`。
- 不要高频并发；脚本默认每页间隔 0.8s，失败重试 3 次。
- 不要把 Cookie 拼进日志、异常信息或最终回答。
- 用户给的链接若带 `?p=N`，默认只处理该 P；要全量必须显式 `--all-pages`。
- 对已有 JSON 的转换不依赖网络，优先用 `--from-json`，避免重复请求。

## References

- `references/api.md`：接口、返回结构、错误码、vCaptions JSON 格式
- `scripts/bili_subtitles.py`：实现（标准库，无第三方依赖）
