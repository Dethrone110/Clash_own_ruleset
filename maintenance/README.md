# Routing maintenance

The default branch `rm` owns the source files and the daily workflow. `optrule`
publishes rule lists; `oldstore` publishes the native Stash override and the
Mihomo/Sub-Store template. Airport subscription URLs, proxy credentials and
client state do not belong in any branch.

## Update

Edit `maintenance/manual/*.list`, not the generated public lists. Service rules
use `DOMAIN` and `DOMAIN-SUFFIX`; user-owned `own_direct.list` is preserved
verbatim, but must now contain only explicit domains/suffixes. Region aliases, groups and
precedence are defined once in `routing.py` for all three template formats.

```sh
python -m pip install -r maintenance/requirements.txt
python maintenance/routing.py --cache .routing-work/upstreams --output build
python -m unittest discover -s maintenance -v
python maintenance/check_core.py --core /path/to/mihomo --output build
```

The builder fetches every upstream before writing outputs, validates payload
types and minimum rule counts, removes IP/ASN/process/keyword rules from shared
service lists, rejects blanket shared-cloud/SaaS routes and compacts redundant
suffixes. Explicit service tenants such as `openai-api.arkoselabs.com` remain
eligible only for their curated category. The public suffix snapshot ships with
the pinned publicsuffixlist wheel: ICANN suffix rules abort publication, and
private hosting namespaces require a curated match. Web3 exclusions remove
Crunchbase and parked Slingshot endpoints even if an upstream reintroduces them.
The public authentication list contains exact shared hosts, not the
entire Auth0, Stripe, Sentry or Cloudflare domain trees.

`rules-manifest.json` records input URLs, SHA-256 hashes, upstream update
comments, output counts, check time and added/removed rules. A successful fetch
does not mean the upstream author has updated its contents recently.

The workflow runs around 03:15 Asia/Taipei daily. Scheduled runs publish only
rule lists and their manifest. Source changes on `rm` also refresh templates;
manual runs offer the same option. It checks all remaining remote providers
and exercises full Mihomo rule order (including LAN, external sets and GEO)
against labeled loopback sinks. It also starts the official core with populated and empty groups before
publishing. A failing fetch, parser, regression or core check prevents any
branch update. Ref updates are fast-forward only; a concurrent change aborts
publication. GitHub may delay scheduled workflows or disable an inactive
repository's schedules; check the Actions page rather than assuming a timer ran.

## Service sources

- Backpack website, API and WebSocket: https://docs.backpack.exchange/
- Bitget API: https://www.bitget.com/docs/classic/rest-api ; its website currently references `static.bgbstatic.com`.
- Kraken: https://docs.kraken.com/exchange/guides/overview
- Binance: https://developers.binance.com/en/docs/introduction
- Hyperliquid: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api
- Lighter: https://github.com/elliottech/lighter-python
- Aster: https://docs.asterdex.com/
- Paradex: https://docs.paradex.trade/
- Polymarket: https://docs.polymarket.com/
- OpenAI: https://help.openai.com/en/articles/9247338
- Cursor network/authentication: https://cursor.com/docs/enterprise/network-configuration ; https://cursor.com/help/troubleshooting/sign-in-domains
- Google country domains: https://www.google.com/supported_domains

External Crypto/Web3, OpenAI/Gemini and Twitter lists are additional inputs,
not unfiltered client-side providers. Their exact URLs and content hashes are
included in each generated manifest.

## Optional local network diagnosis

```sh
python -m pip install websockets==16.0
python maintenance/probe_services.py --core /path/to/mihomo --output build \
  --private-nodes /private/path/airport.yaml --report /private/path/report.json
```

This runs a separate loopback-only core, probes public REST endpoints through
each requested region's selected node and observes four public market WebSockets
for 15 minutes per region. Only quotes with the intended symbol and bid/ask count;
heartbeats are separate and missing live policy/region/node evidence fails the check. It
does not change the active router/client, authenticate to exchanges, place
orders or transfer assets. Private node data is only written to a temporary
directory and removed when the test core stops. X is tested with a concrete JPEG
and a favicon, not the media host root. Actual app rendering still needs a client test.

Name matching identifies advertised regions, not independently verified exit
locations. A delay probe verifies its test URL, not a trading account's access
rights. Selecting `公共验证` affects every service that uses those exact shared
hosts; domain-only rules cannot identify the embedding website.
