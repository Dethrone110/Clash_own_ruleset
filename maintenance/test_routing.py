import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

import routing as r


class RoutingTests(unittest.TestCase):
    def test_parser_normalizes_and_rejects_bad_downloads(self):
        self.assertEqual(r.domain_rules("# title\nDOMAIN-SUFFIX, Example.COM\nDOMAIN-SUFFIX,example.com\nIP-ASN,20473,no-resolve\nUSER-AGENT,TikTok*"), {"DOMAIN-SUFFIX,example.com"})
        for text in ("<html>Not Found</html>", "DOMAIN-SUFFIX,com", "DOMAIN-SUFFIX,127.0.0.1", "DOMAIN-SUFFIX,example.com,DIRECT"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                r.domain_rules(text)

    def test_compaction_does_not_overmatch_siblings(self):
        self.assertEqual(r.compact({"DOMAIN-SUFFIX,example.com", "DOMAIN,a.example.com", "DOMAIN-SUFFIX,a.example.com", "DOMAIN,notexample.com"}), ["DOMAIN-SUFFIX,example.com", "DOMAIN,notexample.com"])

    def test_manual_sources_have_no_blanket_cloud_routes(self):
        for category in ("ai", "us", "mobile_push", "pipi"):
            rules = r.domain_rules((r.HERE / "manual" / f"{category}.list").read_text())
            for item in rules:
                self.assertNotIn(item, {"DOMAIN-SUFFIX," + d for d in r.SHARED_ROOTS})
        self.assertIn("DOMAIN-SUFFIX,backpack.exchange", r.domain_rules((r.HERE / "manual" / "pipi.list").read_text()))
        auth = r.domain_rules((r.HERE / "manual" / "public_auth.list").read_text())
        self.assertTrue(all(item.startswith("DOMAIN,") for item in auth))

    def test_golang_yaml_short_ids_keep_their_literal_value(self):
        import check_core
        node = {"name": "US Extreme 01", "reality-opts": {"short-id": "1e123456"}}
        output = check_core.dump_config({"proxies": [node]})
        self.assertIn('short-id: "1e123456"', output)
        self.assertEqual(yaml.safe_load(output)["proxies"][0], node)

    def test_failed_directory_swap_restores_last_good_build(self):
        cache = Path(".routing-work/upstreams")
        if not cache.exists():
            self.skipTest("Run the builder first")
        payloads = r.load_upstreams(cache, offline=True)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "build"
            output.mkdir()
            (output / "keep.txt").write_text("previous good output")
            original = Path.rename
            def fail_staging(path, destination):
                if path.name.startswith("routing-"):
                    raise OSError("Simulated filesystem failure")
                return original(path, destination)
            with patch.object(Path, "rename", fail_staging), self.assertRaises(OSError):
                r.write_build(output, payloads)
            self.assertEqual((output / "keep.txt").read_text(), "previous good output")

    def test_three_templates_have_same_policies_and_order(self):
        files = r.templates()
        meta = yaml.safe_load(files["mihomo-substore-template.yaml"])
        stash = yaml.safe_load(files["stash-rules.stoverride"])
        for key in ("proxy-groups", "rules", "rule-providers"):
            self.assertEqual(meta[key], stash[key])
        self.assertIn("rules: #!replace", files["stash-rules.stoverride"])
        ini = files["ACL4SSR_Online_Mini_MultiMode.ini"]
        policies = [line.split("=", 1)[1].split(",", 1)[0] for line in ini.splitlines() if line.startswith("ruleset=")]
        expected = [line.split(",")[2] if not line.startswith("MATCH,") else line.split(",")[1] for line in meta["rules"]]
        self.assertEqual(policies, expected)
        for old in ("pipi-a", "pipi-b", "SRC-IP-CIDR", "Hijacking", "All Nodes", "Direct-Extra"):
            self.assertNotIn(old, files["mihomo-substore-template.yaml"])
        self.assertNotIn("find-process-mode", meta)

    def test_defaults_and_empty_groups(self):
        groups = {g["name"]: g for g in r.groups()}
        for name, first in {r.AI: r.region_name("US", "Auto"), "pipi": r.region_name("TW", "Auto"), "ganggang": r.region_name("HK", "Auto"), r.X: r.region_name("JP", "Auto"), r.AUTH: r.AI, r.PROXY: r.region_name("JP", "Auto"), "🍎 Apple": "DIRECT"}.items():
            self.assertEqual(groups[name]["proxies"][0], first)
        for name in (r.AI, "pipi", "ganggang", r.X, r.PROXY):
            self.assertNotIn("DIRECT", groups[name]["proxies"])
            self.assertIn("REJECT", groups[name]["proxies"])
        for code in r.REGIONS:
            auto = groups[r.region_name(code, "Auto")]
            self.assertEqual((auto["interval"], auto["lazy"], auto["proxies"]), (600, True, ["REJECT"]))
            self.assertEqual(groups[r.region_name(code, "Nodes")]["proxies"][0], auto["name"])

    def test_region_membership_includes_all_families_without_notices(self):
        families = ["Extreme 01", "Prestige 三网直连 01", "Prestige 电信专用 01", "Ultimate 01", "Ultiamte 05", "Max 01", "Dynamic 01", "Extreme IPv6 Only 01", "Ultimate IPv6 01", "Extreme HY2 01"]
        for code in r.REGIONS:
            for family in families:
                for prefix in ("", "[vless]", "[Hy2]", r.REGIONS[code][0] + " [Hy2]"):
                    node = prefix + code + " " + family
                    matches = [c for c in r.REGIONS if re.search(r.region_filter(c), node)]
                    self.assertEqual(matches, [code], node)
                    self.assertRegex(node, r.region_filter())
        for notice in ("[Hy2]剩余流量：100 GB", "[vless]距离下次重置剩余：3 天", "套餐到期：2026-12-28", "JP 套餐说明", "USAGE Extreme 01", "US 剩余流量 100GB"):
            self.assertIsNone(re.search(r.region_filter(), notice))

    def test_bad_refresh_does_not_replace_previous_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "build"
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_text("previous good output")
            with self.assertRaises(ValueError):
                r.write_build(output, {"Crypto": "<html>Error</html>"})
            self.assertEqual(sentinel.read_text(), "previous good output")

    def test_known_service_first_matches(self):
        cache = Path(".routing-work/upstreams")
        if not cache.exists():
            self.skipTest("Run the builder or set up source cache first")
        rules, _ = r.build_lists(r.load_upstreams(cache, offline=True))
        r.validate(rules)


if __name__ == "__main__":
    unittest.main()
