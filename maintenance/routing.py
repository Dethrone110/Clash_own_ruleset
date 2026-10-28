"""Build public rule lists and all three client templates from shared inputs."""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import hashlib
import ipaddress
import json
import re
import shutil
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = "https://raw.githubusercontent.com/Dethrone110/Clash_own_ruleset/optrule/"
AI, X, AUTH = "🇺🇸 AI-US", "✖️ X", "🔐 公共验证"
PROXY, DIRECT, SOCIAL = "🚀 Proxy", "🎯 Direct", "📢 Social"
REGIONS = {
    "US": ("🇺🇸", "US|USA|United States|UnitedStates|America|美国|美國|Los Angeles|LosAngeles|San Jose|SanJose|Seattle|New York|NewYork", 180),
    "TW": ("🇹🇼", "TW|TWN|Taiwan|台湾|台灣|Taipei|台北", 150),
    "JP": ("🇯🇵", "JP|JPN|Japan|日本|Tokyo|东京|東京|Osaka|大阪", 150),
    "SG": ("🇸🇬", "SG|SGP|Singapore|新加坡|狮城|獅城", 150),
    "HK": ("🇭🇰", "HK|HKG|Hong Kong|HongKong|香港", 150),
    "UK": ("🇬🇧", "UK|GB|GBR|United Kingdom|UnitedKingdom|Britain|英国|英國|London|伦敦|倫敦", 180),
    "DE": ("🇩🇪", "DE|DEU|Germany|Deutschland|德国|德國|Frankfurt|法兰克福|法蘭克福", 200),
    "AU": ("🇦🇺", "AU|AUS|Australia|澳大利亚|澳大利亞|澳洲|Sydney|悉尼|雪梨", 200),
}
SOURCE_SPECS = {
    "Crypto": ("pipi", "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Crypto/Crypto.list", 100),
    "Web3": ("pipi", "https://raw.githubusercontent.com/szkane/ClashRuleSet/main/Clash/Web3.list", 100),
    "OpenAI": ("ai", "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/OpenAI/OpenAI.list", 10),
    "Gemini": ("ai", "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Gemini/Gemini.list", 5),
    "Google": ("us", "https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/Ruleset/Google.list", 10),
    "GoogleDomains": ("us", "https://www.google.com/supported_domains", 100),
    "YouTube": ("us", "https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/Ruleset/YouTube.list", 5),
    "Twitter": ("x", "https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/Ruleset/Twitter.list", 8),
}
# A shared SaaS/cloud suffix is not evidence that all its tenants use a service.
SHARED_ROOTS = {
    "auth0.com", "arkoselabs.com", "cloudflare.com", "cloudflareinsights.com",
    "stripe.com", "stripe.network", "sentry.io", "segment.io", "algolia.net",
    "launchdarkly.com", "intercom.io", "intercomcdn.com", "statsig.com",
    "statsigapi.net", "featuregates.org", "identrust.com", "observeit.net",
    "livekit.cloud", "datadoghq.com", "usefathom.com", "workos.com",
    "workoscdn.com", "ably.io", "braze.eu", "siftscience.com",
    "cloudfront.net", "cloudflare.net", "azureedge.net", "azurefd.net",
    "windows.net", "imgix.net", "aliyuncs.com", "aliyun.com", "alicdn.com",
    "alibabausercontent.com", "myqcloud.com", "firebaseapp.com", "firebaseio.com",
    "amazonaws.com", "akamaized.net", "akamaihd.net", "hcaptcha.com", "appspot.com",
    "github.io", "vercel.app", "netlify.app", "pages.dev", "workers.dev", "r2.dev",
    "supabase.co", "supabase.com", "onrender.com", "azurewebsites.net", "web.app",
}
KNOWN_TYPES = {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "DOMAIN-REGEX",
               "IP-CIDR", "IP-CIDR6", "IP-ASN", "PROCESS-NAME", "USER-AGENT"}
DOMAIN_RE = re.compile(r"(?=.{3,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}$")


def domain_rules(text: str) -> set[str]:
    rules = set()
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        parts = [p.strip() for p in line.split(",")]
        if parts[0] not in KNOWN_TYPES or len(parts) < 2:
            raise ValueError(f"Invalid rule payload at line {number}: {line[:90]}")
        if parts[0] not in {"DOMAIN", "DOMAIN-SUFFIX"}:
            continue
        if len(parts) != 2:
            raise ValueError(f"Unexpected policy/flags in domain rule: {line[:90]}")
        host = parts[1].rstrip(".").lower().encode("idna").decode("ascii")
        if not DOMAIN_RE.fullmatch(host):
            raise ValueError(f"Invalid domain: {host}")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError(f"IP literal is not a service domain: {host}")
        rules.add(f"{parts[0]},{host}")
    return rules


def matches(host: str, rule: str) -> bool:
    kind, value = rule.split(",", 1)
    return host == value or (kind == "DOMAIN-SUFFIX" and host.endswith("." + value))


def compact(rules: set[str]) -> list[str]:
    suffixes = {r.split(",", 1)[1] for r in rules if r.startswith("DOMAIN-SUFFIX,")}
    result = []
    for rule in sorted(rules, key=lambda r: (r.split(",")[1], r.split(",")[0])):
        kind, host = rule.split(",", 1)
        parents = host.split(".")
        if any(".".join(parents[i:]) in suffixes for i in range(1, len(parents))):
            continue
        if kind == "DOMAIN" and host in suffixes:
            continue
        result.append(rule)
    return result


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Clash-own-ruleset-maintenance/1"})
    with urllib.request.urlopen(request, timeout=35) as response:
        if response.status != 200:
            raise ValueError(f"HTTP {response.status}: {url}")
        data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError(f"Oversized rule source: {url}")
        return data.decode("utf-8-sig")


def source_rules(name: str, text: str) -> set[str]:
    if name == "GoogleDomains":
        text = "\n".join("DOMAIN-SUFFIX," + host.strip().lstrip(".") for host in text.splitlines() if host.strip())
    return domain_rules(text)


def load_upstreams(cache: Path, offline: bool = False) -> dict[str, str]:
    def one(item):
        name, (_, url, minimum) = item
        path = cache / f"{name}.list"
        text = path.read_text() if offline else fetch(url)
        rules = source_rules(name, text)
        if len(rules) < minimum:
            raise ValueError(f"Source {name} has only {len(rules)} domain rules; expected >= {minimum}")
        return name, text
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        payloads = dict(pool.map(one, SOURCE_SPECS.items()))
    if not offline:
        cache.mkdir(parents=True, exist_ok=True)
        for name, text in payloads.items():
            (cache / f"{name}.list").write_text(text)
    return payloads


def build_lists(payloads: dict[str, str]) -> tuple[dict[str, list[str]], dict]:
    manual = {p.stem: domain_rules(p.read_text()) for p in (HERE / "manual").glob("*.list") if p.stem != "own_direct"}
    rules = copy.deepcopy(manual)
    report = {"sources": {}, "outputs": {}}
    dedicated = set().union(*manual.values())
    for name, text in payloads.items():
        category, url, _ = SOURCE_SPECS[name]
        parsed = source_rules(name, text)
        accepted = set()
        for rule in parsed:
            host = rule.split(",", 1)[1]
            shared = any(host == root or host.endswith("." + root) for root in SHARED_ROOTS)
            if not shared or rule in dedicated:
                accepted.add(rule)
        rules[category] |= accepted
        report["sources"][name] = {
            "url": url, "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "domain_rules": len(parsed), "accepted": len(accepted),
            "upstream_updated": next((s.strip("# ") for s in text.splitlines() if "UPDATED:" in s), None),
        }
    # The old account list remains downloadable, but new templates use one pipi.
    rules["pipi"] |= rules["pipi_account"]
    for category in ("ai", "us", "pipi", "x"):
        rules[category] -= rules["public_auth"]
    rules["ai"] -= rules["china_ai"]
    rules["us"] -= rules["china_ai"]
    result = {name: compact(items) for name, items in rules.items()}
    for name, items in result.items():
        report["outputs"][name] = {"rules": len(items), "sha256": hashlib.sha256("\n".join(items).encode()).hexdigest()}
    return result, report


def region_name(code: str, kind: str) -> str:
    return f"{REGIONS[code][0]} {code} {kind}"


def region_filter(code: str | None = None) -> str:
    flags = "|".join(v[0] for v in REGIONS.values()) if code is None else REGIONS[code][0]
    aliases = "|".join(v[1] for v in REGIONS.values()) if code is None else REGIONS[code][1]
    prefix = rf"(({flags})\s*)?(\[(vless|hy2|hysteria|hysteria2|hysteria 2|hysteria-2)\]\s*)?(({flags})\s*)?"
    return rf"(?i)^{prefix}({aliases})(\s|-|_)+(Extreme|Prestige|Ultimate|Ultiamte|Max|Dynamic|HY2|IPv6|[0-9]).*$"


def groups() -> list[dict]:
    def choices(codes):
        return [region_name(code, kind) for code in codes for kind in ("Auto", "Nodes")]
    def select(name, options):
        return {"name": name, "type": "select", "proxies": list(dict.fromkeys(options))}
    countries = ["JP", "TW", "SG", "HK", "US", "UK", "DE", "AU"]
    common = choices(countries)
    result = [
        select(PROXY, [region_name("JP", "Auto"), "🌍 All Auto", *common, "REJECT"]),
        select(AI, [*choices(["US", "JP", "SG", "UK", "TW", "DE", "AU"]), PROXY, "REJECT"]),
        select("pipi", [*choices(["TW", "JP", "SG", "HK", "US", "UK", "DE", "AU"]), PROXY, "REJECT"]),
        select("ganggang", [*choices(["HK"]), PROXY, "REJECT"]),
        select(X, [*common, PROXY, "REJECT"]),
        select(AUTH, [AI, "pipi", PROXY, "REJECT"]),
        select(SOCIAL, [*common, "DIRECT", PROXY, "REJECT"]),
        select("Ⓜ️ Microsoft", [*common, "DIRECT", PROXY, "REJECT"]),
        select("🍎 Apple", ["DIRECT", *common, PROXY, "REJECT"]),
        select(DIRECT, ["DIRECT", PROXY]),
        select("🛑 Block", ["REJECT", "DIRECT"]),
        select("🍃 Clean", ["REJECT", "DIRECT"]),
        select("🐟 Final", [PROXY, DIRECT, "REJECT"]),
    ]
    for code in [None, *REGIONS]:
        auto = region_name(code, "Auto") if code else "🌍 All Auto"
        result.append({"name": auto, "type": "url-test", "url": "https://www.gstatic.com/generate_204",
                       "interval": 600, "lazy": True, "tolerance": REGIONS[code][2] if code else 180,
                       "proxies": ["REJECT"], "include-all": True, "filter": region_filter(code)})
        if code:
            result.append({"name": region_name(code, "Nodes"), "type": "select",
                           "proxies": [auto, "REJECT"], "include-all": True, "filter": region_filter(code)})
    return result


def providers() -> dict:
    original = json.loads((HERE / "providers.json").read_text())
    for name in ("OpenAI", "Gemini", "PipiAccount", "Crypto", "Web3", "Hijacking", "pipiLocal", "Twitter"):
        original.pop(name, None)
    for name, filename in {"Pipi": "pipi", "Twitter": "x", "PublicAuth": "public_auth", "WhatsApp": "whatsapp", "Signal": "signal"}.items():
        original[name] = {"type": "http", "behavior": "classical", "format": "text",
                          "url": ROOT + filename + ".list", "path": f"./ruleset/{filename}.list", "interval": 86400}
    return original


def routing_rules() -> list[str]:
    pairs = [
        ("LocalAreaNetwork", "DIRECT"), ("MobilePush", "DIRECT"), ("ChinaAI", "DIRECT"),
        ("AI", AI), ("US", AI), ("ganggangLocal", "ganggang"), ("Pipi", "pipi"),
        ("Twitter", X), ("PublicAuth", AUTH), ("BanAD", "🛑 Block"), ("BanProgramAD", "🍃 Clean"),
        ("Telegram", SOCIAL), ("Discord", SOCIAL), ("Reddit", SOCIAL), ("Slack", SOCIAL),
        ("WhatsApp", SOCIAL), ("Signal", SOCIAL), ("Instagram", SOCIAL), ("Facebook", SOCIAL),
        ("Microsoft", "Ⓜ️ Microsoft"), ("Apple", "🍎 Apple"), ("OwnDirect", DIRECT),
        ("ProxyLite", PROXY), ("SteamCN", DIRECT), ("GoogleCN", DIRECT), ("ChinaDomain", DIRECT),
        ("ChinaCompanyIp", DIRECT), ("Download", DIRECT),
    ]
    result = ["RULE-SET,LocalAreaNetwork,DIRECT"]
    result += [f"DOMAIN-SUFFIX,{host},DIRECT" for host in ("bankofchina.com", "unionpay.com", "niu.com", "niucache.com")]
    result += [f"RULE-SET,{provider},{policy}" for provider, policy in pairs[1:]]
    return result + [f"GEOSITE,CN,{DIRECT}", f"GEOSITE,geolocation-!cn,{PROXY}",
                     f"GEOIP,CN,{DIRECT},no-resolve", "MATCH,🐟 Final"]


def templates() -> dict[str, str]:
    config = json.loads((HERE / "runtime.json").read_text())
    config.update({"proxies": [], "proxy-groups": groups(), "rule-providers": providers(), "rules": routing_rules()})
    mihomo = "# Generated by maintenance/routing.py. Airport proxies are injected by Sub-Store.\n" + yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
    stash = {"name": "Clash own ruleset", "desc": "Service routing with shared regional selectors",
             "mode": "rule", "profile": {"store-selected": True},
             "proxy-groups": config["proxy-groups"], "rule-providers": config["rule-providers"], "rules": config["rules"]}
    override = yaml.safe_dump(stash, allow_unicode=True, sort_keys=False)
    override = override.replace("proxy-groups:\n", "proxy-groups: #!replace\n", 1).replace("rule-providers:\n", "rule-providers: #!replace\n", 1).replace("rules:\n", "rules: #!replace\n", 1)
    ini = ["[custom]", "; Generated legacy Subconverter template. Prefer native Stash / Mihomo workflows."]
    for rule in config["rules"]:
        parts = rule.split(",")
        if parts[0] == "RULE-SET":
            ini.append(f"ruleset={parts[2]},{config['rule-providers'][parts[1]]['url']}")
        elif parts[0] == "MATCH":
            ini.append(f"ruleset={parts[1]},[]FINAL")
        else:
            position = 2
            ini.append(f"ruleset={parts[position]},[]" + ",".join(parts[:position] + parts[position + 1:]))
    for group in config["proxy-groups"]:
        options = ["[]" + p for p in group["proxies"]]
        if group.get("include-all"):
            options.append(group["filter"])
        entry = "custom_proxy_group=" + "`".join([group["name"], group["type"], *options])
        if group["type"] == "url-test":
            entry += f"`{group['url']}`600,,{group['tolerance']}"
        ini.append(entry)
    ini += ["enable_rule_generator=true", "overwrite_original_rules=true", ""]
    return {"mihomo-substore-template.yaml": mihomo, "stash-rules.stoverride": override,
            "ACL4SSR_Online_Mini_MultiMode.ini": "\n".join(ini)}


def validate(rule_lists: dict[str, list[str]]) -> None:
    configs = templates()
    template = yaml.safe_load(configs["mihomo-substore-template.yaml"])
    names = {g["name"] for g in template["proxy-groups"]}
    assert len(names) == len(template["proxy-groups"]) == 30
    edges = {g["name"]: [p for p in g["proxies"] if p in names] for g in template["proxy-groups"]}
    def visit(name, trail):
        if name in trail:
            raise ValueError("Policy group cycle: " + " -> ".join([*trail, name]))
        for child in edges[name]:
            visit(child, [*trail, name])
    for name in names:
        visit(name, [])
    for group in template["proxy-groups"]:
        assert all(p in names | {"REJECT", "DIRECT"} for p in group["proxies"])
    for rule in template["rules"]:
        if rule.startswith("RULE-SET,"):
            _, provider, policy = rule.split(",")
            assert provider in template["rule-providers"] and policy in names | {"DIRECT", "REJECT"}
    expected = json.loads((HERE / "acceptance.json").read_text())
    local = {"AI": "ai", "US": "us", "ChinaAI": "china_ai", "MobilePush": "mobile_push",
             "Pipi": "pipi", "Twitter": "x", "PublicAuth": "public_auth", "ganggangLocal": "ganggang"}
    for host, policy in expected.items():
        matched = None
        for rule in template["rules"]:
            parts = rule.split(",")
            if parts[0] in ("DOMAIN", "DOMAIN-SUFFIX") and matches(host, ",".join(parts[:2])):
                matched = parts[2]
                break
            if parts[0] == "RULE-SET" and parts[1] in local:
                if any(matches(host, r) for r in rule_lists[local[parts[1]]]):
                    matched = parts[2]
                    break
        if matched != policy:
            raise ValueError(f"First-match regression for {host}: {matched}, expected {policy}")


def write_build(output: Path, payloads: dict[str, str], previous: Path | None = None) -> dict:
    rules, report = build_lists(payloads)
    validate(rules)
    # Complete all parsing and checks before replacing an existing build directory.
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="routing-", dir=output.parent))
    for branch in ("optrule", "oldstore"):
        (staging / branch).mkdir()
    for name, entries in rules.items():
        text = f"# Generated {name} rules. Edit maintenance/manual/{name}.list on rm.\n" + "\n".join(entries) + "\n"
        (staging / "optrule" / f"{name}.list").write_text(text)
    shutil.copyfile(HERE / "manual" / "own_direct.list", staging / "optrule" / "own_direct.list")
    for name, text in templates().items():
        (staging / "oldstore" / name).write_text(text)
        if name.endswith(".ini"):
            (staging / "optrule" / name).write_text(text)
    report["checked_at"] = datetime.now(timezone.utc).isoformat()
    for name, entries in rules.items():
        old = (previous / f"{name}.list") if previous else output / "optrule" / f"{name}.list"
        old_rules = domain_rules(old.read_text()) if old.exists() else set()
        report["outputs"][name].update({"added": sorted(set(entries) - old_rules), "removed": sorted(old_rules - set(entries))})
    (staging / "optrule" / "rules-manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    backup = output.with_name(output.name + ".previous-build")
    if backup.exists():
        raise RuntimeError(f"Unresolved previous build backup: {backup}")
    if output.exists():
        output.rename(backup)
    try:
        staging.rename(output)
    except OSError:
        if backup.exists():
            backup.rename(output)
        raise
    if backup.exists():
        shutil.rmtree(backup)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("build"))
    parser.add_argument("--cache", type=Path, default=Path(".routing-cache"))
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--previous", type=Path, help="Previous optrule checkout for change statistics")
    args = parser.parse_args()
    report = write_build(args.output, load_upstreams(args.cache, args.offline), args.previous)
    print(json.dumps({name: data["rules"] for name, data in report["outputs"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
