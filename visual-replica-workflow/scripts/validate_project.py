#!/usr/bin/env python3
"""只读、离线的复刻阶段校验；机器检查绝不代替用户视觉验收。"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path, PureWindowsPath

from compare_images import compare, crop_rgba, read_png
from inspect_assets import inspect

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 512
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}", re.ASCII)
HASH_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
METHODS = {"html-css", "svg", "reuse-image", "crop-image", "remove-background", "generate-image", "undetermined"}
IMAGE_METHODS = {"reuse-image", "crop-image", "remove-background", "generate-image"}
RUN_FIELDS = {"status", "freeze", "verified", "verificationEvidence"}
LIMITATIONS = [
    "confirmedBy、审批和边缘检查仅是声明一致性；宿主必须核对实际聊天原话或消息引用，不能证明真实用户确认。",
    "PNG Alpha 仅证明透明与非空内容，不能证明边缘质量或视觉可用性。",
    "几何和像素指标仅用于定位，不自动判定视觉质量；旋转后的 DOM AABB 不是旋转局部边界，不作简单坐标校正。",
    "checkpoint 只能证实明列文件；不能证明未追踪的新增文件，宿主还须核对完整 diff。",
    "allowedProperties/allowedElementIds 是授权声明；不解析代码修改范围，宿主须核对允许文件内的实际属性和元素 diff。",
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def number(value, label, positive=False):
    require(type(value) in (int, float), f"{label} 必须是有限数值")
    require(math.isfinite(value) and (not positive or value > 0), f"{label} 必须是有限{'正' if positive else ''}数值")
    return value


def positive_int(value, label):
    require(type(value) is int and value > 0, f"{label} 必须是正整数")
    return value


def mapping(value, label):
    require(isinstance(value, dict), f"{label} 必须是对象")
    require(len(value) <= MAX_ITEMS, f"{label} 超过 {MAX_ITEMS} 项")
    return value


def unique_strings(value, label, known=None, nonempty_list=False):
    require(isinstance(value, list) and len(value) <= MAX_ITEMS, f"{label} 必须是至多 {MAX_ITEMS} 项的数组")
    require(not nonempty_list or bool(value), f"{label} 不得为空")
    require(all(nonempty(v) for v in value), f"{label} 必须包含非空字符串")
    require(len(set(value)) == len(value), f"{label} 含重复项")
    require(known is None or set(value) <= set(known), f"{label} 引用不存在的 ID")
    return value


def safe_file(root, value, relative=False):
    require(isinstance(value, (str, Path)) and bool(str(value)), "文件路径必须非空")
    text = value.as_posix() if isinstance(value, Path) else value
    require("\\" not in text, "文件路径须使用正斜杠")
    path = Path(text)
    require(".." not in path.parts, "文件路径不得包含 ..")
    require(not relative or (not path.is_absolute() and not PureWindowsPath(text).drive), "清单文件必须是根相对路径")
    candidate = path if path.is_absolute() else root / path
    require(candidate.is_relative_to(root), "文件路径逃逸 project-root")
    resolved = candidate.resolve(strict=True)
    require(resolved.is_relative_to(root), "符号链接逃逸 project-root")
    require(resolved.is_file(), f"不是普通文件：{text}")
    return resolved


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def json_shape(value, depth=0):
    require(depth <= 32, "JSON 嵌套超过安全上限")
    if isinstance(value, (dict, list)):
        require(len(value) <= MAX_ITEMS, f"JSON 容器超过 {MAX_ITEMS} 项")
        for item in (value.values() if isinstance(value, dict) else value):
            json_shape(item, depth + 1)
    elif isinstance(value, float):
        number(value, "JSON 数值")


def json_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"JSON 重复键：{key}")
        result[key] = value
    return result


def load_json(path):
    require(path.stat().st_size <= MAX_JSON_BYTES, "JSON 超过 2MB 上限")
    with path.open("rb") as stream:
        data = stream.read(MAX_JSON_BYTES + 1)
    require(len(data) <= MAX_JSON_BYTES, "JSON 超过 2MB 上限")
    value = json.loads(data.decode("utf-8-sig"), object_pairs_hook=json_pairs)
    json_shape(value)
    return mapping(value, str(path))


def validate_file_references(root, value, base=None):
    """只检查 JSON 中明列的文件字段；inspection 的预览相对报告目录。"""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"file", "sourceFile", "inspectionFile", "fontFile"}:
                if base is None:
                    safe_file(root, item, relative=True)
                else:
                    require(nonempty(item) and "\\" not in item and ".." not in Path(item).parts
                            and not Path(item).is_absolute() and not PureWindowsPath(item).drive, "inspection 文件须合法相对路径，不得 .. 逃逸")
                    safe_file(root, base / item)
            else:
                validate_file_references(root, item, base)
    elif isinstance(value, list):
        for item in value:
            validate_file_references(root, item, base)


def plan_digest(analysis):
    """SHA256：canonical JSON 的全部规划字段，仅排除 review 和元素四个运行字段。"""
    mapping(analysis, "analysis")
    plan = {key: value for key, value in analysis.items() if key != "review"}
    if isinstance(plan.get("elements"), list):
        plan["elements"] = [{k: v for k, v in mapping(item, "element").items() if k not in RUN_FIELDS}
                            for item in plan["elements"]]
    json_shape(plan)
    canonical = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_analysis(root, analysis, stage, report):
    require(analysis.get("schemaVersion") == "1", "schemaVersion 必须为字符串 1")
    positive_int(analysis.get("revision"), "revision")
    require(analysis.get("coordinateSpace") == "source-pixels", "coordinateSpace 必须为 source-pixels")
    canvas = mapping(analysis.get("canvas"), "canvas")
    sw, sh, vw, vh = [positive_int(canvas.get(k), f"canvas.{k}") for k in
                      ("sourceWidth", "sourceHeight", "viewportWidth", "viewportHeight")]
    dpr = number(canvas.get("deviceScaleFactor"), "deviceScaleFactor", True)
    require(sw == vw * dpr and sh == vh * dpr, "源物理尺寸必须精确等于 viewport * DPR，不隐式取整")
    source = safe_file(root, analysis.get("sourceFile"), relative=True)
    width, height, _ = read_png(source)
    require((width, height) == (sw, sh), "源 PNG 尺寸与 canvas 不一致")
    actual_hash = sha256_file(source)
    report["source_sha256"] = actual_hash
    declared_hash = analysis.get("sourceSha256")
    if declared_hash is None and stage == "analysis":
        report["warnings"].append("sourceSha256 缺失；进入 implementation 前必须记录实际摘要并重新确认")
    else:
        require(isinstance(declared_hash, str) and HASH_RE.fullmatch(declared_hash), "sourceSha256 缺失或无效")
        require(declared_hash == actual_hash, "sourceSha256 与源文件不匹配")
    elements = analysis.get("elements")
    require(isinstance(elements, list) and 1 <= len(elements) <= MAX_ITEMS, "elements 必须是 1 到 512 项的数组")
    by_id = {}
    for element in elements:
        e = mapping(element, "element")
        eid = e.get("id")
        require(isinstance(eid, str) and ID_RE.fullmatch(eid) and eid not in by_id, "元素 ID 无效或重复")
        by_id[eid] = e
        require(nonempty(e.get("type")), f"{eid}.type 必须非空")
        require("parentId" in e and (e["parentId"] is None or isinstance(e["parentId"], str)), f"{eid}.parentId 必须是 string|null")
        x, y, w, h = [number(e.get(k), f"{eid}.{k}", k in ("width", "height")) for k in ("x", "y", "width", "height")]
        if x < 0 or y < 0 or x + w > sw or y + h > sh:
            require(e.get("allowOverflow") is True and nonempty(e.get("evidence")), f"{eid} 越界须 allowOverflow:true 和 evidence")
        if "relative" in e:
            relative = mapping(e["relative"], f"{eid}.relative")
            for key, expected in zip(("x", "y", "width", "height"), (x / sw, y / sh, w / sw, h / sh)):
                require(abs(number(relative.get(key), f"relative.{key}") - expected) <= 1e-4, f"{eid}.relative.{key} 与源比率不一致")
        number(e.get("rotation"), f"{eid}.rotation")
        require(e.get("source") in {"measured", "estimated", "derived", "user-provided"}, f"{eid}.source 无效")
        require(e.get("confidence") in {"high", "medium", "low"}, f"{eid}.confidence 无效")
        require(type(e.get("verified")) is bool and type(e.get("freeze")) is bool, f"{eid}.verified/freeze 必须是 bool")
        require(e.get("status") in {"unimplemented", "implemented", "pending-review", "approved"}, f"{eid}.status 无效")
        require(e.get("implementation") in METHODS, f"{eid}.implementation 无效")
        if e["verified"] or e["freeze"]:
            require(nonempty(e.get("verificationEvidence")), f"{eid} 缺少 verificationEvidence")
        if e["freeze"]:
            require(e["status"] == "approved", f"{eid} freeze 必须 status approved")
        if not e["verified"] or e["confidence"] != "high" or e["type"] == "unknown":
            report["warnings"].append(f"{eid} 为候选/近似项，仍需用户检查")
    for eid in by_id:
        chain, current = set(), eid
        while current is not None:
            require(current in by_id, f"{eid}.parentId 不存在")
            require(current not in chain, f"{eid} 的 parentId 构成循环")
            chain.add(current)
            current = by_id[current]["parentId"]
    report["analysis_digest"] = plan_digest(analysis)
    return by_id, source


def validate_review(analysis, elements, digest, stage, report):
    review = analysis.get("review")
    if review is None and stage == "analysis":
        return {}, []
    review = mapping(review, "review")
    require(review.get("status") in {"pending", "approved"}, "review.status 必须 pending|approved")
    if stage == "analysis":
        for key in ("approvedElementIds", "allowGeneratedAssetIds", "allowRasterizedTextIds"):
            if key in review:
                unique_strings(review[key], key, elements)
        if (review.get("revision") != analysis["revision"] or review.get("analysisDigest") != digest
                or review.get("confirmedBy") != "user" or not nonempty(review.get("evidence"))):
            report["warnings"].append("候选 review 尚不完整或已过期；实施前必须重新取得完整确认")
        return review, []
    require(type(review.get("revision")) is int and review["revision"] == analysis["revision"], "review revision 已过期")
    require(review.get("analysisDigest") == digest, "review analysisDigest 已过期")
    require(review.get("confirmedBy") == "user" and nonempty(review.get("evidence")), "review 须声明 user 及实际聊天证据")
    selected = unique_strings(review.get("approvedElementIds"), "approvedElementIds", elements, stage != "analysis")
    unique_strings(review.get("allowGeneratedAssetIds"), "allowGeneratedAssetIds", elements)
    unique_strings(review.get("allowRasterizedTextIds"), "allowRasterizedTextIds", elements)
    if stage != "analysis":
        require(review["status"] == "approved", "未取得用户确认，禁止实施")
        for eid in selected:
            require(elements[eid]["type"] != "unknown" and elements[eid]["implementation"] != "undetermined", f"{eid} unknown/undetermined 不可实施")
    return review, selected


def validate_manifests(root, texts, assets, elements, selected, review, report, strict):
    asset_paths = {}
    for aid, value in assets.items():
        require(ID_RE.fullmatch(aid), "asset ID 无效")
        a = mapping(value, f"asset {aid}")
        path = safe_file(root, a.get("file"), relative=True)
        asset_paths[aid] = path
        require(a.get("source") in {"extracted", "provided", "generated"}, f"asset {aid}.source 无效")
        for field in ("approved", "approximate", "transparentBackground", "alphaVerified", "edgeChecked"):
            require(type(a.get(field)) is bool, f"asset {aid}.{field} 必须 bool")
        require(isinstance(a.get("approvalEvidence"), str), f"asset {aid}.approvalEvidence 必须字符串")
        if a["approved"]:
            require(nonempty(a["approvalEvidence"]), f"asset {aid} 审批缺证据")
        if "inspectionFile" in a:
            inspection_path = safe_file(root, a["inspectionFile"], relative=True)
            inspection = load_json(inspection_path)
            validate_file_references(root, inspection, inspection_path.parent)
            if "asset" in inspection:
                require(safe_file(root, inspection["asset"]) == path, f"asset {aid} inspection 来源不一致")
    for eid, value in texts.items():
        require(eid in elements, "text-manifest 引用不存在的元素")
        t = mapping(value, f"text {eid}")
        require(isinstance(t.get("text"), str), f"text {eid}.text 必须字符串")
        require(t.get("source") in {"ocr", "vision", "user-provided"}, f"text {eid}.source 无效")
        for field in ("verified", "requiredEditable", "fontVerified", "lineBreaksVerified"):
            require(type(t.get(field)) is bool, f"text {eid}.{field} 必须 bool")
        require(t.get("renderMode") in {"text", "image"}, f"text {eid}.renderMode 无效")
        if t["verified"]:
            require(nonempty(t.get("verificationEvidence")), f"text {eid} 核验缺证据")
            require("text" not in elements[eid] or elements[eid]["text"] == t["text"], f"text {eid} 内容不一致")
        if not t["fontVerified"]:
            report["warnings"].append(f"{eid} 字体未核验；不据此判定视觉质量")
    if not strict:
        return asset_paths
    for eid in selected:
        e = elements[eid]
        raster = False
        if e["type"] == "text":
            require(eid in texts, f"text {eid} 缺少 text-manifest")
            t = texts[eid]
            require(t["verified"], f"text {eid} 尚未核验")
            raster = t["renderMode"] == "image"
            require(raster or e["implementation"] not in IMAGE_METHODS, f"text {eid} 用图方法与 renderMode:text 不一致")
            if raster:
                require(not t["requiredEditable"], f"text {eid} 必须可编辑，不能 image")
                require(eid in review["allowRasterizedTextIds"], f"text {eid} 未获栅格化授权")
        if e["implementation"] in IMAGE_METHODS or raster or "assetId" in e:
            aid = e.get("assetId", eid)
            require(isinstance(aid, str) and aid in assets, f"{eid} 缺少对应 asset")
            a = assets[aid]
            require(a["approved"] and nonempty(a["approvalEvidence"]), f"{eid} 素材未获批准")
            if e["implementation"] == "generate-image" or a["source"] == "generated" or a["approximate"] or e.get("approximate") is True:
                require(eid in review["allowGeneratedAssetIds"], f"{eid} 生成/近似素材未授权（须元素 ID）")
            needs_alpha = (a["transparentBackground"] or e.get("transparentBackground") is True
                           or e.get("requiresTransparency") is True or e["implementation"] == "remove-background")
            if needs_alpha:
                require(a["transparentBackground"] and a["alphaVerified"] and a["edgeChecked"], f"{eid} 缺少透明或边缘声明")
                facts = inspect(*read_png(asset_paths[aid]))
                require(facts["hasRealTransparency"] and facts["contentBounds"] is not None, f"{eid} PNG 没有真实 Alpha 或非空内容")
                report.setdefault("alpha_checks", {})[eid] = facts
    return asset_paths


def validate_capture(analysis, elements, selected, current, capture, report):
    require(current is not None and capture is not None, "capture 阶段须 current 与 capture-report")
    width, height, pixels = read_png(current)
    canvas = analysis["canvas"]
    require((width, height) == (canvas["sourceWidth"], canvas["sourceHeight"]), "当前 PNG 与源物理尺寸不一致")
    require(capture.get("png_sha256") == sha256_file(current), "capture png_sha256 不匹配")
    require(capture.get("status") == "captured" and capture.get("readiness_verified") is True, "capture 没有严格就绪证明")
    require(capture.get("backend") in {"playwright", "host"}, "CLI 不能升级为严格就绪")
    require(type(capture.get("actual_width")) is int and type(capture.get("actual_height")) is int
            and (capture["actual_width"], capture["actual_height"]) == (width, height), "capture actual dimensions 不一致")
    for key, expected in (("viewport_width", canvas["viewportWidth"]), ("viewport_height", canvas["viewportHeight"]),
                          ("device_scale_factor", canvas["deviceScaleFactor"])):
        require(number(capture.get(key), key, True) == expected, f"capture {key} 不一致")
        observed = "observed_" + key
        if observed in capture:
            require(number(capture[observed], observed, True) == expected, f"capture {observed} 不一致")
    require(isinstance(capture.get("resource_errors"), list) and not capture["resource_errors"], "capture resource_errors 必须空 list")
    for key in ("browser_version", "os", "timestamp"):
        require(nonempty(capture.get(key)), f"capture {key} 必须非空")
    dom = capture.get("elements")
    require(isinstance(dom, list) and len(dom) <= MAX_ITEMS, "capture elements 必须至多 512 项数组")
    by_id = {}
    for value in dom:
        item = mapping(value, "capture element")
        eid = item.get("id")
        require(isinstance(eid, str) and ID_RE.fullmatch(eid) and eid not in by_id, "DOM data-replica-id 无效或重复")
        require(item.get("coordinate_space") == "viewport-css-pixels", "DOM 元素须 viewport-css-pixels")
        for key in ("x", "y", "width", "height"):
            number(item.get(key), f"DOM {eid}.{key}")
        require(item["width"] >= 0 and item["height"] >= 0, "DOM AABB 尺寸不得为负")
        by_id[eid] = item
    require(set(selected) <= set(by_id), "DOM 缺少 selected data-replica-id")
    deltas = {}
    for eid in selected:
        item, element = by_id[eid], elements[eid]
        actual = {key: item[dom_key] * canvas["deviceScaleFactor"] for key, dom_key in
                  (("x", "x"), ("y", "y"), ("width", "width"), ("height", "height"))}
        delta = {k: number(actual[k] - element[k], f"{eid} geometry delta.{k}") for k in actual}
        for key, value in actual.items():
            number(value, f"{eid} source AABB.{key}")
        deltas[eid] = {"actual_source_aabb": actual, "delta": delta,
                       "analysis_rotation": element["rotation"], "interpretation": "仅定位；不作旋转坐标校正或质量阈值判定"}
    report["geometry_deltas"] = deltas
    return width, height, pixels


def validate_version_digest(value, analysis, digest, label):
    require(type(value.get("revision")) is int and value["revision"] == analysis["revision"], f"{label} revision 已过期")
    require(value.get("analysisDigest") == digest, f"{label} analysisDigest 已过期")


def region_metrics(width, height, baseline, current, element):
    # x/y/w/h 是明列的源像素 AABB，不猜测旋转中心或把角度用作平移修正。
    x = max(0, min(width, math.floor(element["x"])))
    y = max(0, min(height, math.floor(element["y"])))
    right = max(0, min(width, math.ceil(element["x"] + element["width"])))
    bottom = max(0, min(height, math.ceil(element["y"] + element["height"])))
    require(right > x and bottom > y, f"{element['id']} 回归区域与源画布无交集")
    region = {"x": x, "y": y, "width": right - x, "height": bottom - y}
    _, _, metrics = compare(crop_rgba(width, baseline, region), crop_rgba(width, current, region), "#ffffff")
    return {"source_aabb_crop": region, **metrics}


def validate_regression(root, analysis, elements, selected, baseline, current_path, current_png,
                        issues, checkpoint, protected, report):
    require(baseline is not None and issues is not None and checkpoint is not None, "regression 须 baseline、issues、checkpoint")
    require(baseline != current_path and not baseline.samefile(current_path), "baseline 与 current 不得同一路径或同一文件")
    width, height, current = current_png
    bw, bh, before = read_png(baseline)
    require((bw, bh) == (width, height), "baseline 与当前物理尺寸不同")
    digest = report["analysis_digest"]
    validate_version_digest(issues, analysis, digest, "issues")
    validate_version_digest(checkpoint, analysis, digest, "checkpoint")
    targets = unique_strings(issues.get("allowedElementIds"), "allowedElementIds", selected, True)
    maximum = issues.get("maxIssues", 3)
    positive_int(maximum, "maxIssues")
    require(maximum <= MAX_ITEMS and len(targets) <= maximum, "问题数量超过 maxIssues（默认最多 3）")
    if maximum > 3:
        require(nonempty(issues.get("expansionEvidence")), "扩大问题规模须用户 expansionEvidence")
    neighbours = unique_strings(issues.get("regressionElementIds"), "regressionElementIds", elements)
    require(nonempty(issues.get("evidence")), "issues 缺少问题证据")
    properties = unique_strings(issues.get("allowedProperties"), "allowedProperties", nonempty_list=True)
    require(all(re.fullmatch(r"(?:--[a-zA-Z0-9_-]+|-?[a-z][a-z0-9-]*)", p) for p in properties), "allowedProperties 必须 CSS 属性名")
    frozen_targets = [eid for eid in targets if elements[eid]["freeze"]]
    if frozen_targets:
        require(nonempty(issues.get("unfreezeEvidence")), "冻结元素修改须 unfreezeEvidence")
    allowed_names = unique_strings(issues.get("allowedFiles"), "allowedFiles", nonempty_list=True)
    allowed = {safe_file(root, name, relative=True) for name in allowed_names}
    require(len(allowed) == len(allowed_names), "allowedFiles 含文件别名")
    protected_inodes = {(p.stat().st_dev, p.stat().st_ino) for p in protected}
    require(not any((p.stat().st_dev, p.stat().st_ino) in protected_inodes for p in allowed),
            "allowedFiles 不得授权覆盖源图、规格或已批准素材（含硬链接）")
    checkpoint_baseline = safe_file(root, checkpoint.get("baseline"), relative=True)
    require(checkpoint_baseline == baseline, "checkpoint baseline 路径不匹配")
    require(checkpoint.get("baselineSha256") == sha256_file(baseline), "checkpoint baselineSha256 不匹配")
    files = mapping(checkpoint.get("files"), "checkpoint.files")
    require(bool(files), "checkpoint.files 不得为空")
    tracked, hashes = set(), {}
    for name, expected in files.items():
        path = safe_file(root, name, relative=True)
        require(path not in tracked, "checkpoint.files 含文件别名")
        tracked.add(path)
        require(isinstance(expected, str) and HASH_RE.fullmatch(expected), "checkpoint 文件 hash 无效")
        actual = sha256_file(path)
        hashes[name] = {"changed": actual != expected, "allowed": path in allowed}
        require(path in allowed or actual == expected, f"非 allowedFiles 的已追踪文件变化：{name}")
    require(allowed <= tracked, "allowedFiles 必须由 checkpoint 明列追踪")
    report["file_checks"] = hashes
    metrics = {}
    frozen_changes = []
    for eid in dict.fromkeys([*targets, *neighbours, *(k for k, e in elements.items() if e["freeze"])]):
        metrics[eid] = region_metrics(width, height, before, current, elements[eid])
        if elements[eid]["freeze"] and metrics[eid]["changed_pixel_count"]:
            frozen_changes.append(eid)
    report["region_metrics"] = metrics
    report["frozen_changes"] = frozen_changes
    if frozen_changes:
        report["status"] = "needs_review"
        report["warnings"].append("冻结区域存在像素变化；需要用户检查，不是自动视觉失败")


def validate_project(project_root, analysis, stage, text_manifest=None, asset_manifest=None,
                     current=None, capture_report=None, baseline=None, issues=None, checkpoint=None):
    """返回结构化 report，不写文件；Path 参数相对 project_root 或为根内绝对路径。"""
    report = {"status": "blocked", "stage": stage, "visual_approved": False, "errors": [],
              "warnings": [], "limitations": list(LIMITATIONS)}
    try:
        require(stage in {"analysis", "implementation", "capture", "regression"}, "无效 stage")
        root = Path(project_root).resolve(strict=True)
        require(root.is_dir(), "project-root 必须是目录")
        inputs = dict(analysis=analysis, text_manifest=text_manifest, asset_manifest=asset_manifest,
                      current=current, capture_report=capture_report, baseline=baseline, issues=issues, checkpoint=checkpoint)
        paths = {key: safe_file(root, value) for key, value in inputs.items() if value is not None}
        require("analysis" in paths, "analysis 必需")
        documents = {key: load_json(path) for key, path in paths.items() if key not in {"current", "baseline"}}
        # 可选输入也必须是有效 PNG；不因当前 stage 未使用而忽略坏文件。
        for key in ("current", "baseline"):
            if key in paths:
                read_png(paths[key])
        spec = documents["analysis"]
        for key in ("analysis", "text_manifest", "asset_manifest"):
            if key in documents:
                validate_file_references(root, documents[key])
        elements, source = validate_analysis(root, spec, stage, report)
        review, selected = validate_review(spec, elements, report["analysis_digest"], stage, report)
        report["selected_element_ids"] = selected if stage != "analysis" else []
        report["pending_element_ids"] = [eid for eid in elements if stage == "analysis" or eid not in selected]
        texts, assets = documents.get("text_manifest", {}), documents.get("asset_manifest", {})
        asset_paths = validate_manifests(root, texts, assets, elements, selected, review, report, stage != "analysis")
        capture = documents.get("capture_report")
        if capture:
            for key in ("output", "report"):
                if key in capture:
                    resolved = safe_file(root, capture[key])
                    if key == "output" and "current" in paths:
                        require(resolved == paths["current"], "capture output 与 current 不一致")
            if "published" in capture:
                for name in unique_strings(capture["published"], "capture.published"):
                    safe_file(root, name)
        for key in ("issues", "checkpoint"):
            doc = documents.get(key)
            if doc is not None:
                for name in doc.get("allowedFiles", []):
                    safe_file(root, name, relative=True)
                if "baseline" in doc:
                    safe_file(root, doc["baseline"], relative=True)
                if "files" in doc:
                    for name in mapping(doc["files"], "checkpoint.files"):
                        safe_file(root, name, relative=True)
        report["status"] = "awaiting_user_review" if stage == "analysis" else "checks_passed"
        if stage in {"capture", "regression"}:
            png = validate_capture(spec, elements, selected, paths.get("current"), capture, report)
        if stage == "regression":
            protected = {source, *[path for key, path in paths.items() if key not in {"current", "baseline"}],
                         *[asset_paths[aid] for aid, a in assets.items() if a["approved"]]}
            validate_regression(root, spec, elements, selected, paths.get("baseline"), paths["current"], png,
                                documents.get("issues"), documents.get("checkpoint"), protected, report)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError, RuntimeError) as exc:
        report["status"] = "blocked"
        report["errors"].append(str(exc) or type(exc).__name__)
    return report


class StructuredParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def parse_args(argv=None):
    parser = StructuredParser(description="只读离线阶段检查；不会自动批准视觉结果", allow_abbrev=False)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--analysis", required=True, type=Path)
    parser.add_argument("--stage", required=True, choices=("analysis", "implementation", "capture", "regression"))
    for name in ("text-manifest", "asset-manifest", "current", "capture-report", "baseline", "issues", "checkpoint"):
        parser.add_argument("--" + name, type=Path)
    return parser.parse_args(argv)


def main(argv=None):
    try:
        report = validate_project(**vars(parse_args(argv)))
    except ValueError as exc:
        report = {"status": "blocked", "visual_approved": False, "errors": [str(exc)], "warnings": [], "limitations": list(LIMITATIONS)}
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if report["status"] in {"awaiting_user_review", "checks_passed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
