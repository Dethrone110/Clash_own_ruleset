"""Offline core parser and runtime group checks; no airport credentials needed."""

import argparse
import concurrent.futures
import copy
import json
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import yaml

import routing as r


class QuotedString(str):
    pass


class CoreDumper(yaml.SafeDumper):
    pass


CoreDumper.add_representer(QuotedString, lambda dumper, value: dumper.represent_scalar("tag:yaml.org,2002:str", str(value), style='"'))


def dump_config(config):
    config = copy.deepcopy(config)
    # Hex strings such as 1e123456 must not become scientific notation in Go YAML.
    for node in config.get("proxies", []):
        reality = node.get("reality-opts", {})
        if "short-id" in reality:
            reality["short-id"] = QuotedString(reality["short-id"])
    return yaml.dump(config, Dumper=CoreDumper, allow_unicode=True, sort_keys=False)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def resolve_sources(config, output):
    def one(item):
        name, provider = item
        local = output / "optrule" / provider["url"].rsplit("/", 1)[-1]
        try:
            return name, local.read_text() if local.exists() else r.fetch(provider["url"])
        except Exception as exc:
            raise RuntimeError(f"Provider {name} failed: {provider['url']}: {exc}") from exc
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        return dict(pool.map(one, config["rule-providers"].items()))


def materialize(config, root, sources):
    for name, provider in config["rule-providers"].items():
        text = sources[name]
        path = root / provider["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        provider.pop("url", None)
        provider.pop("interval", None)
        provider["type"] = "file"
    # Country databases are unnecessary when testing explicit service routes.
    config["rules"] = [line for line in config["rules"] if not line.startswith(("GEOSITE,", "GEOIP,"))]
    config["mixed-port"] = free_port()
    config["allow-lan"] = False
    config["dns"]["listen"] = "127.0.0.1:0"
    config["external-controller"] = f"127.0.0.1:{free_port()}"
    config["secret"] = "routing-offline-test-only"
    config["log-level"] = "error"
    return config


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--core", required=True)
    p.add_argument("--output", type=Path, default=Path("build"))
    p.add_argument("--private-nodes", type=Path)
    args = p.parse_args()
    base = yaml.safe_load((args.output / "oldstore" / "mihomo-substore-template.yaml").read_text())
    actual = yaml.safe_load(args.private_nodes.read_text())["proxies"] if args.private_nodes else []
    matched_actual = [node for node in actual if re.search(r.region_filter(), node["name"])]
    sources = resolve_sources(base, args.output)
    for scenario in ("nodes", "empty"):
        with tempfile.TemporaryDirectory(prefix="routing-core-") as tmp:
            root = Path(tmp)
            config = materialize(copy.deepcopy(base), root, sources)
            if scenario == "nodes":
                config["proxies"] = actual or [{"name": code + " Extreme 01", "type": "socks5", "server": "127.0.0.1", "port": 9} for code in r.REGIONS]
            for g in config["proxy-groups"]:
                if g["type"] == "url-test":
                    g["url"] = "http://127.0.0.1:9/check"
            filename = root / "config.yaml"
            filename.write_text(dump_config(config))
            filename.chmod(0o600)
            result = subprocess.run([args.core, "-t", "-d", str(root), "-f", str(filename)], capture_output=True, text=True, timeout=45)
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            log = (root / "core.log").open("w")
            proc = subprocess.Popen([args.core, "-d", str(root), "-f", str(filename)], stdout=log, stderr=log)
            try:
                url = "http://" + config["external-controller"] + "/proxies"
                request = urllib.request.Request(url, headers={"Authorization": "Bearer " + config["secret"]})
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                for _ in range(60):
                    try:
                        with opener.open(request, timeout=1) as response:
                            proxies = json.load(response)["proxies"]
                        break
                    except (OSError, ValueError):
                        if proc.poll() is not None:
                            raise RuntimeError((root / "core.log").read_text())
                        time.sleep(0.1)
                else:
                    raise TimeoutError("Test core controller did not start")
                for code in r.REGIONS:
                    auto = proxies[r.region_name(code, "Auto")]
                    nodes = proxies[r.region_name(code, "Nodes")]
                    expected = [n["name"] for n in (actual or config.get("proxies", [])) if re.search(r.region_filter(code), n["name"])] if scenario == "nodes" else []
                    assert set(auto["all"]) == set(expected) | {"REJECT"}, (code, auto["all"], expected)
                    assert nodes["now"] == r.region_name(code, "Auto"), nodes
                    if scenario == "empty":
                        assert auto["now"] == "REJECT", auto
                assert proxies["pipi"]["now"] == r.region_name("TW", "Auto")
                assert proxies[r.X]["now"] == r.region_name("JP", "Auto")
                assert proxies[r.AUTH]["now"] == r.AI
                print(json.dumps({"scenario": scenario, "parser": "passed", "runtime_groups": "passed", "airport_records": len(actual), "matched_nodes": len(matched_actual)}, ensure_ascii=False))
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                log.close()


if __name__ == "__main__":
    main()
