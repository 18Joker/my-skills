# 公告系统字段规范（announcements 集合）

> 来源：`cloudfunctions/announcement-admin/index.js`（发布端校验与文档构建）与 `utils/announcement-service.js`（前端读取）。以实时代码为准，本文件为 2026-08-13 快照。

## 集合与文档结构

数据存于云数据库 `announcements` 集合，单条文档结构：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | string | 业务可读 ID：`ann_{YYYYMMDD}_{4位随机}`，如 `ann_20260810_8f6e` |
| `type` | string | 公告类型，5 选 1，见下表 |
| `title` | string | 标题，**非空且 ≤ 30 字** |
| `summary` | string | 摘要，**≤ 80 字**（列表页/开屏展示用） |
| `content_md` | string | 正文 markdown；update / dev_talk / important / urgent **必填** |
| `cover_url` | string | 封面图 URL，可选 |
| `action` | object \| null | 关联动作（按钮），见「动作机制」 |
| `status` | string | `published` / `archived` |
| `publish_time` | number | 发布时间戳（ms），默认当前时间 |
| `expire_time` | number | 过期时间戳（ms），**默认 = publish_time + 15 天**（ANN_EXPIRE_DAYS=15） |
| `pin` | boolean | 是否置顶，**全库已置顶 ≤ 2 条** |
| `weekly_index` | number | ISO 周年周序号，用于每周 ≤ 7 条的频次统计 |
| `created_by` / `created_at` / `updated_at` | — | 创建者 OPENID / 创建 / 更新时间 |

## 类型枚举（ANN_TYPES）

| type | label | 展示样式 |
|---|---|---|
| `update` | 更新公告 | 主色（蓝绿） |
| `dev_talk` | 开发者说 | 鹅绿 |
| `important` | 重要通知 | 中性金 |
| `urgent` | 紧急公告 | 鸭红 |
| `survey` | 调研投票 | 蓝色 |

前端展示元数据唯一来源：`utils/announcement-types.js`（label / icon / color / dim / glow）。

## 动作机制（action）

action 是公告底部的引导按钮，结构 `{ type, payload, label }`：

| type | 含义 | 要求 |
|---|---|---|
| `link` | 跳转外链 | 必须带 `payload`（链接） |
| `survey` | 外部问卷 | 必须带 `payload`（问卷链接） |
| `join_group` | 加入用户群 | payload 可空，label 如「加入交流群提建议」 |
| `feedback` | 意见反馈 | payload 可空 |

规则：action 存在时 type 必须在上述 4 类中，且**必须带 label（按钮文案）**。

## 频次治理规则（发布端自动执行）

- **紧急降级**：同一自然日已发布过 1 条 `urgent`，第二条自动降级为 `important`（仅告警）。
- **置顶上限**：全库已置顶（pin=true 且 published）≥ 2 条时，新置顶请求直接报错（400005），需先下架旧置顶。
- **周频次软提示**：本周（按 `weekly_index`）已发布 ≥ 7 条时给出"建议明天再发"提示，不阻止。
- **紧急公告内容轻校验**：`urgent` 正文必须命中 `/影响|恢复|预计|时间/` 之一，否则报错 400001。
- **调研校验**：`survey` 必须配置 `action.type=survey` 且有 payload。

## 前端读取接口（服务层）

`utils/announcement-service.js`（统一经 `_call` 走云函数 `ocr-card-tracker`）：
- `getAnnouncements({since, limit, type})` — 列表，增量同步
- `getAnnouncementDetail(id)` — 详情
- `markAnnouncementRead(id)` / `markAllAnnouncementsRead(ids)` — 已读
- `markBannerDismissed(id, sessionId)` — 首页标签收起
- `getSplashAnnouncement()` — 开屏公告（最新一条未读）

发布入口为独立云函数 `cloudfunctions/announcement-admin`，仅开发者 OPENID 白名单可调，前端不暴露。

## 发布前核对清单

1. type 合法；2. title ≤ 30 字非空；3. summary ≤ 80 字；4. 正文非空（除 survey）；5. urgent 含影响/恢复表述；6. survey 带问卷 action；7. action 合法且带 label；8. pin 置顶不超 2 条；9. expire_time 默认 15 天。
