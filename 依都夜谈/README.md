# 依都夜谈 · 微信端

瀬尾依都在指定微信群接话。支持 @、引用、拍一拍、低频主动插话、图片与表情接话，以及北京时间 23:00 群报。群聊会过滤挑衅和无效插话。看图需启用媒体接入并配置可用的视觉模型。

1. 在 `AstrBot/` 准备 [AstrBot v4.29.3](https://github.com/AstrBotDevs/AstrBot/tree/v4.29.3) 及其 Python 环境，在 `dashboard/dist/` 放对应 WebUI。保留本仓库的依都插件。面板监听本机 6186。
2. 在 `AstrBot/data/plugins/astrbot_plugin_wechat_native/` 安装 [WeChat Native 固定提交](https://github.com/neozhu/astrbot-plugin-wechat-native/tree/a005b5ad5ff3897aaf44c41f256b99ed66d0f2cd)。进入该目录，用 `git apply` 应用 [WeChat Native 补丁](patches/wechat-native.patch)。
3. 将 [Agent WeChat v2.7.1](https://github.com/thisnick/agent-wechat/releases/tag/v2.7.1) 的 Windows x64 二进制保存为 `agent-wechat/wx-v2.7.1-win32-x64.exe`。复制 `server.example.toml` 为 `server.toml`。按 [Agent WeChat 文档](https://thisnick.github.io/agent-wechat/use/api/) 配置本机凭据及微信账号槽，再扫码登录。
4. 双击「依都开关.cmd」可启停、重启、扫码登录及查看日志。在 AstrBot 添加 WeChat Native，平台 ID 为 `ito_wechat`，API 地址为 `http://127.0.0.1:6174`，按实际填写账号 ID、凭据路径和群白名单。群回复模式用 `probability`，由依都插件决定实际触发。
5. 复制 `瀬尾 依都-人格卡.example.md` 为 `瀬尾 依都-人格卡.md`。在 AstrBot 建同名人格「瀬尾 依都」并设为默认。卡内的 Q/A 示例会和核心人格一起热同步。按 `日报目标.example.json` 创建 `日报目标.json`，填写目标群和起始日期。

双 Key 为可选项。若使用，在 AstrBot 源码根目录用 `git apply` 应用 [Gemini 补丁](patches/astrbot-gemini.patch)，建立名为 `google_gemini` 的原生模型来源，然后用「填写 Gemini 双 Key」配置。双 Key 先试免费，遇到 HTTP 429 或 503 再用付费 Key。直接走付费时，来源只填付费 Key，保持 `gm_rate_limit_fallback` 关闭。

本地资料可选。风格样本用环境变量 `ITO_STYLE_CORPUS_DIR`，见[句读工坊](../句读工坊/)。个人资料用 `ITO_PERSONAL_KB_PATH`，见[自画像](../自画像/)。命中的资料片段会进入模型上下文。

要给固定成员设置互动风格，把 `依都关系.example.json` 复制为 `依都关系.json`，填 `group_id`、本人微信 ID `owner_wxid`，以及可选的 `member_defaults`。后者用微信 ID 作为键，值可包含 `name`、`familiarity`、`affinity`、`banter_level` 和 `banter_cap`。群消息范围由 AstrBot 群白名单控制。指定本人账号后，符合筛选条件的本人发言会作为额外风格样本保存在本机 `plugin_data`。

主动接话判断可用 `google_gemini_free` 来源的 Key，按需查证公开事实用 `google_gemini` 来源。两者使用代码中配置的 Gemini Flash-Lite 辅助模型。启用互动和日报记忆整理时，在 AstrBot 里添加 ID 为 `gemini_ito_lite` 的模型。主聊天使用会话里选定的模型。

## 群内调参和表情包

填好 `依都关系.json` 里的 `owner_wxid` 后，用该账号在群里 @ 依都或引用她的话来执行命令。

| 命令 | 效果 |
| --- | --- |
| `调参` | 查看当前参数。 |
| `调参 友善 75`、`调参 冒泡门槛 8` | 即时调整对应参数。时间项以秒为单位，看图概率使用 0 到 1 的小数。 |
| `记住规则 <内容>`、`清空规则` | 保存或清空长期聊天要求。 |
| `闭嘴 15分钟`、`说话` | 暂停或恢复回复。静音期间也暂停定时群报，重启会解除静音。 |
| `存表情 <名字>` | 在带图片或引用图片、表情包的消息里发送，把素材保存到本地。 |

`依都调参面板.json` 会在首次启动时生成，也可先从 [默认配置](依都调参面板.example.json) 复制。表情包可直接放进同级的 `表情包/` 目录，以文件名匹配。依都支持按请求发表情包，也可以视聊天场景配图。主动配图受冷却时间和连续发送限制。

补丁基线是 AstrBot `f61a7f42696da6df25dc7a249ec9b8d54ed9da18` 和 WeChat Native `a005b5ad5ff3897aaf44c41f256b99ed66d0f2cd`，分别沿用 [AGPL-3.0](patches/ASTRBOT-AGPL-3.0.txt) 和 [MIT](patches/WECHAT-NATIVE-MIT.txt)。
