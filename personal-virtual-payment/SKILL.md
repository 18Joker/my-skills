---
name: personal-virtual-payment
description: Guide for integrating WeChat Mini Program virtual payment for personal-entity developers (individual, resident ID, utility category). Covers activation, item purchase (short_series_goods), delivery push, order query, refund, settlement and fees. Trigger when the user asks to enable or integrate virtual payment for a personal mini program, or configure wx.requestVirtualPayment. 个人主体小程序虚拟支付接入指引。
---

# 个人主体小程序虚拟支付接入

为进一步支持个人开发者实现可持续经营，激发个人主体的创新活力，微信小程序平台将在符合条件的类目范围内，向个人主体小程序开放虚拟支付能力。

## Overview

本技能为**个人主体**小程序提供虚拟支付接入流程，覆盖从开通到上线的完整闭环：

- 核对开通条件（个人主体、工具类目、认证备案）
- MP 后台开通虚拟支付并获取关键参数
- 道具直购接入（`wx.requestVirtualPayment`）
- 服务端签名、发货推送、查单兜底
- 退款、结算、费率、发票说明
- 部署前检查清单验收

**适用范围**：仅个人主体小程序，服务类目含「工具」，月支付限额 10 万元。

## 1. 开通条件核对

| 条件 | 说明 |
| --- | --- |
| 个人主体 | 小程序主体为个人，开发者持有居民身份证 |
| 服务类目 | 小程序服务类目含「工具」 |
| 认证与备案 | 已完成小程序认证、备案 |

> **限额**：个人主体小程序**月支付限额为 10 万元**（含 Android、iOS 等所有终端）。

## 2. 开通流程（MP 后台）

打开浏览器登录微信开放平台（mp.weixin.qq.com）：

1. 左侧栏找到并点击【支付与交易 - 虚拟支付】
2. 点击【开通】→ 勾选同意协议 → 填写个人资料（个人身份信息、提现账户、支付管理员）
3. 提交后等待审核，一般为 5 分钟内
4. 刷新页面、确认审核通过后，扫码签约

### 开通后获取 3 个关键信息

| 信息 | 它是什么 | 在哪找 |
| --- | --- | --- |
| AppID | 小程序的「身份证号」 | MP 后台 → 设置 |
| OfferID | 你的支付账号 | 虚拟支付 → 基本配置 |
| 现网AppKey | 支付密钥 | 虚拟支付 → 基本配置 |

同时，需在【道具管理】里创建商品（道具），记下道具 ID 和价格，并完成发布。

### iOS 支付额外条件

如需在 iOS 端使用支付：
1. **配置小程序简称**（Apple 支付需展示 display name）。配置入口：mp.weixin.qq.com → 虚拟支付 → 基础配置
2. 配置后，在虚拟支付 → 基本配置中**开通苹果 IAP 支付**

## 3. 开发接入

### 3.1 支付与现有业务流程串接

虚拟支付只是把「收钱」环节接入小程序已有业务流程。整体闭环：

```text
用户打开小程序 → 登录 → 选择要购买的功能/道具 → 点击「购买」
     ↓
① 前端请求服务器下单 → 服务器生成唯一单号 outTradeNo，保存订单（状态：待支付）
     ↓
② 服务器返回 payData → 前端调用 wx.requestVirtualPayment 拉起支付
     ↓
③ 支付成功后，服务器通过两条路径确认并完成发货：
   路径 A：收到平台「发货推送」→ 直接发货
   路径 B：推送丢失时，定时调用 query_order 查单 → 查到已支付就补发货
     ↓
④ 前端查询自己服务器的订单状态 → 展示「购买成功」并开放权益
```

关键点：
- `outTradeNo`：商家自己生成的业务单号，下单时必填，须唯一
- `wx_order_id`：平台返回的单号，跟踪订单、发货、对账以此为准
- 发货以「发货推送」为主，推送丢失时用 `query_order` 查单兜底；**前端支付回调不作为发货依据**

### 3.2 前端接入（小程序端）

调用基础库接口 `wx.requestVirtualPayment`（签名 = 防伪校验）。payData 由服务端生成并签名。

```javascript
function buyGoods(payData) {
  wx.requestVirtualPayment({
    ...payData,
    success(res) { wx.showToast({ title: '支付成功' }); },
    fail(err) { wx.showToast({ title: '支付失败', icon: 'none' }); }
  });
}
```

**iOS 版本限制**：iOS 端需微信客户端 **8.0.68 及以上版本**。调用支付前先校验，不满足时提示用户更新微信至最新版。

**payData 核心字段**：

| 字段 | 说明 |
| --- | --- |
| signData | 支付参数 JSON 字符串（服务端生成）： |
| ├ offerId | OfferID（虚拟支付商户号） |
| ├ buyQuantity | 购买数量 |
| ├ env | 环境标识，固定填 0 |
| ├ currencyType | 币种，固定填 CNY |
| ├ productId | 道具 ID |
| ├ goodsPrice | 道具单价（分），需与后台道具价格一致 |
| ├ outTradeNo | 业务单号（必填，须唯一，如 `T` + 时间戳 + 随机数） |
| └ attach | 透传数据（必填，发货时原样透传） |
| mode | 固定 `short_series_goods`（道具直购） |
| paySig | 服务端用 AppKey 对 `requestVirtualPayment&signData` 做 HMAC-SHA256 |
| signature | 服务端用 sessionKey 对 signData 做 HMAC-SHA256（用户态签名） |

### 3.3 服务端接入

#### 3.3.1 接收发货推送

- 需先部署「消息推送接收」能力。使用**腾讯云开发**时，可借助微信开发者工具 Skills 自动完成该部分部署与配置；其余服务端逻辑（下单、查单、发货）由代码实现
- 在 MP 后台【虚拟支付 → 基本配置 → 基础配置 → 发货推送配置】填服务器 URL

推送核心字段：

| 字段 | 说明 |
| --- | --- |
| Event | 固定 `xpay_goods_deliver_notify` |
| OpenId | 用户 openid（确定发货给谁） |
| OutTradeNo | 商家下单时传入的业务单号 |
| WeChatPayInfo.MchOrderNo | 平台单号 wx_order_id（跟踪订单、幂等去重，以此为准） |
| GoodsInfo.ProductId | 道具 ID |
| GoodsInfo.Quantity | 购买数量（按数量发放） |

服务器处理逻辑：
1. 解析 XML，取平台单号 `wx_order_id`（位于 `WeChatPayInfo.MchOrderNo` 字段）
2. **幂等**（同一订单重复通知只发一次货）：查本地订单表，若该 wx_order_id 已发货则直接返回成功
3. 发货：根据 `OpenId` 和道具 ID，给对应用户发放对应数量，更新订单状态
4. 返回 `0` 表示成功，否则平台会重试（最多 15 次）

应答格式：

```xml
<xml><ErrCode>0</ErrCode><ErrMsg><![CDATA[success]]></ErrMsg></xml>
```

#### 3.3.2 查询订单（兜底发货）

接口：`POST /xpay/query_order`（带 pay_sig 签名）

```json
{
  "openid": "用户openid",
  "env": 0,
  "order_id": "业务订单号 outTradeNo"
}
```

> ⚠️ 参数名是 `order_id`（开发者传入的 outTradeNo），不是 `out_trade_no`。

用于：推送丢失时主动查单补发货，建议定时每 5 分钟查一次，查到已支付就发货。

#### 3.3.3 服务端接口清单

| 接口 | 作用 |
| --- | --- |
| `POST /pay/order` | 生成 outTradeNo + signData + paySig，返回给前端去支付 |
| `POST /pay/notify` | 接收发货推送，验签后发货，返回 XML |
| `POST /pay/query` | 转发调用 query_order，供兜底查单 |

### 3.4 签名算法（两套签名）

#### 支付签名 paySig（服务端算，AppKey 是密钥）

```python
import hmac, hashlib

def calc_pay_sig(uri, post_body, appkey):
    """uri 不带问号参数。
    - C 端（wx.requestVirtualPayment 下单）：uri 固定为 requestVirtualPayment
    - B 端（服务端 /xpay/* 接口）：uri 为实际接口路径，如 /xpay/query_order
    """
    msg = uri + '&' + post_body          # post_body 是真正发出去的原始字符串
    return hmac.new(appkey.encode('utf-8'), msg.encode('utf-8'),
                    hashlib.sha256).hexdigest()
```

#### 用户态签名 signature（服务端算，sessionKey 是密钥）

```python
def calc_signature(post_body, session_key):
    return hmac.new(session_key.encode('utf-8'), post_body.encode('utf-8'),
                    hashlib.sha256).hexdigest()
```

## 4. 退款、结算与订单查询

### 4.1 退款

| 终端 | 退款方式 | 说明 |
| --- | --- | --- |
| Android 等 | 开发者主动退款 | 在 MP 后台【虚拟支付 → 交易订单】操作退款，或用 `refund_order` 接口发起；退款完成后收到 `xpay_refund_notify` 推送 |
| iOS | 用户向 App Store 申请 | 开发者无法主动退款；用户申请后由 Apple 决定，退款成功收到 `xpay_refund_notify` |

> 手续费规则：支付时间 180 天以内的退款，平台退还手续费；超过 180 天的退款，平台不退还手续费。

### 4.2 结算

| 终端 | 结算周期 | 费率 | 说明 |
| --- | --- | --- | --- |
| Android 等 | T+3 | 1% | 腾讯技术服务费 |
| iOS | 约 45-60 天 | 12% | Apple 佣金 |

- **提现**：资金到账后，可在 MP 后台【虚拟支付】查看账户余额、每日账单并发起提现
- **发票**：可在**次月 5 号后**申请开具上个月的腾讯技术服务费发票

### 4.3 订单查询

- 页面查询：MP 后台【虚拟支付 → 交易订单】，可按支付渠道切换「普通支付 / Apple 支付」
- 接口查询：`query_order`（见 3.3.2），可用于核对订单与退款状态

## 5. Agent 注意事项

1. **用户告知**：向用户确认开放条件（个人主体、工具类目、认证备案）与**月支付限额 10 万元**，并说明退款、结算与费率规则（见第四节）
2. **接入范围**：只做道具直购，不引入代币等额外功能
3. **outTradeNo**：每次下单重新生成、保证唯一（8-32 位，不能以下划线开头），不能复用
4. **签名**：严格按 3.4 节实现；`post_body` 必须与实际请求体完全一致（不格式化、不改键顺序）；`appkey` 用正式 AppKey；`sessionKey` 通过 `auth.code2Session` 获取
5. **发货**：以 `wx_order_id` 做幂等去重；`success` 回调可能丢失（用户异常退出会丢），以「发货推送」为主、`query_order` 查单兜底
6. **金额与 env**：金额单位是「分」，全程不要换算；`env` 固定填 `0`（正式环境/现网）

## 6. 部署前检查清单

- [ ] 开放条件确认：个人主体 + 中国大陆居民身份证 + 服务类目为「工具」+ 已完成认证、备案
- [ ] 已了解并告知用户：全终端月支付限额为 10 万元
- [ ] MP 后台虚拟支付已开通
- [ ] 已拿到 AppID / OfferID / 现网AppKey
- [ ] 若需 iOS 支付：已配置小程序简称
- [ ] 消息推送接收已部署（腾讯云开发可用开发者工具 Skills 自动完成）
- [ ] MP 后台已配置发货推送 URL，并完成一笔测试支付验证
- [ ] 服务器验签逻辑通过（签名函数与官方文档签名示例核对一致）
- [ ] 发货推送已做幂等（以 wx_order_id 去重）
- [ ] 前端 wx.requestVirtualPayment 打通，支付成功并收到发货推送
- [ ] 兜底查单逻辑已就绪（query_order）
- [ ] 已向用户说明退款规则、结算周期与费率（Android 1%、iOS 12%）
- [ ] 上线后用小额真单验证：支付 → 推送 → 发货 → 后台账单金额一致

## 参考资源

- 个人主体接入指引：https://developers.weixin.qq.com/miniprogram/dev/platform-capabilities/business-capabilities/virtual-payment/person
- 客户端 API：https://developers.weixin.qq.com/miniprogram/dev/api/payment/wx.requestVirtualPayment.html
- 小程序简称配置：https://developers.weixin.qq.com/community/develop/doc/0004221455ce78d413893d4b75b009