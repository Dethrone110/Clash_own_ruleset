# Stash / OpenClash / Clash Verge 分流配置

机场负责节点，GitHub 负责策略组和分流。节点参数不经过公共订阅转换。

## 本次调整

- `pipi-a`（交易所）与 `pipi-b`（其他 Web3）合并为 `pipi`，默认 TW Auto。
- `pipi` 可手动选择 US/TW/JP/SG/HK/UK/DE/AU；同一国家的 Auto 不会跨国测速。
- AI、Google、YouTube 继续共用 `🇺🇸 AI-US`，默认 US Auto，并保留非美国手动备用。
- X 默认 JP Auto，主页、API、头像、图片、视频都使用 `✖️ X`。
- `🔐 公共验证` 默认 AI-US，也能单独切到 pipi、Proxy 或 REJECT。
- Proxy、Social、Microsoft 默认 JP Auto；Apple 默认 DIRECT；ganggang 默认 HK Auto。
- 国家 Auto/Nodes 保留所有套餐等级、IPv6、Dynamic、电信专用节点。节点能否连接仍取决于当前网络。
- 国家 Nodes 首选该国 Auto，仍能手动锁定具体节点。关键组无节点时拒绝连接。
- 停用 `192.168.6.218` 整机强制分流，按服务处理每台设备的流量。

业务组、国家组、节点三层足够完成日常选择。多个业务选中同一个国家 Nodes 时，会共享那个 Nodes 组的当前选择。需要固定出口时选定一个可用节点；Auto 测速成功只说明测速地址可达。

## Stash

1. 保留机场原生 Stash 订阅为当前配置。
2. 更新并启用远程覆写：
   `https://raw.githubusercontent.com/Dethrone110/Clash_own_ruleset/oldstore/stash-rules.stoverride`
3. 更新远程规则源，检查 pipi、X、公共验证以及各国 Auto/Nodes。
4. 机场更新只更新节点；规则列表独立更新。策略组改变时才需要更新覆写。

覆写替换策略组、规则集合和规则，不改写代理或机场远程代理集；不需要 MITM。不要把 Mihomo 完整模板当作 Stash 覆写。

## OpenClash / Clash Verge

1. Sub-Store 保留机场原始订阅。
2. 文件的远程模板继续使用：
   `https://raw.githubusercontent.com/Dethrone110/Clash_own_ruleset/oldstore/mihomo-substore-template.yaml`
3. 保留“从订阅加入代理”操作，生成完整 Mihomo YAML。
4. 刷新远程模板及文件预览，再让 OpenClash / Clash Verge 更新该文件的原订阅链接。
5. OpenClash 使用 Mihomo/Meta 内核。第一次切换前保留当前可用配置，先执行配置检查。

Sub-Store 的私有文件链接不变。只更新域名列表时，无需重新生成主 YAML；客户端的 rule-providers 每日刷新。GitHub 上的 `rules-manifest.json` 可以查看来源、数量、内容摘要和更新时间。

## 更新后的选择

新建的 pipi 会默认选择 TW Auto。已有客户端会缓存其他组的选择：如果 Proxy 原来选中 All Auto，更新后仍可能保留该选择，需要手动切到 JP Auto；若某个国家 Nodes 原来选中 REJECT，也需要重新选择 Auto 或具体节点。

普通域名规则无法区分“同一个验证码域名是被 AI 还是交易所调用”。公共验证默认优先 AI 的美国出口；遇到确认由此引起的交易所验证故障，再单独调整该组。

机场广告的地区名称不等于已经核验的出口国家。更换节点后，可查看目标服务的连接记录和实际出口，不以节点套餐名称判断线路可用性。

## 验证与回滚

- Bitget：主页、`api.bitget.com`、`ws.bitget.com`、`static.bgbstatic.com` 应命中 pipi。
- Kraken：主页、Pro、REST、WebSocket 应命中 pipi。
- Backpack：钱包 `backpack.app` 和交易所 `backpack.exchange`、API、WebSocket 均命中 pipi。
- Binance：主页、账号入口、REST、行情流和 `bnbstatic.com` 均命中 pipi。
- X：`x.com`、`pbs.twimg.com`、`abs.twimg.com`、`video.twimg.com` 命中 X。
- `openai.com`、`claude.ai`、`google.com`、`youtube.com` 命中 AI-US；中国 AI API 命中 DIRECT。

HTTP 200 只能证明对应公开请求成功；登录、图片渲染和应用内行情仍需在实际客户端确认。排查时记录域名、命中规则、完整代理链、错误类型，并在同一节点和备用节点之间做对照，不只看延迟数字。

Stash 可停用覆写回到机场配置；OpenClash/Verge 可切回更新前保留的 YAML。需要恢复 `.218` 的整机规则时，在自定义规则中手动添加 `SRC-IP-CIDR,192.168.6.218/32,pipi`，放在专用业务规则之后；默认模板不启用它。

旧 Subconverter INI 继续保留原地址，但不负责修复旧转换器对 VLESS/HY2/Reality 的支持问题。
