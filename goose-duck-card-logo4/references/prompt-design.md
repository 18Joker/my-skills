# prompt-design.md — 提示词设计法则

> **权威顺位**：风格目录里最新的 style 文件 > 本文档。本文档提供方法论与历史验证过的范例；style 文件的具体条款（背景色、描边、禁项）每次以实读为准，逐条落进 prompt。

## §1 通用原则（两种风格都适用）

1. **借概念保识别，改表达避侵权**：继承官方角色的核心身份符号（帽子品类、特殊眼睛、颈胸服饰、专属道具），严禁描摹官方原图的线条、纹样与构图骨架。目标：玩家不看文字一眼认出是哪个角色，同时与官方图保持可测量的距离。
2. **严禁望文生义**：不得根据角色名字脑补现实职业道具（巫医≠采药葫芦，医生≠听诊器）。一切特征来自开图核对 `official_camps_v3` 实图。
3. **持物状态对齐官方**：官方双手无持物 → prompt 显式写"不手持任何道具，双手自然垂落或收于胸下"；官方有专属道具 → 才能写，且做圆润化/卡通化重绘。
4. **五段式结构**（项目规范）：画风段 → 角色外观段 → 标志性道具/表情段 → 质感光效段 → 输出要求段（背景、居中、不裁切、无文字水印边框）。
5. **内嵌引号用全角「“”」**；prompt 内可用 `\n` 分行提高模型遵循度。
6. **每角色的多个方案必须写明差异化杠杆**（换什么、破什么对称、改什么角度），不允许只换形容词。同角色 N 方案 = N 个不同的杠杆组合。

## §2 chibi 风格（chibi_style_v2，规范 style_v3.txt）设计要点

四位一体锚点（写词前对照官方图逐项锁定）：

| 锚点 | 强继承 | 原创化手段 |
|---|---|---|
| 头部装束 | 同品类帽子/发饰（高顶礼帽、牛仔帽、侦探帽…），严禁换品类 | 几何外形 Q 版化、圆角化、偏心斜戴 |
| 五官异质特征 | 特殊眼（旋涡眼/准星眼/红心眼/独眼罩/墨镜）必须保留概念，严禁降级为普通豆眼 | 单侧突出 + 另一侧表情互动（半眯挑眉/wink） |
| 颈胸服饰 | 锯齿羽毛领/警徽/领结/斗篷等上半身剪影 | 简化褶皱，平涂色块 + 粗线条 |
| 持物状态 | 与官方双手交互状态完全对齐 | 有道具则圆润 Q 版化 |

硬指标：1:1 构图、主体占比 80~90% 不触边、二头身、全封闭粗黑描边、纯色块平涂（Cel-shading）、近暗色 ≤40%、含 ≥8% 面积高饱和亮色、纯白背景 #FFFFFF、禁棋盘格假透明、禁文字水印。

阵营神态：鹅=纯良呆萌元气；鸭=狡黠心机反差萌（嘴角单侧微翘坏笑）；中立=荒诞疯批放空（呆滞眼/斗鸡眼）。保留特殊五官前提下融入，禁千人一面眯眯笑。

**六维提示词框架**（style_v3.txt §7，逐段拼接）：
1. 取景与构图定位（对照官方图锁定：纯图标道具 / 完整角色全身 / 仅头部特写 / 肩部以上半身，四类不许擅自升降级）
2. Q版形体与角色主色
3. 头部装束与五官特征（锁定官方锚点）
4. 颈胸服装与持物状态（锁定官方锚点）
5. 材质风格与色彩工艺
6. 纯白背景与安全尾缀（从 style 文件一字不差复制）

## §3 美式复古漫画风格（american_retro_style_v3，规范 style.md）设计要点

- 生图方式 text_to_image（**不挂参考图**，`input_urls` 省略），prompt 用**英文**。
- 固定开头：`American retro comic style, pop art, above the shoulders.`
- 构图：肩部以上胸像、头部占主体、1024×1024（任务里 `aspect_ratio: "1:1"` + `resolution: "1K"`）、放射状光柱背景（`Radiating burst of light rays behind the head in ... halftone tones`）。
- 阵营表情：鸭=邪恶/狡诈；鹅=可爱/善良/正义/阳光；中立=按实际物种漫画化处理。
- 提示词与官方素材**高度相关**：把官方图的物品/职业特征转成卡通配饰（可戴卡通化配饰体现职业），但**避开职业名词本身**（不写 shaman/doctor/assassin 等，防止 AI 幻觉出刻板道具），改用视觉特征描述动物拟人化。
- 固定尾缀：`Bold comic ink outlines, flat cel-shaded colors, halftone dot shading, high contrast retro color palette. No borders, no frames, no text, no watermark.`
- 合规红线：禁血腥恐怖、禁真实危险物品、禁任何边框、必须卡通风格、禁暴力暗示。
- 光柱颜色随角色主色调走（如绿色系角色配 vintage green and teal halftone）。

## §4 重设计场景：先做侵权/雷同诊断

用户要求"重新设计"现有套图中的角色时，先在批次 README 里做诊断表（历史范例：巫医避权批次）：

| 锚点 | 官方 | 现用图 | 判定 |
|---|---|---|---|
| 取景角度 | （开图描述） | （开图描述） | ✗ 未差异化 / ✓ |
| 帽子/头饰 | … | … | ✗ 描摹 / ✓ |
| 眼睛特征 | … | … | … |
| 颈饰/服饰 | … | … | … |

- 现用图与官方在构图骨架+元素堆叠上接近 1:1（只改质感）= 侵权风险高，新方案必须打散骨架：换角度（微侧 30°/仰角/歪头 15°）、破对称（单侧特征）、替换母题（骷髅→原创骨节月牙徽扣）。
- 新方案之间也要有杠杆差异，避免 N 张雷同浪费积分。

## §5 审核评估维度（写 manifest verdict 时用）

按优先级排 rank：
1. **识别锚点齐全度**：官方核心锚点逐项打 ✓/✗（anchors 字段）。
2. **版权距离**：与官方构图骨架的差异度；帽徽等母题是否漂回官方元素（历史坑：同方向另一帧自发回退成小骷髅头——**逐帧核帽徽，不能只看方案名**）。
3. **小图可读性**：48/96px 下是否糊成黑块；近黑占比、是否有高饱和亮色视觉中心。
4. **阵营神态不跑偏**：鸭的狡黠不能被萌化盖掉，中立的荒诞不能画成鹅的元气。
5. **规范硬指标**：触边、留白、背景纯净度、有无文字水印。
6. 同 prompt 多帧的方差坑：旋涡眼可能退化成涂鸦波浪、帽徽退化成花形——逐张核，别按帧号想当然。

## §6 完整范例

### chibi（真实入库批次，巫医方案 A）

```text
纯头部大特写徽章构图，不画躯干四肢，仅一颗大圆头加底部一圈颈饰，主体饱满居中占比85%，四周充足安全留白。
一只Q版二头身比例的白羽鸭鸭，只呈现头部：饱满圆润的水滴形大脸，奶白色羽毛，形体圆滑无尖锐棱角，脸颊带淡粉腮红。
头戴一顶黑色宽檐高帽，偏心斜戴、帽檐一侧自然上卷；帽带上不使用骷髅头与交叉骨，改为一枚原创的圆润骨节配月牙组合徽扣，其旁斜排三颗钝角骨钉。
眼睛为单侧特殊特征：左眼是紫白相间的旋涡催眠眼，右眼半眯挑眉呈狡黠笑意；橙色圆润宽扁嘴喙，嘴角单侧微翘坏笑。
颈部下方露出一圈灰色锯齿羽毛领圈，锯齿重绘为三大簇圆角钝齿且左右不对称。不手持任何道具、葫芦、瓶子、布偶或法杖，双手收于胸下或自然垂落。
极简2D矢量平涂插画，潮玩贴纸质感，外轮廓具有完整封闭的厚重纯黑粗描边，纯色块平涂，局部点缀简约小弧光，色彩明快分明，无写实杂乱渐变。
整图为纯白色纯色背景：背景为均匀纯白（#FFFFFF），严禁任何渐变、阴影、投影、光晕或棋盘格；主体外轮廓与白色背景分界清晰，不触碰画面边缘，无文字，无水印。
```

对应任务字段：

```json
{
  "task_id": "wuyi_A_歪帽单旋涡",
  "mode": "gpt_image_2_5",
  "model_variant": "Sunburst",
  "quality": "medium",
  "resolution": "1K",
  "aspect_ratio": "1:1",
  "output_num": 2,
  "prompt": "<上面全文，\\n 分行>",
  "out_path": "D:\\program\\project\\front\\eys-image2\\工坊\\批次\\20260919_巫医避权重设计\\images\\巫医_A_歪帽单旋涡.png"
}
```

### 美式复古（真实入库任务，静语者）

```text
American retro comic style, pop art, above the shoulders. An anime-style cunning duck logo bust, head as the dominant subject. The duck wears a small teal domino half-mask over its eyes, one white-gloved finger lightly touching its beak in a classic shush gesture, one eye winking with a playful confident smirk, a few tiny cartoon stars sparkling around the head, mysterious yet lighthearted mood. Radiating burst of light rays behind the head in warm vintage halftone tones. Bold comic ink outlines, flat cel-shaded colors, halftone dot shading, high contrast retro color palette. No borders, no frames, no text, no watermark.
```

注意：无职业名词（不写 "spy"），特征全部来自官方图的视觉元素（面罩、噤声手势）。

## §7 批量写完后的断言检查

项目历史教训：肉眼查 prompt 会漏 30+ 处。批量任务 JSON 写完后除了跑 `scripts/validate_tasks.py`，还要自查：
- 禁词 0 残留（如 chibi 批次禁"透明背景/棋盘格"、复古批次禁职业名词、全批次禁半角引号包中文）。
- 必含关键词全命中（每条 prompt 都含固定尾缀、阵营神态词、"不手持"声明等）。
- 可用 Grep 工具对 JSON 文件跑关键词计数核对。
