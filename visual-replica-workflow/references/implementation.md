# 获准素材处理与受约束的前端实现

## 先确认审核范围

未展示 `analysis-spec.md` 的八段分析、未收到当前方案的明确用户确认，不运行素材制作、抠图、生图或页面编码。后续仅实施 `analysis.review.approvedElementIds` 指定范围，完整回执与机器格式见 `workflow.md`。方案确认与素材单项批准是两回事，不能因为用户说“继续”就自动批准后来生成的图片。

## 素材决策与处理

| 元素 | 首选方式 | 核验重点 |
|---|---|---|
| 普通说明、编号、可更新或交互文字 | HTML 真实文本 | 内容、标点、字体、换行和可编辑性 |
| 装饰性特殊标题 | 相同字体真实文本；必要时提议图片化 | 字体可得性、逐项许可、可访问文字说明 |
| 面板、卡片、手机外框 | HTML/CSS | 位置、尺寸、圆角、阴影和层级 |
| 简单矢量图标或曲线 | SVG | 笔画、关键顶点和比例 |
| 复杂人物／动物／毛发 | 原素材或原图抠图 | 轮廓、表情、透明边缘，不重新生成相似替代品 |
| 复杂纹理或手绘笔触 | 原图裁切／现有素材 | 分辨率、平铺、遮挡和裁切范围 |
| 装饰性内屏 | 经批准保留局部图片 | 只装饰，不冒充真实交互 |
| 可交互内屏 | 真组件 | 状态、按钮、内容与点击区域 |

按 `reuse-image → crop-image → remove-background → generate-image` 的资源优先级逐项处理。能简单用代码准确实现的元素采用代码；复杂素材优先复用，裁切不能解决透明轮廓时才抠图，原图缺失时才提议生成。必要时改变方式须先更新分析并重审，不自行将“提取失败”变成“重新生图”。

- 仅搜索用户已提供的项目素材目录，不到个人目录寻找替代素材。
- 保留原图与裁切坐标。原图被文字或角色遮挡时，说明无法直接恢复隐藏像素。
- 抠图工具由宿主提供；脚本只能矩形裁切、透明检查，不能去背景或恢复遮挡。
- 白色角色不采用简单删除白色像素的方法；检查耳尾、毛发、细线、浅色边缘。
- 生成每个独立素材，不把多个角色塞进一张图后再切。仅按已批准需求选择比例、完整轮廓、透明需求及留白；不假设生成工具真的支持透明输出。
- 精确抠图和生图的操作参数以工具实际能力为准，不编造调用结果。

## 透明检查与素材清单

```bash
python "<技能目录>/scripts/inspect_assets.py" --asset "<项目目录>/public/assets/cat.png" --output-dir "<项目目录>/reviews/assets/cat-round-01"
```

脚本输出 `inspection.json` 和 `preview-light-dark.png`。查看真实 Alpha、非空内容、透明留白；再把深浅背景预览交用户检查角色轮廓。全透明空图、普通像素棋盘格或白底图不是合格透明素材。机器结果不自动批准图片。

`asset-manifest.json` 根节点以素材 ID 为键。下例只是待审批模板，文件名、尺寸、证据必须换成实际材料；未存在文件不要伪填入机器清单，先留在分析待办中。

```json
{
  "cat-original": {
    "file": "public/assets/cat.png",
    "source": "extracted",
    "sourceRegion": {"x": 100, "y": 200, "width": 300, "height": 250},
    "usage": "原图角色",
    "displaySize": {"width": 300, "height": 250},
    "aspectRatioLocked": true,
    "transparentBackground": true,
    "alphaVerified": false,
    "edgeChecked": false,
    "approximate": false,
    "approved": false,
    "approvalEvidence": "",
    "inspectionFile": "reviews/assets/cat-round-01/inspection.json"
  }
}
```

`source` 使用 `provided/extracted/generated`。`file` 以工程根为基准，例如 `public/assets/cat.png`；浏览器引用 URL 可能是 `/assets/cat.png`，**文件路径与 URL 不混用**。元素通过 `assetId` 对应素材 ID，未填写时默认同元素 ID。

- `alphaVerified` 只能来自真实检查；`edgeChecked`、`approved` 需要实际看图与用户决定，批准时保留 `approvalEvidence`。
- `generate-image`、来源为 generated 或 `approximate: true` 均需 `review.allowGeneratedAssetIds` 中的对应**元素 ID**许可。
- 需要透明的素材必须真实有透明像素且内容非空；文件有 RGBA 通道但全部不透明不证明去背景成功。
- 素材显示坐标需考虑内容框与透明留白，不能把图片元素框直接当人物边界。

## 独立文字与装饰字例外

使用宿主已可用 OCR 或用户提供结果，保留区域、候选文字、来源；小字先裁剪再识别。OCR 不可用则明确使用 vision，不能把视觉模型转录标为 OCR。手写或模糊文字保持待核验，不猜写。

`text-manifest.json` 以元素 ID 为键；内容在分析规格中存在时须一致。

```json
{
  "title-main": {
    "text": "示例标题",
    "source": "vision",
    "verified": false,
    "verificationEvidence": "",
    "renderMode": "text",
    "requiredEditable": true,
    "fontVerified": false,
    "lineBreaksVerified": false,
    "fontSize": 96,
    "fontWeight": 900,
    "lineHeight": 1.1
  }
}
```

文字来源使用 `ocr/vision/user-provided`。内容核验后才设置 verified 并保留真实证据，字体和换行分别核验。字体加载成功不证明使用原字体；未知字体或回退保留警告。

只有装饰性标题明确无需编辑且用户单项允许，才可 `renderMode: image`；同时设 `requiredEditable: false`，取得 `review.allowRasterizedTextIds` 许可，并引用已批准素材。普通说明、表单、按钮等必需可编辑的文字禁止图片化。图片化文字保留转录内容与可访问说明，不重复显示文本。

## 固定编码顺序与标识

固定技术栈、版本、视口、组件接口、共享样式和素材路径后按当前阶段执行：

1. 列出工程分区与引用表，不猜不存在的文件。
2. 只实现画布、背景、主要面板位置与层级；未批准素材用明确占位，不当作正式集成。
3. 检查主区截图后实现重复组件和真实文字。
4. 接入已批准素材，处理内容框、裁剪、字体和换行。
5. 再精修边框、阴影和装饰，运行页面并记录关键错误。
6. 固定状态截图、对比、局部修复，不凭代码审阅宣布视觉完成。

主元素统一使用 `data-replica-id="稳定元素ID"`，对应分析规格和截图报告。单个自动检查批次最多 512 个标识；重复微小装饰可按实际共同布局分组，不能静默丢失内容。分析中保留分组数量和各项文字。

固定画布可用相对容器加绝对定位，列表用 Grid，卡片内部用 Flexbox。源图像素除以 DPR 得到 CSS 坐标；若旋转框的分析数据是 AABB，先还原变换中心和局部框，不直接把 AABB 当旋转前尺寸。真实响应式任务必须按确认断点重排，不用整页缩放冒充响应式。

## 每轮交付与局部修改

默认一次一个区域、最多三个相关问题。先在聊天中说明目标元素、直接证据、允许文件／选择器／属性、禁止改变的素材与冻结元素、回归范围，再做局部补丁。自动回归另记录 `issues.json` 与 checkpoint，格式见 `workflow.md`。

每轮列出修改文件、完成项、待核验项；不能扩大到全局字体或共享规则后不说明影响。`validate_project.py` 能发现明列文件的越界变化与冻结区域变化，但不会解析每条 CSS 修改；宿主仍须检查完整 diff。重新截图后才判断修复效果，失败时记录原因或经许可回退，不继续叠加不确定的全页改动。
