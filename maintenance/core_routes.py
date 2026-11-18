"""Exercise the real Mihomo matcher with local-only, labeled proxy destinations."""

import base64
import contextlib
import copy
import http.client
import json
import socket
import socketserver
import subprocess
import threading
import time

import routing as r


class RouteSink(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(5)
        command = self.rfile.readline(4096)
        if not command.startswith(b"CONNECT "):
            return
        auth = http.client.parse_headers(self.rfile).get("Proxy-Authorization", "")
        label = base64.b64decode(auth.removeprefix("Basic ")).split(b":")[0]
        self.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        if self.rfile.readline(4096).startswith(b"GET "):
            self.wfile.write(b"HTTP/1.1 204 No Content\r\nX-Route: " + label + b"\r\nConnection: close\r\n\r\n")


def check(core, root, config, dump):
    cases = json.loads((r.HERE / "acceptance.json").read_text())
    cases["router.lan"] = "DIRECT"
    ordinary = {"www.crunchbase.com", "canto-project.example.net", "rebus-project.example.net",
                "slingshot-project.example.net", "unrelated.s3.amazonaws.com", "other.zaticdn.com"}
    config = copy.deepcopy(config)
    config["hosts"] = {host: "192.0.2.5" for host in set(cases) | ordinary}
    config["dns"] = {"enable": False}
    config["sniffer"] = {"enable": False}
    config["proxy-groups"] = []
    config["proxies"] = []
    labels = {}
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), RouteSink) as sink:
        sink.daemon_threads = True
        # Predicates, provider contents, ports and order remain intact. Only the
        # outbound action is replaced, so no request ever reaches a bank.
        for i, rule in enumerate(config["rules"]):
            fields = rule.split(",")
            idx = 1 if fields[0] == "MATCH" else 2
            policy = fields[idx]
            if policy not in labels:
                label = labels[policy] = "audit-" + str(len(labels))
                config["proxies"].append({"name": label, "type": "http", "server": "127.0.0.1",
                                          "port": sink.server_address[1], "username": label, "password": "local"})
            fields[idx] = labels[policy]
            config["rules"][i] = ",".join(fields)
        policies = {v: k for k, v in labels.items()}
        path = root / "route-audit.yaml"
        path.write_text(dump(config))
        threading.Thread(target=sink.serve_forever, daemon=True).start()
        try:
            with (root / "route-audit.log").open("w") as log:
                proc = subprocess.Popen([core, "-d", str(root), "-f", str(path)], stdout=log, stderr=log)
                try:
                    for _ in range(300):
                        if proc.poll() is not None:
                            raise RuntimeError((root / "route-audit.log").read_text())
                        try:
                            with socket.create_connection(("127.0.0.1", config["mixed-port"]), timeout=.25):
                                break
                        except OSError:
                            time.sleep(.1)
                    else:
                        raise RuntimeError("Mihomo audit listener did not start")
                    for host in sorted(set(cases) | ordinary):
                        with contextlib.closing(http.client.HTTPConnection("127.0.0.1", config["mixed-port"], timeout=10)) as conn:
                            port = 4001 if host.startswith(("hdc1.", "mcgw1")) else 443
                            conn.request("GET", f"http://{host}:{port}/audit")
                            response = conn.getresponse()
                            policy = policies.get(response.getheader("X-Route"))
                        if host in cases and policy != cases[host]:
                            raise AssertionError(f"{host}: full matcher selected {policy}, expected {cases[host]}")
                        if host in ordinary and policy not in {r.PROXY, r.DIRECT, "🐟 Final"}:
                            raise AssertionError(f"{host}: unexpected special policy {policy}")
                    print(f"Full matcher: {len(cases)} expected routes and {len(ordinary)} ordinary-site controls passed")
                finally:
                    proc.terminate()
                    try:
                        proc.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
        finally:
            sink.shutdown()
