# Bilibili 字幕接口与数据格式

## 1. 取 BV 号与 cid

```http
GET https://api.bilibili.com/x/web-interface/view?bvid=BV1c4411d7jb
```

关键字段：

```json
{
  "code": 0,
  "data": {
    "bvid": "BV1c4411d7jb",
    "aid": 112161859,
    "title": "计算机网络微课堂（有字幕无背景音乐版）",
    "cid": 112161859,
    "pages": [
      { "cid": 112161859, "page": 1, "part": "1.1 计算机网络在信息时代的作用", "duration": 234 }
    ]
  }
}
```

- 单 P 可以用 `data.cid`。
- 多 P 必须遍历 `data.pages[]`，每项的 `cid` 才是该 P 的字幕查询参数。
- `aid` 不是 `cid`，不要混用。

## 2. 取字幕列表

```http
GET https://api.bilibili.com/x/player/wbi/v2?aid=112161859&cid=112161859
Cookie: SESSDATA=...; buvid3=...; buvid4=...
User-Agent: Mozilla/5.0 ...
Referer: https://www.bilibili.com/video/BV1c4411d7jb/
Origin: https://www.bilibili.com
Sec-Fetch-Site: same-origin
Accept-Language: zh-CN,zh;q=0.9
```

`aid` 来自第 1 步的 `data.aid`，`cid` 来自 `data.cid` 或 `data.pages[].cid`。两个主流扩展（vCaptions / IndieKKY 的哔哩君）都调用这个 wbi 接口，且**不手工计算 WBI 签名**；它们靠的是 B 站视频页上下文里的完整 first-party Cookie 和同源请求头。

`buvid3` / `buvid4` 可用匿名接口补取，失败不影响主流程：

```http
GET https://api.bilibili.com/x/frontend/finger/spi
User-Agent: Mozilla/5.0 ...
```

返回 `data.b_3` / `data.b_4`，分别作为 `buvid3` / `buvid4` 追加到 Cookie。

返回：

```json
{
  "code": 0,
  "data": {
    "subtitle": {
      "allow_submit": false,
      "subtitles": [
        {
          "id": 123,
          "lan": "ai-zh",
          "lan_doc": "中文（自动生成）",
          "type": "AIsubtitle",
          "subtitle_url": "//aisubtitle.hdslb.com/bfs/ai_subtitle/prod/....json"
        }
      ]
    }
  }
}
```

- `subtitles` 为空数组时：未登录、登录态失效、`aid/cid` 不匹配、该 P 没有字幕，都可能。
- `subtitle_url` 可能是 `//` 或 `http://`，分别补 `https:`、升级为 `https`。
- 常见 `lan`：`zh-Hans`、`zh-CN`、`zh`、`ai-zh`、`en-US`。
- `type` 常见：`AIsubtitle`（AI 字幕）、`subtitle`（人工/上传字幕）。

## 3. 下载字幕 JSON

直接 GET `subtitle_url`，只带 User-Agent；**不要带 Cookie / Referer**，CDN 上的字幕 JSON 是公开文件。

```json
{
  "font_size": 0.4,
  "font_color": "#FFFFFF",
  "background_alpha": 0.5,
  "background_color": "#9C27B0",
  "Stroke": "none",
  "type": "AIsubtitle",
  "lang": "zh",
  "version": "1.5.0",
  "body": [
    { "from": 1.52, "to": 2.579, "sid": 1, "location": 2, "content": "同学们好", "music": 0.0 },
    { "from": 2.76, "to": 6.36, "sid": 2, "location": 2, "content": "在正式开始咱们的课程内容之前呢", "music": 0.0 }
  ]
}
```

字幕正文在 `body[]`：

- `from` / `to`：秒，浮点数
- `content`：这一条字幕的文本
- `sid`：序号（不一定连续）
- `location` / `music`：播放器样式/音乐标记，转 SRT 时可忽略

## 4. 转 SRT

```text
1
00:00:01,520 --> 00:00:02,579
同学们好

2
00:00:02,760 --> 00:00:06,360
在正式开始咱们的课程内容之前呢
```

时间格式：`HH:MM:SS,mmm`；毫秒四舍五入；`to` 缺失时可用下一条 `from` 或 `from + 2s` 兜底。

## 5. 常见错误

| code / 现象 | 含义 | 处理 |
| --- | --- | --- |
| `-101` | 账号未登录 | 提供有效 `SESSDATA` |
| `-403` | 访问权限不足 | 检查 Cookie/Referer，或该视频限制 |
| `code=0` 但 `subtitles=[]` | 未登录/无字幕 | 先登录；确认该 P 是否真的开放字幕 |
| `subtitle_url` 403 | 字幕文件地址失效 | 重新请求 `x/player/wbi/v2` 获取新地址 |
| 429 / 请求频繁 | 触发限流 | 增大 `--sleep`，降低并发 |

## 6. vCaptions JSON

vCaptions 导出的 `_ai-zh.json` 与 Bilibili AI 字幕 JSON 结构兼容，至少包含：

```json
{
  "type": "AIsubtitle",
  "lang": "zh",
  "body": [{ "from": 1.52, "to": 2.579, "content": "同学们好" }]
}
```

因此可以直接：

```bash
python3 scripts/bili_subtitles.py --from-json 001_前言_ai-zh.json -o out
```

不需要 Cookie，也不会发网络请求。

## 7. 批量与命名

- 多 P 按 `pages[].page` 三位补零：`001_...`、`002_...`。
- 文件名中的标题做安全化：`/\:*?"<>|` → `_`，空白 → `_`。
- 语言后缀取 `lan`：`ai-zh`、`zh-Hans`。
- 默认保留 `.json` 原始文件；`.srt` 用于阅读/检索；`--txt` 生成纯文本。
