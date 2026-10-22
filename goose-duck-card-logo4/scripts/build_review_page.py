# -*- coding: utf-8 -*-
"""build_review_page.py — 从 manifest 生成候选审核页 HTML（goose-duck-card-logo4 skill 专用）

用法:
    python build_review_page.py <manifest_审核.json 路径> [--out <输出html路径>] [--no-open]

manifest schema (UTF-8 JSON):
{
  "title": "巫医 logo 重设计 · 候选审核页（共 N 张）",
  "subtitle": "规范 <style文件> ｜ 模型 GPT Image 2.5 Sunburst · medium · 1K · 1:1 ｜ 评估口径说明…",
  "refs": [                      // 可选, 页面顶部对照区（官方基准 / 现用图等）
    {"label": "官方基准", "path": "D:\\...\\official_camps_v3\\duck\\duck_巫医.png"},
    {"label": "现用图",   "path": "D:\\...\\chibi_style_v2\\duck\\duck_巫医.png"}
  ],
  "items": [                     // 按推荐顺序排 rank
    {
      "rank": 1,
      "name": "巫医_A_歪帽单旋涡_1_1",
      "path": "D:\\...\\工坊\\批次\\<批次>\\images\\巫医_A_歪帽单旋涡_1_1.png",
      "verdict": "一句话结论 + 量化指标 + 点评（可含 \\n）",
      "anchors": "黑宽檐巫帽✓ 紫旋涡眼✓ …",     // 可选
      "risk": "风险/扣分点说明",                 // 可选
      "badge": "★ 首选"                          // 可选, 默认 rank1=★ 首选, 其余=☆ 备选
    }
  ]
}

行为:
  - 批次目录 = manifest 所在目录; 所有图片以相对路径引用（file:// 直开即可显示）
  - refs 里位于批次目录之外的图会自动复制到 <批次>\\assets\\ref_<label>.png
  - 每张候选图渲染 200px 原图 + 48px / 96px 小图实测（小程序九宫格可读性）
  - 输出默认 <批次>\\审核页.html, --out 可自定义; 默认完成后自动用浏览器打开
"""
import argparse
import json
import os
import re
import shutil
import sys
import urllib.parse
import webbrowser

CSS = """
body{margin:0;padding:28px;background:#f4f4f6;font-family:"Microsoft YaHei",system-ui,sans-serif;color:#1c1c1e}
h1{font-size:22px;margin:0 0 6px} .sub{color:#6b6b70;font-size:13px;margin-bottom:18px;line-height:1.6}
.refs{display:flex;gap:14px;flex-wrap:wrap;background:#fff;padding:16px;border-radius:12px;margin-bottom:22px}
.refs figure{margin:0;width:170px;text-align:center;font-size:12px}
.refs img{width:170px;height:170px;object-fit:contain;background:
 repeating-conic-gradient(#e6e6e6 0% 25%, #fff 0% 50%) 0 0/20px 20px;border-radius:8px}
.card{display:flex;gap:18px;background:#fff;border-radius:12px;padding:16px;margin-bottom:14px;
 box-shadow:0 1px 3px rgba(0,0,0,.08);align-items:flex-start}
.card.top{outline:3px solid #f5a623}
.thumbs{display:flex;gap:10px;flex:0 0 auto}
.thumbs figure{margin:0;text-align:center;font-size:11px;color:#8a8a8e}
.thumbs img{width:200px;height:200px;object-fit:contain;border-radius:8px;background:
 repeating-conic-gradient(#e6e6e6 0% 25%, #fff 0% 50%) 0 0/20px 20px}
.mini{width:48px!important;height:48px!important} .mini96{width:96px!important;height:96px!important}
.miniwrap{background:#2b2b30!important;border-radius:8px;padding:0}
.meta{flex:1;min-width:0} .meta h2{font-size:16px;margin:0 0 8px} .rank{color:#f5a623}
.meta h2 em{font-size:12px;font-style:normal;background:#1c1c1e;color:#fff;padding:2px 8px;
 border-radius:10px;margin-left:6px}
.verdict{font-size:14px;margin:0 0 8px;white-space:pre-line;line-height:1.6}
.kv{font-size:13px;margin:4px 0;color:#3a3a3e;line-height:1.6}
.kv b{display:inline-block;min-width:74px;color:#8a8a8e;font-weight:600}
.risk b{color:#c0392b} .path{font-size:11px;color:#a0a0a5;word-break:break-all;margin-top:10px}
"""


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def rel_url(batch_dir, abs_path):
    """把绝对路径转成相对 batch_dir 的 URL 编码路径; 跨盘/外部路径回退 file:/// 绝对 URL"""
    abs_path = os.path.normpath(abs_path)
    try:
        rel = os.path.relpath(abs_path, batch_dir)
        if rel.startswith(".."):
            raise ValueError
    except ValueError:
        return urllib.parse.quote(abs_path.replace("\\", "/"))
    return urllib.parse.quote(rel.replace("\\", "/"))


def safe_name(label):
    return re.sub(r'[\\/:*?"<>|\s]+', "_", label)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--out")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    mpath = os.path.abspath(args.manifest)
    if not os.path.isfile(mpath):
        print(f"[ERROR] manifest 不存在: {mpath}")
        sys.exit(1)
    batch_dir = os.path.dirname(mpath)
    with open(mpath, "r", encoding="utf-8") as f:
        m = json.load(f)

    title = m.get("title", "候选审核页")
    items = m.get("items", [])
    if not items:
        print("[ERROR] manifest.items 为空")
        sys.exit(1)

    parts = ['<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">',
             f"<title>{esc(title)}</title><style>{CSS}</style></head><body>",
             f"<h1>{esc(title)}</h1>"]
    if m.get("subtitle"):
        parts.append(f'<div class="sub">{esc(m["subtitle"])}</div>')

    # refs 对照区
    refs = m.get("refs") or []
    if refs:
        parts.append('<div class="refs">')
        assets_dir = os.path.join(batch_dir, "assets")
        for r in refs:
            src = os.path.normpath(r["path"])
            label = r.get("label", "对照")
            if not os.path.isfile(src):
                parts.append(f'<figure><div style="width:170px;height:170px;display:flex;'
                             f'align-items:center;justify-content:center;background:#fee;'
                             f'border-radius:8px;font-size:12px;color:#c0392b">缺失</div>'
                             f'<figcaption>{esc(label)}<br>{esc(src)}</figcaption></figure>')
                continue
            # 批次目录外的图复制进 assets/, 保证审核页自包含可迁移
            if os.path.normcase(os.path.dirname(src)).startswith(os.path.normcase(batch_dir)):
                url = rel_url(batch_dir, src)
            else:
                os.makedirs(assets_dir, exist_ok=True)
                dst = os.path.join(assets_dir, f"ref_{safe_name(label)}.png")
                if os.path.normcase(os.path.abspath(dst)) != os.path.normcase(src):
                    shutil.copy2(src, dst)
                url = rel_url(batch_dir, dst)
            parts.append(f'<figure class="ref"><img src="{url}">'
                         f"<figcaption>{esc(label)}</figcaption></figure>")
        parts.append("</div>")

    # 候选卡片
    missing = []
    for it in sorted(items, key=lambda x: x.get("rank", 999)):
        img = os.path.normpath(it["path"])
        name = it.get("name") or os.path.splitext(os.path.basename(img))[0]
        rank = it.get("rank", "-")
        badge = it.get("badge") or ("★ 首选" if rank == 1 else "☆ 备选")
        url = rel_url(batch_dir, img)
        if not os.path.isfile(img):
            missing.append(img)
        top = " top" if rank == 1 else ""
        parts.append(f'<section class="card{top}"><div class="thumbs">'
                     f'<figure><img src="{url}" alt="{esc(name)}"><figcaption>原图 200px</figcaption></figure>'
                     f'<figure><img class="mini miniwrap" src="{url}" alt=""><figcaption>48px 深底实测</figcaption></figure>'
                     f'<figure><img class="mini96" src="{url}" alt=""><figcaption>96px 实测</figcaption></figure>'
                     f'</div><div class="meta">'
                     f'<h2><span class="rank">#{esc(rank)}</span> {esc(name)} <em>{esc(badge)}</em></h2>'
                     f'<p class="verdict">{esc(it.get("verdict", ""))}</p>')
        if it.get("anchors"):
            parts.append(f'<p class="kv"><b>识别锚点</b>{esc(it["anchors"])}</p>')
        if it.get("risk"):
            parts.append(f'<p class="kv risk"><b>风险/扣分</b>{esc(it["risk"])}</p>')
        parts.append(f'<p class="path">{esc(img)}</p></div></section>')

    parts.append("</body></html>")

    out = args.out or os.path.join(batch_dir, "审核页.html")
    out = os.path.abspath(out)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))

    print(f"审核页已生成: {out}  (共 {len(items)} 张候选)")
    for p in missing:
        print(f"[WARN] 候选图缺失(卡片仍占位): {p}")
    if not args.no_open:
        webbrowser.open("file:///" + out.replace("\\", "/"))


if __name__ == "__main__":
    main()
