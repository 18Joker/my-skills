# -*- coding: utf-8 -*-
"""validate_tasks.py — photogpt 生图任务 JSON 提交前校验（goose-duck-card-logo4 skill 专用）

用法:
    python validate_tasks.py <任务JSON路径> [--batch <批次目录>]

校验项:
    1. 顶层是 JSON 数组、UTF-8 可解析
    2. 每任务 prompt 非空; 中文 prompt 内不得出现半角双引号(应改全角「“”」)
    3. mode 合法; 默认组合四字段显式齐全 (gpt_image_2_5 + Sunburst + medium + 1K)
       —— 缺任一字段记 ERROR
    4. aspect_ratio 按 mode 校验合法值 (gpt_image_2_5 仅 9 个)
    5. quality/resolution/output_num 取值合法
    6. input_urls 数量上限 + 本地路径存在性
    7. out_path: 绝对路径、.png 结尾、位于 --batch 目录内(给了 batch 时)、批内不重复
    8. 生成参数指纹去重 (与执行器同口径), 重复任务记 ERROR
    9. task_id 批内唯一 (WARN)
   10. 积分预估 (优先读 photogpt pricing.json, 缺失回退内置 2026-09-26 价目镜像)

退出码: 0=通过(可含 WARN), 1=存在 ERROR
"""
import argparse
import hashlib
import json
import os
import sys

PRICING_FALLBACK = {
    # 2026-09-26 调价后镜像 (TASKS_JSON_FORMAT.md 第三章)
    "gpt_image_2_5": {
        "low": {"1K": 3, "2K": 3, "4K": 4},
        "medium": {"1K": 4, "2K": 4, "4K": 6},
        "high": {"1K": 12, "2K": 12, "4K": 24},
    },
    "gpt_image_2": {
        "low": {"1K": 3, "2K": 5, "4K": 5},
        "medium": {"1K": 12, "2K": 24, "4K": 24},
        "high": {"1K": 26, "2K": 50, "4K": 50},
    },
    "poster_fixed": 4,
}
PRICING_JSON = r"D:\program\project\media-automation\tools\photogpt_playwright\pricing.json"

AR_25 = {"自动", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"}
AR_FULL = AR_25 | {"5:4", "4:5", "2:1", "1:2", "9:21"}
MODES = {"poster", "gpt_image_2", "gpt_image_2_5"}
QUALITIES = {"low", "medium", "high"}
RESOLUTIONS = {"1K", "2K", "4K"}
VARIANTS = {"flare", "sunburst"}

errors = []
warns = []


def E(msg):
    errors.append(msg)


def W(msg):
    warns.append(msg)


def fingerprint(t):
    keys = ["mode", "prompt", "aspect_ratio", "quality", "resolution",
            "output_num", "input_urls", "poster_style", "model_variant"]
    payload = json.dumps({k: t.get(k) for k in keys}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def estimate_cost(t, pricing):
    mode = t.get("mode", "poster")
    num = int(t.get("output_num", 1))
    if mode == "poster":
        return pricing.get("poster_fixed", 4) * num
    q = t.get("quality", "medium")
    r = t.get("resolution", "1K")
    table = pricing.get(mode)
    if not table:
        return None
    try:
        return int(table[q][r]) * num
    except (KeyError, TypeError, ValueError):
        return None


def load_pricing():
    """载入价目表, 统一成 {mode: {quality: {res: cost}}, 'poster_fixed': int} 结构。"""
    pricing = {k: v for k, v in PRICING_FALLBACK.items()}
    if not os.path.isfile(PRICING_JSON):
        W("未找到 photogpt pricing.json, 用内置 2026-09-26 价目镜像估算")
        return pricing
    try:
        with open(PRICING_JSON, "r", encoding="utf-8") as f:
            pj = json.load(f)
        modes = pj.get("modes", {}) if isinstance(pj, dict) else {}
        for m in ("gpt_image_2_5", "gpt_image_2"):
            entry = modes.get(m)
            if isinstance(entry, dict) and isinstance(entry.get("unit_cost"), dict):
                pricing[m] = entry["unit_cost"]
        poster = modes.get("poster")
        if isinstance(poster, dict) and poster.get("fixed_unit_cost"):
            pricing["poster_fixed"] = int(poster["fixed_unit_cost"])
    except Exception as ex:
        W(f"pricing.json 读取失败, 用内置价目镜像: {ex}")
    return pricing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks_json")
    ap.add_argument("--batch", help="批次目录绝对路径; out_path 必须位于其内")
    args = ap.parse_args()

    # --- 载入 JSON ---
    try:
        with open(args.tasks_json, "r", encoding="utf-8") as f:
            raw = f.read()
        tasks = json.loads(raw)
    except UnicodeDecodeError:
        print("[ERROR] 文件不是 UTF-8 编码")
        sys.exit(1)
    except json.JSONDecodeError as ex:
        print(f"[ERROR] JSON 解析失败: {ex}")
        sys.exit(1)
    if not isinstance(tasks, list):
        print("[ERROR] 顶层必须是 JSON 数组")
        sys.exit(1)
    if not tasks:
        print("[ERROR] 任务数组为空")
        sys.exit(1)

    # --- pricing ---
    pricing = load_pricing()

    batch_norm = None
    if args.batch:
        batch_norm = os.path.normcase(os.path.normpath(args.batch))

    seen_fp = {}
    seen_out = {}
    seen_tid = {}
    total_cost = 0
    unknown_cost = 0

    for i, t in enumerate(tasks):
        tag = t.get("task_id") or f"#{i}"
        if not isinstance(t, dict):
            E(f"[{tag}] 任务不是对象")
            continue

        # prompt
        prompt = t.get("prompt", "")
        if not isinstance(prompt, str) or not prompt.strip():
            E(f"[{tag}] prompt 缺失或为空")
        else:
            if '"' in prompt:
                E(f"[{tag}] prompt 含半角双引号, 中文语境必须改全角「“”」")
            if len(prompt) < 40:
                W(f"[{tag}] prompt 过短({len(prompt)}字), 检查是否遗漏规范段落")

        # mode
        mode = t.get("mode", "poster")
        if mode not in MODES:
            E(f"[{tag}] mode 非法: {mode}")
            continue

        # 默认组合
        if mode == "gpt_image_2_5":
            variant = t.get("model_variant")
            quality = t.get("quality")
            resolution = t.get("resolution")
            miss = []
            if variant is None:
                miss.append("model_variant(须显式 Sunburst)")
            elif str(variant).lower() not in VARIANTS:
                E(f"[{tag}] model_variant 非法: {variant}")
            elif str(variant).lower() != "sunburst":
                W(f"[{tag}] model_variant={variant}, 非默认组合推荐值 Sunburst")
            if quality is None:
                miss.append("quality(须显式 medium)")
            if resolution is None:
                miss.append("resolution(须显式 1K)")
            if "mode" not in t:
                miss.append("mode(须显式 gpt_image_2_5)")
            if miss:
                E(f"[{tag}] 默认组合字段未显式写出: {', '.join(miss)}")
            if quality == "high":
                W(f"[{tag}] quality=high 单价 12 分/张, 超每日免费额度, 确认是用户要求")
        else:
            W(f"[{tag}] mode={mode} 偏离默认组合(gpt_image_2_5), 确认有明确理由并在方案摘要说明")

        # aspect_ratio
        ar = t.get("aspect_ratio")
        if mode == "gpt_image_2_5" and ar is not None and ar not in AR_25:
            E(f"[{tag}] gpt_image_2_5 不支持 aspect_ratio={ar} (仅: {' '.join(sorted(AR_25))})")
        elif mode in ("gpt_image_2", "poster") and ar is not None and ar not in AR_FULL:
            E(f"[{tag}] aspect_ratio 非法: {ar}")

        # quality / resolution / output_num
        q = t.get("quality")
        if q is not None and q not in QUALITIES:
            E(f"[{tag}] quality 非法: {q}")
        if mode == "poster" and (q is not None or t.get("resolution") is not None):
            W(f"[{tag}] poster 模式忽略 quality/resolution, 建议删掉")
        r = t.get("resolution")
        if r is not None and r not in RESOLUTIONS:
            E(f"[{tag}] resolution 非法: {r}")
        on = t.get("output_num", 1)
        if not isinstance(on, int) or not (1 <= on <= 4):
            E(f"[{tag}] output_num 必须是 1~4 的整数: {on}")
            on = 1

        # input_urls
        urls = t.get("input_urls") or []
        if not isinstance(urls, list):
            E(f"[{tag}] input_urls 必须是数组")
            urls = []
        limit = 1 if mode == "poster" else 4
        if len(urls) > limit:
            E(f"[{tag}] {mode} 参考图上限 {limit} 张, 实际 {len(urls)}")
        for u in urls:
            if isinstance(u, str) and not u.lower().startswith(("http://", "https://")):
                if not os.path.isfile(u):
                    E(f"[{tag}] 参考图不存在(任务将直接 failed 不提交): {u}")

        # out_path
        op = t.get("out_path")
        if not op:
            W(f"[{tag}] 未写 out_path, 将按 task_id 落到 photogpt output 目录(违反批次归集规范)")
        else:
            if not os.path.isabs(op):
                E(f"[{tag}] out_path 必须是绝对路径(本 skill 规范): {op}")
            if not op.lower().endswith(".png"):
                W(f"[{tag}] out_path 建议带 .png 扩展名: {op}")
            if batch_norm:
                opn = os.path.normcase(os.path.normpath(os.path.dirname(op)))
                if not opn.startswith(batch_norm):
                    E(f"[{tag}] out_path 不在批次目录内: {op}")
            key = os.path.normcase(os.path.normpath(op))
            if key in seen_out:
                E(f"[{tag}] out_path 与 [{seen_out[key]}] 重复: {op}")
            seen_out[key] = tag

        # task_id / 指纹
        if "task_id" in t:
            if t["task_id"] in seen_tid:
                W(f"[{tag}] task_id 与 #{seen_tid[t['task_id']]} 重复(不影响去重但难排查)")
            seen_tid[t["task_id"]] = i
        fp = fingerprint(t)
        if fp in seen_fp:
            E(f"[{tag}] 生成参数指纹与 [{seen_fp[fp]}] 完全相同, 会被执行器去重静默跳过")
        seen_fp[fp] = tag

        cost = estimate_cost(t, pricing)
        if cost is None:
            unknown_cost += on
            W(f"[{tag}] 价目表查不到 {mode}/{q}/{r}, 该任务消耗以生成按钮实时读数为准")
        else:
            total_cost += cost

    # --- 汇总 ---
    print(f"任务数: {len(tasks)}  |  预估总消耗: {total_cost} 积分"
          + (f" (+{unknown_cost} 张无法预估)" if unknown_cost else ""))
    print(f"每日免费额度 10 分/账号, 预估需要至少 {(total_cost + 9) // 10 if total_cost else '?'} 个账号额度或分日执行")
    for w in warns:
        print(f"[WARN] {w}")
    for e in errors:
        print(f"[ERROR] {e}")
    if errors:
        print(f"\n校验失败: {len(errors)} 个 ERROR, 修复后重跑, 禁止带病提交")
        sys.exit(1)
    print(f"\n校验通过 (WARN {len(warns)} 个, 逐条确认后可提交)")


if __name__ == "__main__":
    main()
