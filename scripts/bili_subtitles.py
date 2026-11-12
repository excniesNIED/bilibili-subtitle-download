#!/usr/bin/env python3
"""Download Bilibili subtitles (including AI subtitles) as SRT/JSON/TXT.

Only Python standard library is required.

Examples:
    python3 bili_subtitles.py BV1c4411d7jb -o out --cookie-file cookies.txt
    python3 bili_subtitles.py 'https://www.bilibili.com/video/BV1qG41197E4/?p=1' \
        -o out --all-pages --txt --cookie-file cookies.txt
    python3 bili_subtitles.py --from-json 001_前言_ai-zh.json -o out
"""

from __future__ import annotations

import argparse
import glob as globlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
VIEW_API = "https://api.bilibili.com/x/web-interface/view"
PLAYER_API = "https://api.bilibili.com/x/player/wbi/v2"
SPI_API = "https://api.bilibili.com/x/frontend/finger/spi"

DEFAULT_LANGS = ("zh-Hans", "ai-zh", "zh-CN", "zh")


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def parse_bvid(value: str) -> str:
    m = re.search(r"(BV[0-9A-Za-z]{10})", value)
    if not m:
        raise SystemExit(f"无法从输入中解析 BV 号：{value}")
    return m.group(1)


def parse_page(url: str) -> int | None:
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    raw = query.get("p", [None])[0]
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def load_cookie(args: argparse.Namespace) -> str:
    if args.cookie:
        return args.cookie.strip()
    if os.environ.get("BILI_COOKIE"):
        return os.environ["BILI_COOKIE"].strip()
    if not args.cookie_file:
        return ""

    path = Path(args.cookie_file).expanduser()
    if not path.exists():
        raise SystemExit(f"Cookie 文件不存在：{path}")
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return ""

    # JSON export (browser extensions)
    if text.startswith("{") or text.startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return "; ".join(f"{k}={v}" for k, v in data.items() if k and v)
            if isinstance(data, list):
                pairs = []
                for item in data:
                    if isinstance(item, dict) and item.get("name"):
                        pairs.append(f"{item['name']}={item.get('value', '')}")
                if pairs:
                    return "; ".join(pairs)
        except json.JSONDecodeError:
            pass

    # Raw Cookie header
    if "SESSDATA=" in text and "\t" not in text:
        return re.sub(r"^\s*Cookie:\s*", "", text, flags=re.I)

    # Netscape cookies.txt
    pairs: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        http_only = line.startswith("#HttpOnly_")
        if line.startswith("#") and not http_only:
            continue
        if http_only:
            line = line[len("#HttpOnly_"):]
        fields = line.split("\t")
        if len(fields) >= 7:
            name, value = fields[-2], fields[-1]
            if name:
                pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def headers_for(bvid: str, cookie: str) -> dict[str, str]:
    headers = {
        "User-Agent": UA,
        "Referer": f"https://www.bilibili.com/video/{bvid}/",
        "Origin": "https://www.bilibili.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


def request_json(url: str, headers: dict[str, str], retries: int = 3) -> dict:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"请求失败：{url}（{last}）")


def with_buvid(cookie: str) -> str:
    """补充视频页常见的 buvid3/buvid4；取不到时原样返回，不打印 Cookie。"""
    present = cookie.lower()
    if "buvid3=" in present and "buvid4=" in present:
        return cookie
    try:
        data = api_data(
            request_json(SPI_API, {"User-Agent": UA}, retries=1),
            "获取 buvid",
        )
        pairs = []
        if "buvid3=" not in present and data.get("b_3"):
            pairs.append(f"buvid3={data['b_3']}")
        if "buvid4=" not in present and data.get("b_4"):
            pairs.append(f"buvid4={data['b_4']}")
        if pairs:
            return f"{cookie}; {'; '.join(pairs)}" if cookie else "; ".join(pairs)
    except Exception:
        pass
    return cookie


def api_data(payload: dict, what: str) -> dict:
    if payload.get("code") != 0:
        raise RuntimeError(
            f"{what} 失败：code={payload.get('code')} message={payload.get('message')}"
        )
    return payload.get("data") or {}


def fetch_view(bvid: str, headers: dict[str, str]) -> tuple[str, int, list[dict]]:
    data = api_data(
        request_json(f"{VIEW_API}?bvid={urllib.parse.quote(bvid)}", headers),
        "获取视频信息",
    )
    pages = data.get("pages") or [
        {"cid": data.get("cid"), "page": 1, "part": data.get("title", bvid)}
    ]
    return data.get("title") or bvid, int(data.get("aid") or 0), pages


def fetch_subtitles(aid: int, cid: int, headers: dict[str, str]) -> list[dict]:
    query = urllib.parse.urlencode({"aid": aid, "cid": cid})
    data = api_data(
        request_json(f"{PLAYER_API}?{query}", headers),
        f"获取字幕列表 cid={cid}",
    )
    subtitle = data.get("subtitle") or {}
    return [s for s in subtitle.get("subtitles") or [] if s.get("subtitle_url")]


def choose_subtitle(
    subtitles: list[dict], lang: str | None, all_langs: bool
) -> list[dict]:
    if all_langs:
        return subtitles
    if lang:
        wanted = lang.lower()
        matched = [
            s
            for s in subtitles
            if str(s.get("lan", "")).lower().startswith(wanted)
        ]
        return matched[:1]
    for preferred in DEFAULT_LANGS:
        for s in subtitles:
            if str(s.get("lan", "")).lower() == preferred.lower():
                return [s]
    for preferred in DEFAULT_LANGS:
        for s in subtitles:
            if str(s.get("lan", "")).lower().startswith(preferred.lower()):
                return [s]
    return subtitles[:1]


def safe_name(value: str, fallback: str = "subtitle") -> str:
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", value)
    value = re.sub(r"\s+", "_", value).strip("._ ")
    return (value or fallback)[:80]


def format_ts(seconds: float) -> str:
    total_ms = max(0, int(round(float(seconds) * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def body_to_srt(body: list[dict]) -> str:
    lines: list[str] = []
    index = 0
    for item in body:
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        start = item.get("from", item.get("start", 0))
        end = item.get("to", item.get("end"))
        if end is None:
            end = float(start) + 2.0
        index += 1
        lines.append(str(index))
        lines.append(f"{format_ts(start)} --> {format_ts(end)}")
        lines.append(content)
        lines.append("")
    return "\n".join(lines)


def body_to_txt(body: list[dict]) -> str:
    return "\n".join(
        str(item.get("content", "")).strip()
        for item in body
        if str(item.get("content", "")).strip()
    ) + "\n"


def write_outputs(
    json_data: dict,
    output_dir: Path,
    stem: str,
    want_txt: bool,
    force: bool,
) -> tuple[Path, Path, Path | None]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    srt_path = output_dir / f"{stem}.srt"
    txt_path = output_dir / f"{stem}.txt" if want_txt else None

    if not force:
        existing = [p for p in (json_path, srt_path, txt_path) if p and p.exists()]
        if existing:
            raise FileExistsError(
                "目标文件已存在，使用 --force 覆盖：" + ", ".join(map(str, existing))
            )

    body = json_data.get("body") or []
    srt = body_to_srt(body)
    if not srt.strip():
        raise ValueError(f"字幕 JSON 没有可用 body：{json_path}")

    json_path.write_text(
        json.dumps(json_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    srt_path.write_text(srt, encoding="utf-8")
    if txt_path:
        txt_path.write_text(body_to_txt(body), encoding="utf-8")
    return json_path, srt_path, txt_path


def load_subtitle_json(url: str) -> dict:
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = "https://api.bilibili.com" + url
    elif url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    # 字幕 JSON 是公开 CDN 文件，不发送 Cookie / Referer。
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cmd_from_json(args: argparse.Namespace) -> int:
    source = Path(args.from_json).expanduser()
    if source.is_dir():
        pattern = args.glob or "*.json"
        files = [Path(p) for p in sorted(globlib.glob(str(source / pattern)))]
    else:
        files = [source]

    if not files:
        eprint("没有匹配到 JSON 文件。")
        return 1

    output_dir = Path(args.output).expanduser() if args.output else None
    ok = 0
    for file in files:
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            body = data.get("body")
            if not isinstance(body, list):
                eprint(f"[skip] 不是 Bilibili/vCaptions 字幕 JSON：{file}")
                continue
            stem = safe_name(file.stem)
            target = output_dir or file.parent
            j, s, t = write_outputs(data, target, stem, args.txt, args.force)
            ok += 1
            print(f"[ok] {s}（{len(body)} 条）")
            if t:
                print(f"     {t}")
        except FileExistsError as exc:
            eprint(f"[skip] {exc}")
        except Exception as exc:
            eprint(f"[fail] {file}: {exc}")
    return 0 if ok else 1


def cmd_download(args: argparse.Namespace) -> int:
    bvid = parse_bvid(args.url)
    cookie = with_buvid(load_cookie(args))
    headers = headers_for(bvid, cookie)

    title, aid, pages = fetch_view(bvid, headers)
    page_from_url = parse_page(args.url)
    if args.page:
        selected_page = args.page
    elif page_from_url:
        selected_page = page_from_url
    else:
        selected_page = 1

    if args.all_pages:
        selected = pages
    else:
        selected = [p for p in pages if int(p.get("page", 1)) == selected_page]
        if not selected:
            eprint(f"找不到第 {selected_page} P；该视频共 {len(pages)} P。")
            return 1

    if args.list:
        print(f"视频：{title}（{bvid}，共 {len(pages)} P）")
        for page in selected:
            cid = page.get("cid")
            part = page.get("part") or title
            subs = fetch_subtitles(aid, int(cid), headers)
            print(f"  P{page.get('page')} cid={cid} {part}")
            if not subs:
                print("    字幕：无（可能未登录，或该 P 未开放字幕）")
            for sub in subs:
                print(
                    f"    - lan={sub.get('lan')} type={sub.get('type')} "
                    f"doc={sub.get('lan_doc')}"
                )
        return 0

    output_dir = Path(args.output).expanduser()
    written = 0
    skipped = 0
    for page in selected:
        cid = int(page["cid"])
        page_no = int(page.get("page", 1))
        part = page.get("part") or title
        try:
            subs = fetch_subtitles(aid, cid, headers)
        except Exception as exc:
            eprint(f"[fail] P{page_no} 获取字幕列表失败：{exc}")
            skipped += 1
            continue
        if not subs:
            print(f"[skip] P{page_no} {part}：无字幕（未登录或未开放）")
            skipped += 1
            time.sleep(args.sleep)
            continue

        chosen = choose_subtitle(subs, args.lang, args.all_langs)
        if not chosen:
            print(f"[skip] P{page_no} {part}：没有匹配语言 {args.lang}")
            skipped += 1
            continue

        for sub in chosen:
            lan = str(sub.get("lan") or "unknown")
            stem = f"{page_no:03d}_{safe_name(str(part))}_{safe_name(lan)}"
            try:
                data = load_subtitle_json(str(sub["subtitle_url"]))
                j, s, t = write_outputs(data, output_dir, stem, args.txt, args.force)
                written += 1
                print(f"[ok] P{page_no} {lan} -> {s}（{len(data.get('body') or [])} 条）")
                if t:
                    print(f"     {t}")
            except Exception as exc:
                eprint(f"[fail] P{page_no} {lan}：{exc}")
                skipped += 1
        time.sleep(args.sleep)

    print(f"完成：写入 {written} 个字幕，跳过 {skipped} 个。输出目录：{output_dir}")
    return 0 if written else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="下载 Bilibili 字幕（含 AI 字幕），或把字幕 JSON 转成 SRT。",
    )
    parser.add_argument("url", nargs="?", help="视频 URL 或 BV 号")
    parser.add_argument("-o", "--output", help="输出目录")
    parser.add_argument("--cookie", help="完整 Cookie 字符串（不推荐，会进 shell 历史）")
    parser.add_argument("--cookie-file", help="cookies.txt（Netscape）或原始 Cookie 文件")
    parser.add_argument("--lang", help="语言前缀，如 zh、zh-Hans、ai-zh")
    parser.add_argument("--all-langs", action="store_true", help="下载全部字幕语言")
    parser.add_argument("--all-pages", action="store_true", help="下载全部 P")
    parser.add_argument("--page", type=int, help="只下载第 N P（默认取 URL 的 ?p=，否则 1）")
    parser.add_argument("--list", action="store_true", help="只列出字幕，不下载")
    parser.add_argument("--txt", action="store_true", help="额外写纯文本 .txt")
    parser.add_argument("--force", action="store_true", help="覆盖已存在文件")
    parser.add_argument("--sleep", type=float, default=0.8, help="每页间隔秒数")
    parser.add_argument("--from-json", help="从已有字幕 JSON 转换，不发网络请求")
    parser.add_argument("--glob", default="*.json", help="--from-json 为目录时的匹配模式")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.from_json:
        return cmd_from_json(args)
    if not args.url:
        parser.error("需要视频 URL/BV 号，或使用 --from-json")
    if not args.output and not args.list:
        parser.error("下载字幕需要 -o/--output 输出目录")
    return cmd_download(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        eprint("已中断。")
        raise SystemExit(130)
