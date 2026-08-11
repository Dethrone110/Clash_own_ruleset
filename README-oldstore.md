# oldstore 双客户端工作流

这个分支把“机场节点”和“分流规则”拆开维护：机场负责更新节点，GitHub 负责策略组、远程规则源和规则顺序。不要再把机场订阅交给公共 Subconverter。

## 文件

- `stash-rules.stoverride`：Stash 远程覆写，只接管策略组、规则源和规则，不包含或改写机场节点。
- `mihomo-substore-template.yaml`：Sub-Store 生成 OpenClash/Mihomo 完整配置时使用的远程模板。
- `optrule/pipi_account.list`：CEX、托管账户和交易平台，命中 `pipi-a`。
- `optrule/pipi.list`：钱包、RPC、DeFi、浏览器、数据和 NFT，命中 `pipi-b`；同时保留旧用户兼容内容。
- `optrule/ganggang.list`：香港银行、支付、券商和 IBKR，命中 `ganggang`。

## Stash

机场原生订阅地址和覆写地址各司其职：

1. 在 Stash 中导入机场提供的原生 Stash 订阅，并保持它为当前配置。
2. 添加并启用下面的远程覆写：

   `https://raw.githubusercontent.com/Dethrone110/Clash_own_ruleset/oldstore/stash-rules.stoverride`

3. 也可以使用一键安装地址：

   `https://link.stash.ws/install-override/raw.githubusercontent.com/Dethrone110/Clash_own_ruleset/oldstore/stash-rules.stoverride`

4. 第一次启动后检查策略组：
   - `🇺🇸 AI-US` 默认使用 `🇺🇸 US Auto`；美国全断时，手动切换到 JP、SG、UK、TW、DE 或 AU。
   - `pipi-a` 默认使用 `🇹🇼 TW Auto`；也可以选 JP，或进入对应 `Nodes` 锁定具体节点。
   - `pipi-b` 默认使用 `🇯🇵 JP Auto`，并提供全部非美国地区作为手动候选。
   - `ganggang` 默认使用 `🇭🇰 HK Auto`，其中包含 HK Extreme 和 HK Dynamic。
   - `🚀 Proxy` 会直接展开机场全部实际节点，也保留 `🌐 All Nodes` 作为统一入口。
5. 以后在 Stash 更新机场配置即可更新节点；覆写和远程规则源独立更新。

Stash 这条路径不需要 Sub-Store、Subconverter、MITM，也不使用 `api.wcc.best`。覆写不会改动 VLESS、HY2、Reality 的密钥或参数。

## OpenClash

Sub-Store 只在生成或更新主配置时需要在线。可以通过家中局域网访问，也可以在外面通过 Tailscale 访问 x86 小主机；OpenClash 日常运行不依赖 Sub-Store 持续在线。

1. 在私有 Sub-Store 中建立订阅 `airport`，填入机场原始订阅地址。
2. 建立一个 Mihomo 配置文件，远程模板使用：

   `https://raw.githubusercontent.com/Dethrone110/Clash_own_ruleset/oldstore/mihomo-substore-template.yaml`

3. 添加“从订阅加入代理”操作，来源选 `airport`，关闭 `includeUnsupportedProxy`。
4. 生成 Clash.Meta/Mihomo 完整配置链接。
5. OpenClash 选择 Meta/Mihomo 内核，订阅上一步的完整配置链接。
6. 机场更新节点时：先刷新 Sub-Store 的 `airport`，再让 OpenClash 更新配置。
7. GitHub 只更新域名列表时，`rule-providers` 会自行刷新，不必重新生成主 YAML。
8. GitHub 更新 `mihomo-substore-template.yaml` 的策略组时，先刷新 Sub-Store 文件，再更新 OpenClash。

不要把机场原始订阅地址、Sub-Store 私有分享链接或认证信息提交到 GitHub。

## 出口映射

| 策略 | 默认出口 | 可选范围 |
|---|---|---|
| `🇺🇸 AI-US` | US Auto | US 全部节点；手动备用 JP、SG、UK、TW、DE、AU |
| `pipi-a` | TW Auto | TW/JP 全部节点，同国自动或锁定具体节点 |
| `pipi-b` | JP Auto | JP/TW/SG/HK/UK/DE/AU 全部节点 |
| `ganggang` | HK Auto | HK 全部节点 |
| `📢 Social` / `✖️ X` | All Auto | 全部国家、全部节点，也可 DIRECT |
| `Ⓜ️ Microsoft` | All Auto | 全部国家、全部节点；Copilot 由前面的 AI-US 捕获 |
| `🍎 Apple` | DIRECT | 全部国家和全部节点均可手动选择 |
| `🚀 Proxy` | All Auto | 直接展开全部原始节点，同时提供全部国家和 `All Nodes` |

地区组按本机场的命名体系识别 `US/TW/JP/SG/HK/UK/DE/AU`，同时兼容 `[vless]`、`[Hy2]`、Hysteria 协议前缀、国旗、ISO 代码、国家中英文名和对应主要城市名。节点名还必须包含 Extreme、Prestige、Ultimate、`Ultiamte`、Max、Dynamic、HY2、IPv6 或数字编号之一，因此套餐说明、剩余流量和重置日期不会误入节点组。所有套餐等级仍统一留在所属地区，不再分层。

所有关键过滤组都显式包含 `REJECT`。机场改名导致筛选为空时会中止连接，不会静默退回 `DIRECT`。`AI-US` 的非美国路线只作为手动灾备，自动测速不会跨国切换。

AI 灾备顺序为 JP、SG、UK、TW、DE、AU：前两者延迟较低，英国和德国作为欧美路线补充，台湾距离近；当前 AU 节点均为 IPv6 Only，因此放在最后。上述地区均在 OpenAI、Gemini 和 Claude 的官方支持地区内，但账号风控仍可能取决于注册地、付款方式和长期登录轨迹。

## 域名修正

- `bankofchina.com`、`unionpay.com` 明确前置 `DIRECT`。
- `bochk.com`、`bochk.com.hk`、`unionpayintl.com` 使用 `ganggang`。
- 如果中银香港 App 将来调用某个专用 `bankofchina.com` 子域，只在日志确认后添加该精确子域，不扩大整个主域。

## 更新与回滚

- Stash：更新前保留当前可用配置；发生异常时先停用此覆写，即可回到机场原生规则。
- OpenClash：保留上一份可用配置并关闭自动覆盖；新配置验证通过后再设为主配置。
- Sub-Store 离线时，OpenClash 继续使用最后缓存的 YAML，只是暂时不能更新节点。
- 停用旧的 `api.wcc.best` 地址前，比较机场原始订阅与最终 YAML 中 VLESS、HY2、Reality 节点数量。

## 验收清单

- `deepseek.com`、`bigmodel.cn`、`kimi.com` 命中 `🎯 Direct`。
- `openai.com`、`google.com`、`youtube.com` 命中 `🇺🇸 AI-US`。
- Binance、OKX、Bybit 等账户平台命中 `pipi-a`。
- MetaMask、WalletConnect、Alchemy、Uniswap、Etherscan 等命中 `pipi-b`。
- `bochk.com`、`unionpayintl.com`、IBKR 命中 `ganggang`。
- `bankofchina.com`、`unionpay.com` 命中 `🎯 Direct`。
- `pipi-a` 的 TW/JP 自动组不跨国家；对应 `Nodes` 可锁定具体节点。
- `pipi-b` 不出现 US，但会完整保留其他地区的 Dynamic 和 IPv6 Only 节点。
- `Proxy`、Social、X、Microsoft、Apple 均能进入 `All Nodes`，并看到全部国家候选。
- 每个实际节点只归入一个地区，套餐说明、流量和重置日期条目不进入任何地区。

参考：[Stash 覆写说明](https://stash.wiki/configuration/override)、[Stash 策略组说明](https://stash.wiki/proxy-protocols/proxy-groups)、[Sub-Store 项目说明](https://github.com/sub-store-org/Sub-Store)、[OpenAI 支持地区](https://help.openai.com/en/articles/5347006-openai-api-supported-countries-and-territories)、[Gemini 支持地区](https://support.google.com/gemini/answer/13575153)、[Claude 支持地区](https://www.anthropic.com/supported-countries)。
