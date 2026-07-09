#!/usr/bin/env python3
"""从《Java 开发手册》PDF 重新生成 alibaba-manual/ reference 文件。

仅收录【强制】与【推荐】条目，跳过【参考】。

依赖:
    pip3 install pymupdf

用法:
    python3 scripts/regenerate-alibaba-manual.py
    python3 scripts/regenerate-alibaba-manual.py --pdf /path/to/manual.pdf
    python3 scripts/regenerate-alibaba-manual.py --pdf /path/to/manual.pdf --out-dir ../alibaba-manual
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import fitz  # pymupdf
except ImportError:
    print("缺少依赖 pymupdf，请执行: pip3 install pymupdf", file=sys.stderr)
    sys.exit(1)

DEFAULT_PDF = Path.home() / "Downloads/Java开发手册(黄山版).pdf"
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUT = SCRIPT_DIR.parent / "alibaba-manual"

CHAPTERS = [
    ("01-programming.md", "一、编程规约", "编程规约"),
    ("02-exception-log.md", "二、异常日志", "异常日志"),
    ("03-unit-test.md", "三、单元测试", "单元测试"),
    ("04-security.md", "四、安全规约", "安全规约"),
    ("05-mysql.md", "五、MySQL 数据库", "MySQL 数据库"),
    ("06-project-structure.md", "六、工程结构", "工程结构"),
    ("07-design.md", "七、设计规约", "设计规约"),
]

NOISE = {
    "Java 开发手册（黄山版）",
    "Java 开发手册（嵩山版）",
    "版本号",
    "制定团队",
    "更新日期",
    "备注",
    "1.7.1",
    "1.7.0",
    "全球 Java 社区开发者",
    "2022.02.03",
    "2020.08.03",
    "黄山版，新增 11 条新规约。",
    "嵩山版，首次发布前后端规约",
}

STRUCT_MARKER = re.compile(
    r"^(\([一二三四五六七八九十]+\)|[一二三四五六七]、|\d+\.【(强制|推荐|参考)】|\d+\.[^【\d])"
)
SUB_RE = re.compile(r"\(([一二三四五六七八九十]+)\)\s*([^\(\n]+)")
RULE_RE = re.compile(r"(\d+)\.【(强制|推荐|参考)】")
COMPOSITE_RE = re.compile(r"(\d+)\.(?=.{0,200}?(?:【强制】|【推荐】))")


def extract_pdf_text(pdf_path: Path) -> str:
    doc = fitz.open(str(pdf_path))
    return "\n".join(page.get_text() for page in doc)


def clean_raw(content: str) -> str:
    start = content.find("一、编程规约 \n(一) 命名风格")
    if start == -1:
        start = content.find("一、编程规约 \n(一)")
    if start == -1:
        raise ValueError("无法在 PDF 中定位正文起始位置（一、编程规约）")

    end = content.find("附 1：版本历史", start)
    if end == -1:
        raise ValueError("无法在 PDF 中定位正文结束位置（附 1：版本历史）")

    lines: list[str] = []
    for line in content[start:end].split("\n"):
        s = line.strip()
        if not s or s in NOISE or re.fullmatch(r"\d+/\d+", s):
            continue
        if re.search(r"\.{5,}", s):
            continue
        lines.append(s)

    merged: list[str] = []
    buf = ""
    for s in lines:
        if STRUCT_MARKER.match(s):
            if buf:
                merged.append(buf)
            buf = s
        else:
            buf = buf + s if buf else s
    if buf:
        merged.append(buf)
    return "\n".join(merged)


def beautify(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    for tag in ("说明：", "正例：", "反例：", "注意："):
        text = text.replace(tag, f"\n\n{tag}")
    return text.strip()


def format_chapter(title: str, body: str, stats: dict) -> tuple[str, int]:
    lines = [
        f"# {title}",
        "",
        "> 来源：《Java 开发手册》| 仅收录【强制】与【推荐】条目",
        "",
    ]
    body = re.sub(rf"^{re.escape(title)}\s*", "", body.strip())

    subs = [(m.start(), m.group(2).strip()) for m in SUB_RE.finditer(body)]
    rules: list[tuple] = []
    for m in RULE_RE.finditer(body):
        rules.append(("std", m.start(), m.group(1), m.group(2), m.end()))
    for m in COMPOSITE_RE.finditer(body):
        if any(kind == "std" and abs(pos - m.start()) < 3 for kind, pos, *_ in rules):
            continue
        rules.append(("composite", m.start(), m.group(1), "复合", m.end()))
    rules.sort(key=lambda x: x[1])

    if not rules:
        return "\n".join(lines) + "\n", 0

    current_sub = None
    count = 0
    for i, (_kind, pos, num, level, _end_tag) in enumerate(rules):
        next_pos = rules[i + 1][1] if i + 1 < len(rules) else len(body)
        chunk = body[pos:next_pos].strip()

        sub_name = None
        for spos, sname in subs:
            if spos <= pos:
                sub_name = sname
            else:
                break
        if sub_name != current_sub:
            current_sub = sub_name
            if current_sub:
                lines += ["", f"## {current_sub}", ""]

        if level == "参考":
            stats["skipped参考"] += 1
            continue
        if level == "复合":
            if "【参考】" in chunk and "【强制】" not in chunk and "【推荐】" not in chunk:
                stats["skipped参考"] += 1
                continue
            stats["强制"] += chunk.count("【强制】")
            stats["推荐"] += chunk.count("【推荐】")
            lines.append(f"### {num}. 【复合规约】")
            lines.append(beautify(chunk))
            lines.append("")
            count += 1
            stats["entries"] += 1
            continue

        stats[level] += 1
        stats["entries"] += 1
        count += 1
        body_text = RULE_RE.sub("", chunk, count=1)
        lines.append(f"### {num}. 【{level}】")
        lines.append(beautify(body_text))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n", count


def build_readme(pdf_path: Path, stats: dict) -> str:
    return f"""# 阿里巴巴 Java 开发手册 Reference

> **来源**：`{pdf_path}`  
> **收录范围**：仅【强制】与【推荐】，不含【参考】

## 章节索引

| 文件 | 章节 |
|------|------|
| [01-programming.md](01-programming.md) | 一、编程规约 |
| [02-exception-log.md](02-exception-log.md) | 二、异常日志 |
| [03-unit-test.md](03-unit-test.md) | 三、单元测试 |
| [04-security.md](04-security.md) | 四、安全规约 |
| [05-mysql.md](05-mysql.md) | 五、MySQL 数据库 |
| [06-project-structure.md](06-project-structure.md) | 六、工程结构 |
| [07-design.md](07-design.md) | 七、设计规约 |

## 统计

- 规约条目：{stats['entries']} 条
- 【强制】：{stats['强制']} 条
- 【推荐】：{stats['推荐']} 条
- 已跳过【参考】：{stats['skipped参考']} 条

## 重新生成

```bash
pip3 install pymupdf
python3 scripts/regenerate-alibaba-manual.py --pdf "{pdf_path}"
```
"""


def regenerate(pdf_path: Path, out_dir: Path) -> dict:
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF 不存在: {pdf_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    raw = extract_pdf_text(pdf_path)
    text = clean_raw(raw)

    chapter_bodies: dict[str, str] = {}
    for i, (fname, marker, _title) in enumerate(CHAPTERS):
        idx = text.find(marker)
        if idx == -1:
            raise ValueError(f"未找到章节标记: {marker}")
        nidx = (
            text.find(CHAPTERS[i + 1][1], idx + len(marker))
            if i + 1 < len(CHAPTERS)
            else len(text)
        )
        chapter_bodies[fname] = text[idx:nidx]

    stats = {"强制": 0, "推荐": 0, "skipped参考": 0, "entries": 0}
    for fname, _marker, title in CHAPTERS:
        md, entry_count = format_chapter(title, chapter_bodies[fname], stats)
        (out_dir / fname).write_text(md, encoding="utf-8")
        print(f"  {fname}: {entry_count} 条")

    (out_dir / "README.md").write_text(build_readme(pdf_path.resolve(), stats), encoding="utf-8")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="从 Java 开发手册 PDF 生成 alibaba-manual reference")
    parser.add_argument(
        "--pdf",
        type=Path,
        default=DEFAULT_PDF,
        help=f"PDF 路径（默认: {DEFAULT_PDF}）",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT,
        help=f"输出目录（默认: {DEFAULT_OUT}）",
    )
    args = parser.parse_args()

    print(f"PDF: {args.pdf}")
    print(f"输出: {args.out_dir}")
    stats = regenerate(args.pdf, args.out_dir)
    print(
        f"完成: {stats['entries']} 条规约 "
        f"（强制 {stats['强制']} / 推荐 {stats['推荐']} / 跳过参考 {stats['skipped参考']}）"
    )


if __name__ == "__main__":
    main()
