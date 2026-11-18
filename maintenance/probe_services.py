"""Test public endpoints in an isolated core without altering the active client."""

import argparse
import asyncio
import copy
import json
import re
import socket
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
    "X-image": "https://pbs.twimg.com/profile_images/1683325380441128960/yRsRRjGO_400x400.jpg",
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
            body = response.read(32768)
            status = response.status
            if name.startswith("X-"):
                magic = b"\xff\xd8\xff" if name == "X-image" else (b"\x00\x00\x01\x00", b"\x89PNG\r\n\x1a\n")
                if not response.headers.get_content_type().startswith("image/") or not body.startswith(magic):
                    raise ValueError("Not the expected image")
            else:
                data = json.loads(body)
                valid = (
                    (name == "Binance" and isinstance(data.get("serverTime"), int))
                    or (name == "Kraken" and data.get("error") == [] and isinstance(data.get("result", {}).get("unixtime"), int))
                    or (name == "Bitget" and data.get("code") == "00000" and str(data.get("data", {}).get("serverTime", "")).isdigit())
                    or (name == "Backpack" and str(data).isdigit())
                )
                if not valid:
                    raise ValueError("Unexpected public time response")
        error = None
    except urllib.error.HTTPError as exc:
        status, error = exc.code, "http_response"
    except Exception as exc:
        status, error = None, type(exc).__name__ + ": " + str(exc)[:180]
    return {"service": name, "host": urllib.parse.urlparse(url).hostname, "status": status,
            "seconds": round(time.monotonic() - started, 2), "error": error}


def market_quote(name, message):
    if message in ("pong", b"pong"):
        return False
    d = json.loads(message)
    if not isinstance(d, dict):
        return False
    if d.get("error") or d.get("event") == "error" or d.get("success") is False or ("code" in d and "msg" in d):
        raise ValueError(f"{name}: public subscription rejected")
    def prices(row, bid, ask):
        try:
            return float(row[bid]) > 0 and float(row[ask]) > 0
        except (KeyError, TypeError, ValueError):
            return False
    if name == "Binance":
        return d.get("s") == "BTCUSDT" and "u" in d and prices(d, "b", "a")
    if name == "Backpack":
        tick = d.get("data", d)
        return (isinstance(tick, dict) and tick.get("e") == "bookTicker"
                and tick.get("s") == "SOL_USDC" and prices(tick, "b", "a"))
    rows = d.get("data") or []
    if name == "Kraken":
        return d.get("channel") == "ticker" and any(row.get("symbol") == "BTC/USD" and prices(row, "bid", "ask") for row in rows)
    arg = d.get("arg", {})
    return (name == "Bitget" and arg.get("channel") == "ticker" and arg.get("instId") == "BTCUSDT"
            and any(prices(row, "bidPr", "askPr") for row in rows))


async def stream(proxy, name, seconds, controller, country, node):
    url, subscription = STREAMS[name]
    count, control, started, chain = 0, 0, time.monotonic(), None
    report = {"service": name, "country": country, "node": node}
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
            last = time.monotonic()
            deadline = last + seconds
            while time.monotonic() < deadline:
                if time.monotonic() - last >= 45:
                    raise TimeoutError("No valid market quote for 45 seconds")
                remaining = deadline - time.monotonic()
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=min(45, remaining))
                except asyncio.TimeoutError:
                    if time.monotonic() >= deadline:
                        break
                    raise TimeoutError("No public market messages for 45 seconds")
                if market_quote(name, message):
                    count += 1
                    last = time.monotonic()
                    if count == 1:
                        host = urllib.parse.urlsplit(url).hostname
                        active = (await asyncio.to_thread(request_json, controller, "/connections")).get("connections") or []
                        chain = next((c for c in active if c["metadata"].get("host") == host and
                                      c.get("rulePayload") == "Pipi" and
                                      {node, "pipi", r.region_name(country, "Nodes")} <= set(c.get("chains", []))), None)
                        if not chain:
                            raise RuntimeError("Expected live Pipi rule and selected node not observed")
                else:
                    control += 1
            if count < 2 or time.monotonic() - last >= 45:
                raise RuntimeError("No sustained public market stream")
            report["status"] = "passed"
    except Exception as exc:
        report.update(status="failed", error=type(exc).__name__ + ": " + str(exc)[:200])
    finally:
        if pinger:
            pinger.cancel()
            await asyncio.gather(pinger, return_exceptions=True)
    return {**report, "seconds": round(time.monotonic() - started, 1), "quotes": count, "other": control,
            "chain": chain["chains"] if chain else None, "rule": chain["rulePayload"] if chain else None}


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
    report = {"rest": {}, "streams": [], "note": "Public endpoints only. No login, trade or transfer."}
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
                        if "pipi" not in request_json(controller, "/proxies").get("proxies", {}):
                            time.sleep(0.1)
                            continue
                        with socket.create_connection(("127.0.0.1", config["mixed-port"]), timeout=1):
                            pass
                        break
                    except OSError:
                        if proc.poll() is not None:
                            raise RuntimeError("Isolated test core stopped during startup")
                        time.sleep(0.2)
                else:
                    raise RuntimeError("Isolated test proxy did not open its listener")
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
                        report["streams"].extend({"country": country, "service": name, "status": "no-tested-node"}
                                                 for name in args.only_streams)
                        continue
                    selector = r.region_name(country, "Nodes")
                    request_json(controller, "/proxies/" + urllib.parse.quote(selector, safe=""), {"name": chosen[country]})
                    for name in ("pipi", r.X):
                        request_json(controller, "/proxies/" + urllib.parse.quote(name, safe=""), {"name": selector})
                    report["rest"][country] = [endpoint(proxy, name, url) for name, url in REST.items()]
                    print(json.dumps({"country": country, "checks": report["rest"][country]}, ensure_ascii=False), flush=True)
                    async def all_streams():
                        return await asyncio.gather(*(stream(proxy, name, args.seconds, controller, country, chosen[country])
                                                      for name in args.only_streams))
                    print(f"Starting public WebSocket observation: {country}", flush=True)
                    report["streams"].extend(asyncio.run(all_streams()))
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
    if (any(s["status"] != "passed" for s in report["streams"])
            or any(isinstance(results, dict) or any(row["error"] for row in results) for results in report["rest"].values())):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
