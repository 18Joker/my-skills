# workflow.md — 项目结构、映射规则与执行细节

## §1 角色名 → 官方基准图映射

官方基准素材：`D:\program\project\front\eys-image2\official_camps_v3\`，按阵营分三个子目录：

| 阵营 | 目录 | 文件名格式 | 数量基准 |
|---|---|---|---|
| 鹅（好人） | `goose\` | `goose_{角色名}.png` | 24 |
| 鸭（坏人） | `duck\` | `duck_{角色名}.png` | 23 |
| 中立 | `neutral\` | `neutral_{角色名}.png` | 9 |

映射步骤：
1. 用户报角色名（可能带阵营前缀，如"duck_巫医"或只说"巫医"）。
2. 先按用户给的阵营找；没给阵营就用 Glob 在三个子目录搜 `*_{角色名}.png`。
3. **变体后缀**：部分文件带 `_v2` 后缀（如 `goose_生存主义者_v2.png`、`duck_牧师_v2.png`）。搜不到精确名时放宽为 `*_{角色名}*.png`，命中多个（如 `duck_牧师.png` 与 `duck_牧师_v2.png` 并存）时**取版本号最高的一张**，并在方案摘要里向用户说明用了哪个文件。
4. 完全找不到：列出三个目录的全部文件名让用户挑，**不要猜近似角色**。
5. 用户报的数量对不上时（如"5 张巫医"但巫医只有 1 个官方图），理解为**同一角色出 5 个差异化设计方案**，不是 5 个角色。

用户可能一次报多个角色 + 每个多方案，任务总数 = 角色数 × 方案数 × output_num，先算清积分再出方案。

## §2 风格目录发现规则

**只认这两个在用风格目录**（不要扫描其他目录找 style 文件）：

| 风格 | 目录 | style 文件（取最新） |
|---|---|---|
| chibi Q版潮玩贴纸 | `D:\program\project\front\eys-image2\chibi_style_v2\` | `style_v3.txt`（存在 v1/v2/v3 时**只用最高版本号**） |
| 美式复古漫画 | `D:\program\project\front\eys-image2\american_retro_style_v3\` | `style.md` |

规则：
- 目录名尾部的 `_vN` 是**套图版本**；风格目录本身也可能升版（如未来出现 `chibi_style_v3\`）。每次执行前用 Glob 确认目录是否仍是最高版本：搜 `<项目根>\chibi_style_*` 与 `<项目根>\american_retro_style_*`，取版本号最大的目录。
- style 文件同理：目录内可能有 `style.txt` / `style_v2.txt` / `style_v3.txt` / `style.md` 多个版本，**读取版本号最高的那个**（无版本号 < v2 < v3）。读之前 Glob 列一遍目录根部的 `style*` 文件。
- 每次执行都完整重读 style 文件，不要凭记忆——用户会随时改规范。
- 风格目录内同样按 `goose\ duck\ neutral\` 三阵营存放现用成图，文件名与 official_camps_v3 对齐（`{阵营}_{角色名}.png`）。

**一次任务只服务一种风格**：用户未点名风格时，先用 AskUserQuestion 让其在两种风格中选一个（选项 label / description 见 SKILL.md 第 1 步），拿到答复前不读 style、不设计 prompt、不写 JSON。严禁"两种风格各生成一遍供挑选"（积分翻倍、违背用户预期）；仅当用户明确要求两种都做时，才在同一批次里写两套任务，且方案摘要分列两套数量与合计积分，out_path 用文件名区分（如 `巫医_chibi_A.png` / `巫医_复古_A.png`）。

新增第三种风格目录时的处理：Glob 发现项目根出现新的 `*_style_*` 套图目录（含 style 文件）→ 把它加进 AskUserQuestion 选项，并同步更新本表与 SKILL.md 的风格选项表。

## §3 photogpt_playwright 执行器细节

目录：`D:\program\project\media-automation\tools\photogpt_playwright\`

| 事项 | 说明 |
|---|---|
| python | `D:\c-envs\media-automation\python.exe`（已装 playwright + sqlalchemy）。**不要**用 WorkBuddy 托管 python 或 base conda |
| 入口 | `playwright_runner.py -t <任务JSON绝对路径>` |
| 查余额 | `playwright_runner.py --status` |
| 干跑 | `playwright_runner.py -t <json> --dry-run`（只注册+去重判定，不开浏览器不花积分） |
| 完成后开画廊 | 加 `--open`（打开 photogpt 自己的 output 画廊；本 skill 另建批次审核页，二者不冲突） |
| 积分不足降级 | `--downgrade`（自动降 low/1K/1张重试）——**默认不加**，先问用户 |
| 浏览器 | CDP 连本机真实 Chrome（端口 9333，独立 profile），脚本自动拉起，无需 `playwright install` |
| 人工验证 | 登录态失效时脚本自动填好账号密码→断开自动化→等用户手点登录+过 Turnstile（300s 上限）。**执行前提醒用户留意弹出的 Chrome 窗口** |
| 去重 | 生成参数 sha256 指纹（含 prompt/mode/variant/quality/resolution/output_num/aspect_ratio/input_urls）。success→零积分复用；submitted→恢复轮询；failed/pending→自动重试。task_id 与 out_path 不参与指纹 |
| 任务表 | 落 `media-automation` 项目 `data/app.db` 的 `photogpt_gen_tasks` 表，`--list` 可查 |
| 输出 | `out_path` 为绝对路径时直接落该路径（本 skill 全部写批次 `images\` 绝对路径）；目录不存在会自动创建 |

积分价目（2026-09-26 调价后，gpt_image_2_5 / 1K）：low=3、**medium=4（默认组合）**、high=12 每张；每日免费 10 分/账号，多账号自动轮换。**权威价目以 `pricing.json` 与生成按钮实时读数为准**，怀疑过期就重读 `TASKS_JSON_FORMAT.md` 第三章。

常见故障：
- **任务被静默跳过**：多为余额不足（预检跳过记 failed，error_msg="积分不足：需 X 剩 Y"）或指纹重复。查 `--list --filter-status failed`。
- **no-option 失败**：aspect_ratio 写了 gpt_image_2_5 不支持的值（仅 自动/1:1/16:9/9:16/4:3/3:4/3:2/2:3/21:9）。不扣积分，改 JSON 重跑。
- **NODE_OPTIONS 报错**：脚本内部会自动清理；若在 WorkBuddy 终端跑仍报 node 驱动错误，改用 `cmd /c` 包裹执行。
- **Git Bash 的 ls/tail 报 shim 错误**：列目录用内置 Glob/Grep 工具，不用 shell 命令。

## §4 批次目录规范（工坊制）

```
工坊\批次\YYYYMMDD_语义名\
├── 任务_<语义名>.json      # 可多个（多轮迭代），保留哪些由人类判断
├── images\                 # 全部候选图（含落选），不重命名、不清理、不外搬
├── manifest_审核.json       # 审核页数据
├── 审核页_<语义名>.html     # build_review_page.py 产出
└── README.md               # 3~5 行：模型/参数、规范依据、官方基准、方案要点、状态
```

- 目录建一次、原地待久；收尾不改名不挪位置，只在 `_台账.md` 更新状态。
- `_台账.md` 登记行模板：`| \`YYYYMMDD_批次名/\` | N | NM | YYYY-MM-DD | 进行中 | — |`
- 状态流转：`进行中` → `已挑图待转正` → `已交付`（人类操作后）/ `放弃`。

## §5 转正流程（仅人类手工，AI 不代做）

1. 用户在审核页挑中图 → 告知 AI 或自己动手。
2. 压缩：`py\compress_inplace.py`（单图 ≤300KB 合格，>1MB 绝对禁止入库；透明背景 PNG 禁止有损压缩，palette 近无损/lossless）。
3. 复制进交付套图目录（如 `chibi_style_v2\duck\`），文件名对齐 `{阵营}_{角色名}.png`。
4. 在批次 `README.md` 与 `_台账.md` 各记一行去向。

AI 在收尾时可以**输出转正建议清单**（哪张压到多少、复制到哪），但执行权归人类。
