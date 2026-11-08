# 项目协议、阶段检查与回归

## 分析与实施的边界

首次详细分析必须以 `analysis-spec.md` 的八段格式发在聊天中并等待用户，不能用工程文件代替说明。收到批准前，不需要也不得为了走流程创建整个项目。收到批准后在已授权目录固化下面的机器材料，沿用现有工程，不强迫重建目录。

```text
reference/source.png                  同尺寸比较基准，原始文件另保留
reference/preprocessed/regions.json    网格、裁图与坐标逆变换清单
reference/analysis.json                已批准方案和候选坐标
reference/text-manifest.json           独立文字候选与核验
reviews/asset-manifest.json            已存在素材与审批记录
reviews/issues.json                   机器局部任务卡；聊天中另说明
reviews/checkpoints/round-01.json      明列文件摘要及截图基线
public/assets/                        实际素材
screenshots/round-01.png               每轮独立截图
screenshots/round-01.png.capture.json   严格截图配对报告
screenshots/round-01-comparison/       叠加与分区材料
```

路径全部以批准项目根目录为基准，清单引用用正斜杠、根相对路径，不用 `..`。脚本拒绝越界路径及逃逸符号链接，只检查明列文件，不扫描其他个人目录。若工程素材位于其他目录，先由用户决定纳入哪个项目根范围或提供独立副本。

## 统一分析规格

下面数字和文字仅为格式示例，不是对任何用户图的测量。用实际图、实际摘要和实际用户回复替换，不能复制示例声明为已验证。

```json
{
  "schemaVersion": "1",
  "revision": 1,
  "sourceFile": "reference/source.png",
  "sourceSha256": "替换为工具计算的64位小写摘要",
  "coordinateSpace": "source-pixels",
  "canvas": {
    "sourceWidth": 1536,
    "sourceHeight": 864,
    "viewportWidth": 1536,
    "viewportHeight": 864,
    "deviceScaleFactor": 1
  },
  "elements": [
    {
      "id": "title-main",
      "type": "text",
      "parentId": null,
      "text": "示例标题",
      "x": 90,
      "y": 18,
      "width": 820,
      "height": 120,
      "rotation": 0,
      "implementation": "html-css",
      "style": {"fontSize": 96, "fontWeight": 900, "lineHeight": 1.1},
      "source": "estimated",
      "confidence": "medium",
      "verified": false,
      "status": "unimplemented",
      "freeze": false,
      "evidence": "标题可见，精确边界和字体待核验"
    }
  ],
  "review": {"status": "pending"}
}
```

元素使用 `width/height`，不用混杂的 `w/h`；`parentId` 只表示层级，所有坐标仍为源图绝对像素。可选 `relative` 使用 `x/y/width/height`，由源图宽高计算，误差容差 0.0001 仅用于数值一致性。明确越界的装饰需要 `allowOverflow: true` 和原因，不能默默裁错。

`verified: true` 必须附 `verificationEvidence`（实际测量、截图或用户核对记录）；`freeze: true` 必须同时 `status: approved` 并有证据。策略批准不等于元素已经视觉验收；估算可用于实施，但保持待核验，后续截图校正。

## 用户审核回执

对当前完整规划计算摘要后记录真实审批，而不是让模型自填“用户已同意”。分析检查输出 `analysis_digest` 和 `source_sha256`；先把实际源摘要写入规格再计算最终规划摘要。使用 `validate_project.plan_digest(analysis)` 或再次执行分析检查获取，禁止手写或猜测摘要。

```json
{
  "status": "approved",
  "revision": 1,
  "analysisDigest": "工具计算的当前规划摘要",
  "confirmedBy": "user",
  "evidence": "实际用户原话或可追溯消息引用，不能使用这段示例",
  "approvedElementIds": ["title-main", "panel-main", "character-cat"],
  "allowGeneratedAssetIds": [],
  "allowRasterizedTextIds": []
}
```

把该对象写入 `analysis.review`。后三个数组全部使用**元素 ID**，即使字段名含 Asset 也不是素材 ID。没有获准生成则生成数组为空；特殊字图片化单列许可；不得把批准局部解释为批准全部。数组中 ID 必须实际存在，待定方法或 unknown 元素不可进入实施范围。

规划摘要包含原图、尺寸、坐标、样式、方法、版本等全部规划字段，排除 `review` 以及元素 `status/freeze/verified/verificationEvidence`。用户纠正方案或更换规划时更新 `revision` 和摘要，重新获得受影响范围确认。日常只修正实现 CSS 使之符合已批准目标，不必擅自改目标规格；确实需要纠正目标规格时重新审核，不能用旧回执冒充新授权。

脚本只能检查回执内容、版本和摘要一致，不能证明真实用户发过消息。宿主必须核对聊天原话；`checks_passed` 不等于用户授权或视觉通过。

## 阶段检查命令

所有路径替换为实际绝对路径；支持的 stage 为 `analysis / implementation / capture / regression`。脚本只读并向终端输出 JSON，不创建报告文件。

```bash
python "<技能目录>/scripts/validate_project.py" --project-root "<项目目录>" --analysis "reference/analysis.json" --stage analysis
python "<技能目录>/scripts/validate_project.py" --project-root "<项目目录>" --analysis "reference/analysis.json" --text-manifest "reference/text-manifest.json" --asset-manifest "reviews/asset-manifest.json" --stage implementation
python "<技能目录>/scripts/validate_project.py" --project-root "<项目目录>" --analysis "reference/analysis.json" --text-manifest "reference/text-manifest.json" --asset-manifest "reviews/asset-manifest.json" --current "screenshots/round-01.png" --capture-report "screenshots/round-01.png.capture.json" --stage capture
```

- `analysis`：核对候选规格、坐标、层级、参考图和已提供的文件；状态 `awaiting_user_review`，**绝不授予实施许可**。
- `implementation`：核对本次回执、已选元素、文字、现存素材、生成许可和透明需求。缺文件或未批准的素材不作为正式资源；骨架可保留占位，但不得因此宣称完整集成检查通过。
- `capture`：再核对当前 PNG、报告摘要、物理尺寸、严格就绪、错误、版本与 DOM ID；输出源像素几何偏差，仅定位，不自动视觉评分。
- `regression`：追加问题清单、基线和文件检查点，检查越界文件变化及冻结区域。
- `blocked` 退出码 1：输入、审批或证据不一致；停止受影响动作。
- `needs_review` 退出码 1：冻结区域发生变化；交用户复查，不代表视觉自动失败。
- `awaiting_user_review / checks_passed` 退出码 0：对应机器检查结束，`visual_approved` 始终为 `false`。

清单可以先只包含已存在且需要本轮检查的素材；未制作素材留在分析的策略和聊天待办中，不用假的文件路径通过检查。完整交付时必须补齐全部已批准元素及对应清单；局部检查不冒充全页验收。

## 局部任务卡与文件检查点

以聊天问题说明为主，自动回归时另保存下面两个 JSON。只填实际存在的文件及工具计算的摘要，不自动初始化仓库、提交或回退。

```json
{
  "revision": 1,
  "analysisDigest": "当前规划摘要",
  "allowedElementIds": ["title-main"],
  "allowedFiles": ["src/styles/page.css"],
  "allowedProperties": ["top", "font-size"],
  "regressionElementIds": ["panel-main"],
  "evidence": "本轮截图中标题偏低，列出实际截图或区域证据"
}
```

```json
{
  "revision": 1,
  "analysisDigest": "当前规划摘要",
  "baseline": "screenshots/round-01.png",
  "baselineSha256": "实际基线摘要",
  "files": {
    "src/styles/page.css": "修改前文件摘要",
    "src/pages/index.html": "修改前文件摘要",
    "public/assets/cat.png": "已批准素材的实际摘要"
  }
}
```

默认最多三个目标问题，扩大时记录 `maxIssues` 和 `expansionEvidence`；冻结目标需要 `unfreezeEvidence`，但仍须复查实际冻结区域，不能用字符串自动豁免。把全部可能受影响的源码、共享样式、已批准素材和规格明列入 checkpoint；缺失文件或非允许文件 hash 变化会阻止继续。

```bash
python "<技能目录>/scripts/validate_project.py" --project-root "<项目目录>" --analysis "reference/analysis.json" --text-manifest "reference/text-manifest.json" --asset-manifest "reviews/asset-manifest.json" --current "screenshots/round-02.png" --capture-report "screenshots/round-02.png.capture.json" --baseline "screenshots/round-01.png" --issues "reviews/issues.json" --checkpoint "reviews/checkpoints/round-01.json" --stage regression
```

冻结区域用明确源坐标裁剪并检查变化；旋转时使用实际 AABB 或用户批准的回归区域，不把旋转前框误称精确覆盖。记录目标、相邻和冻结区域，再决定保留或回退。文件 hash 检查只覆盖明列文件，不会发现未追踪新增文件；允许文件内部的 CSS 属性／选择器仍须宿主看完整 diff。机器指标与用户判断缺一不可。

## 分工与最终验收

视觉角色只分析与诊断；素材角色只处理获准素材；代码角色只实现目标或局部补丁；浏览器角色提供实际证据。一个助手可轮流担当，不省略阶段边界。分别记录结构验收和视觉验收，任何局部批准、机器 checks_passed 或有 PNG 文件都不能等同完整视觉通过。
