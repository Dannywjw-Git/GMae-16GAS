#!/usr/bin/env python3
"""
Markdown 转 PDF 工具（零依赖，用 Edge 无头模式打印）
用法: python md_to_pdf.py input.md output.pdf
"""
import sys
import os
import re
import base64
import subprocess
import tempfile


def image_to_base64(path, base_dir):
    """将图片转为 base64 data URI。"""
    full_path = os.path.join(base_dir, path) if not os.path.isabs(path) else path
    if not os.path.exists(full_path):
        return path
    ext = os.path.splitext(full_path)[1].lower().lstrip(".")
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/png")
    with open(full_path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{data}"


def parse_markdown(md_text, base_dir):
    """简单的 Markdown 转 HTML。"""
    lines = md_text.split("\n")
    html = []
    in_code = False
    code_lines = []
    in_table = False
    table_rows = []
    in_list = False
    list_type = None

    i = 0
    while i < len(lines):
        line = lines[i]

        # 代码块
        if line.strip().startswith("```"):
            if in_code:
                html.append(f"<pre><code>{''.join(code_lines)}</code></pre>")
                code_lines = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_lines.append(line + "\n")
            i += 1
            continue

        # 表格
        if "|" in line and line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            # 分隔行
            if all(re.match(r'^[-:]+$', c) for c in cells if c):
                i += 1
                continue
            if not in_table:
                in_table = True
                table_rows = []
            table_rows.append(cells)
            i += 1
            continue
        elif in_table:
            # 输出表格
            html.append("<table>")
            for ri, row in enumerate(table_rows):
                tag = "th" if ri == 0 else "td"
                html.append("<tr>" + "".join(f"<{tag}>{inline_format(c, base_dir)}</{tag}>" for c in row) + "</tr>")
            html.append("</table>")
            in_table = False
            table_rows = []

        # 分割线
        if re.match(r'^-{3,}$', line.strip()):
            html.append("<hr>")
            i += 1
            continue

        # 标题
        m = re.match(r'^(#{1,6})\s+(.*)$', line)
        if m:
            level = len(m.group(1))
            text = inline_format(m.group(2), base_dir)
            html.append(f"<h{level}>{text}</h{level}>")
            i += 1
            continue

        # 引用
        if line.strip().startswith(">"):
            text = inline_format(line.strip().lstrip(">").strip(), base_dir)
            html.append(f"<blockquote>{text}</blockquote>")
            i += 1
            continue

        # 无序列表
        if re.match(r'^[\s]*[-*]\s+', line):
            if not in_list or list_type != "ul":
                if in_list:
                    html.append(f"</{list_type}>")
                html.append("<ul>")
                in_list = True
                list_type = "ul"
            text = inline_format(re.sub(r'^[\s]*[-*]\s+', '', line), base_dir)
            html.append(f"<li>{text}</li>")
            i += 1
            continue

        # 有序列表
        if re.match(r'^[\s]*\d+\.\s+', line):
            if not in_list or list_type != "ol":
                if in_list:
                    html.append(f"</{list_type}>")
                html.append("<ol>")
                in_list = True
                list_type = "ol"
            text = inline_format(re.sub(r'^[\s]*\d+\.\s+', '', line), base_dir)
            html.append(f"<li>{text}</li>")
            i += 1
            continue

        # 空行
        if line.strip() == "":
            if in_list:
                html.append(f"</{list_type}>")
                in_list = False
                list_type = None
            i += 1
            continue

        # 普通段落
        if in_list:
            html.append(f"</{list_type}>")
            in_list = False
            list_type = None
        text = inline_format(line.strip(), base_dir)
        html.append(f"<p>{text}</p>")
        i += 1

    if in_list:
        html.append(f"</{list_type}>")
    if in_table:
        html.append("<table>")
        for ri, row in enumerate(table_rows):
            tag = "th" if ri == 0 else "td"
            html.append("<tr>" + "".join(f"<{tag}>{inline_format(c, base_dir)}</{tag}>" for c in row) + "</tr>")
        html.append("</table>")

    return "\n".join(html)


def inline_format(text, base_dir):
    """处理行内格式：粗体、图片、链接、行内代码。"""
    # 图片 ![alt](path)
    def img_repl(m):
        alt = m.group(1)
        path = m.group(2)
        src = image_to_base64(path, base_dir)
        return f'<img src="{src}" alt="{alt}" class="md-img">'
    text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', img_repl, text)

    # 链接 [text](url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    # 粗体 **text**
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)

    # 行内代码 `code`
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    return text


CSS = """
@page { size: A4; margin: 20mm 18mm; }
* { box-sizing: border-box; }
body {
    font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
    font-size: 11pt;
    line-height: 1.7;
    color: #1a1a2e;
    max-width: 100%;
    margin: 0;
    padding: 0;
}
h1 {
    font-size: 22pt;
    color: #0f3460;
    border-bottom: 3px solid #e94560;
    padding-bottom: 8px;
    margin-top: 0;
    page-break-after: avoid;
}
h2 {
    font-size: 16pt;
    color: #16213e;
    border-left: 4px solid #e94560;
    padding-left: 12px;
    margin-top: 28px;
    page-break-after: avoid;
}
h3 {
    font-size: 13pt;
    color: #0f3460;
    margin-top: 20px;
    page-break-after: avoid;
}
h4 {
    font-size: 11.5pt;
    color: #533483;
    margin-top: 16px;
    page-break-after: avoid;
}
p { margin: 8px 0; text-align: justify; }
ul, ol { margin: 8px 0; padding-left: 24px; }
li { margin: 4px 0; }
strong { color: #e94560; }
hr { border: none; border-top: 1px solid #ddd; margin: 24px 0; }
blockquote {
    border-left: 3px solid #e94560;
    background: #f8f9fa;
    margin: 12px 0;
    padding: 8px 16px;
    color: #555;
    font-style: italic;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin: 14px 0;
    font-size: 10pt;
    page-break-inside: avoid;
}
th {
    background: #16213e;
    color: white;
    padding: 8px 10px;
    text-align: left;
    font-weight: 600;
}
td {
    padding: 7px 10px;
    border-bottom: 1px solid #e0e0e0;
}
tr:nth-child(even) td { background: #f8f9fa; }
pre {
    background: #1a1a2e;
    color: #e0e0e0;
    padding: 14px;
    border-radius: 6px;
    overflow-x: auto;
    font-size: 9pt;
    line-height: 1.5;
    page-break-inside: avoid;
}
code {
    font-family: "Consolas", "Courier New", monospace;
    background: #f0f0f0;
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 9.5pt;
}
pre code { background: none; padding: 0; color: #e0e0e0; }
img.md-img {
    max-width: 100%;
    border-radius: 8px;
    margin: 12px 0;
    box-shadow: 0 2px 12px rgba(0,0,0,0.15);
    page-break-inside: avoid;
}
a { color: #e94560; text-decoration: none; }
.cover {
    text-align: center;
    padding: 60px 20px 40px;
    page-break-after: always;
}
.cover h1 {
    font-size: 28pt;
    border: none;
    color: #0f3460;
    margin-bottom: 8px;
}
.cover .subtitle {
    font-size: 14pt;
    color: #e94560;
    margin-bottom: 40px;
}
.cover .slogan {
    font-size: 16pt;
    color: #533483;
    font-style: italic;
    margin-top: 30px;
}
.cover .meta {
    margin-top: 60px;
    font-size: 10pt;
    color: #888;
}
"""


def main():
    if len(sys.argv) < 3:
        print("用法: python md_to_pdf.py input.md output.pdf")
        sys.exit(1)

    input_md = sys.argv[1]
    output_pdf = sys.argv[2]
    base_dir = os.path.dirname(os.path.abspath(input_md))

    with open(input_md, "r", encoding="utf-8") as f:
        md_text = f.read()

    # 分离标题和正文，生成封面
    lines = md_text.split("\n")
    title = "GPU Maestro"
    subtitle = ""
    body_start = 0
    for i, line in enumerate(lines):
        if line.startswith("# "):
            title = line[2:].strip()
            body_start = i + 1
            # 下一行可能是副标题
            if i + 1 < len(lines) and lines[i+1].startswith("## "):
                subtitle = lines[i+1][3:].strip()
                body_start = i + 2
            break

    body_md = "\n".join(lines[body_start:])
    body_html = parse_markdown(body_md, base_dir)

    cover_html = f"""
    <div class="cover">
        <h1>{title}</h1>
        <div class="subtitle">{subtitle}</div>
        <div class="slogan">One GPU, Infinite Models</div>
        <div class="meta">
            2026 上海开源软件应用创新大赛 · 智算云赛道<br>
            个人参赛作品 · {os.popen('date /t').read().strip()}
        </div>
    </div>
    """

    full_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>{CSS}</style>
</head>
<body>
{cover_html}
{body_html}
</body>
</html>"""

    # 写临时 HTML
    tmp_html = os.path.join(tempfile.gettempdir(), "md_to_pdf_temp.html")
    with open(tmp_html, "w", encoding="utf-8") as f:
        f.write(full_html)

    print(f"HTML 已生成: {tmp_html}")

    # 用 Edge 无头模式打印 PDF
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    edge = None
    for p in edge_paths:
        if os.path.exists(p):
            edge = p
            break

    if not edge:
        print("未找到 Edge 浏览器，请手动打开 HTML 文件并打印为 PDF")
        print(f"HTML 文件: {tmp_html}")
        sys.exit(1)

    output_abs = os.path.abspath(output_pdf)
    cmd = [
        edge,
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={output_abs}",
        tmp_html
    ]
    print(f"正在生成 PDF: {output_abs}")
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    if result.returncode == 0 and os.path.exists(output_abs):
        size = os.path.getsize(output_abs)
        print(f"PDF 生成成功: {output_abs} ({size/1024:.1f} KB)")
    else:
        print(f"PDF 生成可能失败，返回码: {result.returncode}")
        print(f"stderr: {result.stderr.decode('utf-8', errors='ignore')[:500]}")
        print(f"请手动打开 HTML: {tmp_html}")


if __name__ == "__main__":
    main()
