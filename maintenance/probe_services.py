"""Test public endpoints in an isolated core without altering the active client."""

import argparse
import asyncio
import copy
import json
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import websockets
import yaml

import check_core
import routing as r

REST = {
    "Bitget": "https://api.bitget.com/api/v2/public/time",
    "Kraken": "https://api.kraken.com/0/public/Time",
    "Backpack": "https://api.backpack.exchange/api/v1/time",
    "Binance": "https://api.binance.com/api/v3/time",
    "X-icon": "https://abs.twimg.com/favicons/twitter.3.ico",
    "X-image-host": "https://pbs.twimg.com/",
}
STREAMS = {
    "Bitget": ("wss://ws.bitget.com/v2/ws/public", {"op": "subscribe", "args": [{"instType": "SPOT", "channel": "ticker", "instId": "BTCUSDT"}]}),
    "Kraken": ("wss://ws.kraken.com/v2", {"method": "subscribe", "params": {"channel": "ticker", "symbol": ["BTC/USD"]}}),
    "Backpack": ("wss://ws.backpack.exchange", {"method": "SUBSCRIBE", "params": ["bookTicker.SOL_USDC"], "id": 1}),
    "Binance": ("wss://stream.binance.com:443/ws/btcusdt@bookTicker", None),
}


def request_json(controller, path, data=None):
    request = urllib.request.Request(controller + path, data=json.dumps(data).encode() if data is not None else None,
                                     method="PUT" if data is not None else "GET",
                                     headers={"Authorization": "Bearer routing-offline-test-only", "Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=15) as response:
        body = response.read()
        return json.loads(body) if body else None


def endpoint(proxy, name, url):
    started = time.monotonic()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    try:
        with opener.open(urllib.request.Request(url, headers={"User-Agent": "routing-public-connectivity-test"}), timeout=18) as response:
            response.read(1000)
            status = response.status
        error = None
    except urllib.error.HTTPError as exc:
        status, error = exc.code, "http_response"
    except Exception as exc:
        status, error = None, type(exc).__name__ + ": " + str(exc)[:180]
    return {"service": name, "host": urllib.parse.urlparse(url).hostname, "status": status,
            "seconds": round(time.monotonic() - started, 2), "error": error}


async def stream(proxy, name, seconds):
    url, subscription = STREAMS[name]
    count, started, first, last = 0, time.monotonic(), None, None
    async def app_ping(ws):
        while True:
            await asyncio.sleep(20)
            await ws.send("ping")
    pinger = None
    try:
        # Binance sends its own Ping frames; websockets automatically replies Pong.
        interval = None if name == "Binance" else 20
        async with websockets.connect(url, proxy=proxy, open_timeout=20, ping_interval=interval, ping_timeout=20) as ws:
            if subscription:
                await ws.send(json.dumps(subscription))
            if name == "Bitget":
                pinger = asyncio.create_task(app_ping(ws))
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=min(45, remaining))
                except asyncio.TimeoutError:
                    if time.monotonic() >= deadline:
                        break
                    raise TimeoutError("No public market messages for 45 seconds")
                if message:
                    count += 1
                    last = time.monotonic() - started
                    first = first if first is not None else last
            if count < 2:
                raise RuntimeError("No sustained public market stream")
            return {"service": name, "status": "passed", "seconds": round(time.monotonic() - started, 1), "messages": count}
    except Exception as exc:
        return {"service": name, "status": "failed", "seconds": round(time.monotonic() - started, 1),
                "messages": count, "error": type(exc).__name__ + ": " + str(exc)[:200]}
    finally:
        if pinger:
            pinger.cancel()
            await asyncio.gather(pinger, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--private-nodes", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=900)
    parser.add_argument("--countries", nargs="+", choices=["TW", "JP"], default=["TW", "JP"])
    parser.add_argument("--only-streams", nargs="+", choices=list(STREAMS), default=list(STREAMS))
    args = parser.parse_args()
    base = yaml.safe_load((args.output / "oldstore/mihomo-substore-template.yaml").read_text())
    nodes = yaml.safe_load(args.private_nodes.read_text())["proxies"]
    sources = check_core.resolve_sources(base, args.output)
    report = {"rest": {}, "streams": [], "note": "No account login, trade or transfer. X image host root status is not an image rendering test."}
    with tempfile.TemporaryDirectory(prefix="routing-probe-") as tmp:
        root = Path(tmp)
        config = check_core.materialize(copy.deepcopy(base), root, sources)
        config["proxies"] = nodes
        config["log-level"] = "warning"
        config["dns"]["enable"] = False
        for group in config["proxy-groups"]:
            if group["type"] == "url-test":
                group["lazy"] = True
        path = root / "config.yaml"
        path.write_text(check_core.dump_config(config))
        path.chmod(0o600)
        with (root / "core.log").open("w") as log:
            proc = subprocess.Popen([args.core, "-d", str(root), "-f", str(path)], stdout=log, stderr=log)
            controller = "http://" + config["external-controller"]
            proxy = "http://127.0.0.1:" + str(config["mixed-port"])
            try:
                for _ in range(60):
                    try:
                        request_json(controller, "/version")
                        break
                    except OSError:
                        time.sleep(0.2)
                chosen = {}
                for country in args.countries:
                    candidates = [n["name"] for n in nodes if re.search(r.region_filter(country), n["name"])]
                    candidates.sort(key=lambda n: ("IPv6" in n, "电信" in n, "Dynamic" in n, "Extreme" not in n))
                    for node in candidates[:4]:
                        try:
                            result = request_json(controller, "/proxies/" + urllib.parse.quote(node, safe="") + "/delay?timeout=6000&url=" + urllib.parse.quote("https://www.gstatic.com/generate_204", safe=""))
                            if result.get("delay") is not None:
                                chosen[country] = node
                                break
                        except (OSError, ValueError):
                            continue
                    if country not in chosen:
                        report["rest"][country] = {"error": "No tested node reached the connectivity probe"}
                        continue
                    selector = r.region_name(country, "Nodes")
                    request_json(controller, "/proxies/" + urllib.parse.quote(selector, safe=""), {"name": chosen[country]})
                    for name in ("pipi", r.X):
                        request_json(controller, "/proxies/" + urllib.parse.quote(name, safe=""), {"name": selector})
                    report["rest"][country] = [endpoint(proxy, name, url) for name, url in REST.items()]
                    print(json.dumps({"country": country, "checks": report["rest"][country]}, ensure_ascii=False), flush=True)
                if chosen:
                    country = "TW" if "TW" in chosen else "JP"
                    request_json(controller, "/proxies/pipi", {"name": r.region_name(country, "Nodes")})
                    async def all_streams():
                        return await asyncio.gather(*(stream(proxy, name, args.seconds) for name in args.only_streams))
                    print("Starting public WebSocket observation", flush=True)
                    report["streams"] = asyncio.run(all_streams())
                try:
                    connections = request_json(controller, "/connections").get("connections") or []
                    report["connections"] = [{"host": c["metadata"].get("host"), "rule": c.get("rule"), "rulePayload": c.get("rulePayload"), "chains": c.get("chains")} for c in connections if c["metadata"].get("host")]
                except OSError:
                    pass
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
