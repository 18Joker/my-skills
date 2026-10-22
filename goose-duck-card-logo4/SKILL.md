---
name: goose-duck-card-logo4
description: 为鹅鸭杀记牌器小程序（eys-image2 项目）参考官方素材重设计角色 logo。当用户要求"重新设计 N 张某角色 logo"、"按某风格生成角色 logo"、"重构官方素材"、批量生成鹅/鸭/中立阵营角色图时使用。一次只做一个风格：用户未指定 chibi Q版 还是 美式复古漫画 时，必须先提问让用户二选一，严禁两种风格都生成一遍。流程：确认风格 → 读 official_camps_v3 官方基准图 → 读最新风格目录的 style 文件 → 设计提示词 → 写 photogpt 任务 JSON → 本地脚本生图 → 产物落 工坊/批次/ → 生成审核页 HTML 交用户挑图。触发词：鹅鸭杀 logo、记牌器 logo、角色 logo 重设计、chibi 风格、美式复古漫画风格、套图生成。
---

# 鹅鸭杀记牌器角色 Logo 生成（v4）

参考官方素材 logo，按指定风格套图规范重新设计角色 logo，通过本地 photogpt_playwright 脚本生图，产物归集到批次目录并生成审核页交付。

## 关键路径（写死，勿猜）

| 用途 | 路径 |
|---|---|
| 项目根 | `D:\program\project\front\eys-image2` |
| 官方基准素材 | `<项目根>\official_camps_v3\{goose,duck,neutral}\{阵营}_{角色名}.png` |
| 在用风格套图 | `<项目根>\chibi_style_v2\`、`<项目根>\american_retro_style_v3\`（发现规则见 references/workflow.md §2） |
| 生图执行器 | `D:\program\project\media-automation\tools\photogpt_playwright\playwright_runner.py` |
| 任务 JSON 格式权威文档 | `D:\program\project\media-automation\tools\photogpt_playwright\TASKS_JSON_FORMAT.md` |
| 生图 python | `D:\c-envs\media-automation\python.exe`（conda 环境 media-automation） |
| 产物归集地 | `<项目根>\工坊\批次\YYYYMMDD_语义名\`（永不入 git） |
| 批次台账 | `<项目根>\工坊\_台账.md` |

> 注意：工作区可能打开的是 `eys-image`（旧项目），本 skill 的目标项目是 **`eys-image2`**。用户明确指定其他项目根时以用户为准。

## 工作流（8 步，三处停顿必须等用户：风格确认 → 方案确认 → 挑图确认）

### 1. 解析需求
提取三要素：
- **角色清单**：如"巫医、刺客"；"重新设计 5 张巫医 logo" = 同一角色出 5 个差异化方案。
- **风格**：**必须先确定唯一一种风格才能继续**，见下方「风格未指定时的处理」。
- **每角色方案数**：默认 1；用户说"N 张"即 N 个方案。

**风格未指定时的处理（硬规则）**：
- 用户没点名风格（也没说"两种都要/所有风格"）时，**立即停下用 AskUserQuestion 工具提问**，让用户在两种风格里选一个，拿到答复前不得进入第 2 步、不得设计任何 prompt、不得写 JSON、不得跑生图。
- 提问选项固定两项（描述可带一句风格特征）：
  | 选项 label | description 建议写法 |
  |---|---|
  | `chibi Q版` | Q版二头身潮玩贴纸风，粗黑描边纯色平涂，纯白背景（规范 chibi_style_v2） |
  | `美式复古漫画` | 肩部以上胸像 + 放射光柱背景，pop art 复古漫画质感（规范 american_retro_style_v3） |
- **绝对禁止**把两种风格各生成一遍让用户挑——积分翻倍且违背用户预期。只有用户明确说"两种风格都做/都生成"时才允许同批跑两种风格，此时方案摘要里要分别列出两套任务与合计积分。
- 用户答复后把选定风格写进批次语义名与 README（如 `巫医美式复古重设计`）。

角色名 → 官方图路径的映射规则、别名与找不到的处理见 references/workflow.md §1。

### 2. 读风格规范 + 开图核对官方基准
- 定位风格目录内**最新版本** style 文件（`style_v3.txt` > `style_v2.txt` > `style.txt`，规则见 references/workflow.md §2），完整读取。
- 用 Read 工具**逐张开图查看**每个角色的 `official_camps_v3` 官方图，按 style 文件法则提炼视觉锚点（chibi = 四位一体：头饰/五官/颈胸服饰/持物状态；复古 = 物品与职业特征）。**严禁凭角色名脑补特征**——历史教训：文字档案描述与实图不符（D-22 鸭子事件）。
- 同时开图查看风格套图目录下同名角色的**现用图**（如 `chibi_style_v2\duck\duck_巫医.png`），确保新方案不比现用图差、且与现用图有区分度（重设计场景尤其要做侵权/雷同诊断，方法见 references/prompt-design.md §4）。

### 3. 设计提示词（Checkpoint ①：先出方案再执行）
按 references/prompt-design.md 写每条 prompt。然后向用户输出**方案摘要**：每角色每方案的差异化杠杆一句话、任务总数、预估积分（默认组合 4 积分/张 × output_num）。**等用户确认后才写 JSON 执行**（项目红线：批量任务先出方案）。用户已明确说"直接生成/不用确认"时可跳过等待。

### 4. 建批次目录 + 登记台账
- 目录 `工坊\批次\YYYYMMDD_语义名\`（语义名如 `巫医美式复古重设计`；同日多批加 `_02`；禁止 副本/copy/bak/v2 式命名）。建 `images\` 子目录。
- 在 `工坊\_台账.md` 批次一览表**先登记一行**（状态=进行中）再开工，模板见台账文件底部。

### 5. 写任务 JSON
- 落盘批次目录：`任务_<语义名>.json`，UTF-8。
- `out_path` 一律写**绝对路径**指向批次 `images\`，文件名 `<角色名>_<方案ID>.png`（如 `巫医_A_歪帽单旋涡.png`）。**禁止**写交付套图目录、`py/`、`config/`、项目根、photogpt 的 output 目录。
- 默认参数组合（四字段缺一不可，必须显式写出）：
  `"mode": "gpt_image_2_5"` + `"model_variant": "Sunburst"` + `"quality": "medium"` + `"resolution": "1K"`；`aspect_ratio` 两风格均为 `"1:1"`；`output_num` 默认 1（要多帧挑选时才 >1，积分按张翻倍）。
- 字段细则、积分价目、去重机制以 `TASKS_JSON_FORMAT.md` 为唯一权威，有任何不确定先重读该文档。
- 写完必须跑校验，失败修复后重跑，不允许带病提交：
  ```bash
  C:\Users\22322\.workbuddy\binaries\python\envs\default\Scripts\python.exe <本skill目录>\scripts\validate_tasks.py <任务JSON绝对路径> --batch <批次目录绝对路径>
  ```

### 6. 执行生图
```bash
cd D:\program\project\media-automation\tools\photogpt_playwright
D:\c-envs\media-automation\python.exe playwright_runner.py -t <任务JSON绝对路径> --open
```
- 先 `--status` 查账号余额。总消耗 = 任务数 × output_num × 4 积分（默认组合）；每账号每日免费 10 分，执行器自动换号。余额明显不足时告知用户，由用户决定减量/分日/充值，不要自作主张改参数。
- 可加 `--dry-run` 预览去重与跳过情况（不花积分、不开浏览器）。
- 长任务（每张 1~3 分钟 + 登录开销），用后台运行并等通知。**脚本可能拉起 Chrome 要求人工登录/过人机验证**——提前提醒用户留意浏览器窗口（脚本会自动填好账号密码，用户只需点登录按钮）。
- 中断/失败可直接重跑同一 JSON：指纹去重保证已成功任务零积分复用，failed/pending 自动重试。

### 7. 生成审核页（Checkpoint ②：交人类挑图）
- 清点 `images\` 实际产出，对照运行日志列成功/失败清单与失败原因。
- 写 `manifest_审核.json` 到批次目录（schema 见 scripts/build_review_page.py 文件头注释），逐张给 verdict/anchors/risk 评语并**按推荐顺序排 rank**（评估维度见 references/prompt-design.md §5）。
- 生成审核页并打开：
  ```bash
  C:\Users\22322\.workbuddy\binaries\python\envs\default\Scripts\python.exe <本skill目录>\scripts\build_review_page.py <批次目录>\manifest_审核.json
  ```
  产出批次目录内 `审核页_<title>.html`（含 48/96px 小图实测列）。用 present_files 呈现给用户。
- 批次 `README.md` 写 3~5 行：模型/参数、规范依据（style 文件路径）、官方基准路径、各方案要点、当前状态。

### 8. 收尾
- `_台账.md` 状态改为 `已挑图待转正`，登记图数/体积。
- 向用户报告：批次目录、审核页路径、每张图绝对路径、实际积分消耗、失败项。
- **转正（挑图→压缩→复制进交付套图目录）只能由人类手工完成。** AI 只提供候选与对比页；绝不代替用户把图复制进 `chibi_style_v2\` 等交付目录；绝不删除任何落选图。转正流程与压缩闸门见 references/workflow.md §5。

## 硬性红线（违反即返工）

1. **一切生成产物只落 `工坊\批次\<当前批次>\`**（任务 JSON、图片、审核页、README、manifest）；不进 git，不进交付套图目录。
2. **prompt 角色特征必须来自开图核对官方实图**，不得凭文字名称脑补道具（叫巫医≠画葫芦；官方无持物严禁加手持道具）。
3. **中文 prompt 内嵌引号一律全角「“”」**，半角引号破坏 JSON；长 JSON 分片写入后必须 `json.load` 校验（单次 Write 超 30KB 会截断）。
4. **不删除任何文件**。落选图是花积分换来的不可再生样本；发现冗余只以表格列举汇报（路径/作用/建议原因），由人类手删。
5. style 文件的技术红线（背景、描边、禁文字水印、禁边框等）逐条落实到每条 prompt 尾部，一字不差带上固定尾缀。
6. 三处停顿必须等用户，禁止自动连续推进：**风格确认（未指定时）**、方案确认、挑图确认。
7. **一次只做一个风格**。未指定风格时必须先 AskUserQuestion 让用户选一种；严禁"两种风格都生成一遍让用户挑"（积分翻倍）。仅当用户明确要求两种都做时才同批跑两套。
8. 同一生成需求重跑不会重复扣积分，但"想换一批结果"必须在 prompt 里做实质微调（指纹含 prompt），改 task_id/out_path 无效。

## 参考文件

- `references/workflow.md` — 角色名映射、风格目录发现、执行器细节与故障处理、转正流程
- `references/prompt-design.md` — 两种风格的提示词设计法则、六维框架、侵权诊断、评估维度、完整范例
- `scripts/validate_tasks.py` — 任务 JSON 提交前校验（字段/默认组合/去重/out_path 归位/积分预估）
- `scripts/build_review_page.py` — 从 manifest 生成候选审核页 HTML