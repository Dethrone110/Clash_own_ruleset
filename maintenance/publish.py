"""Publish validated outputs using fast-forward commits; never force branch refs."""

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


def api(method, path, body=None):
    token = os.environ["GH_TOKEN"]
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request("https://api.github.com/repos/" + os.environ["GITHUB_REPOSITORY"] + "/" + path,
                                     data=data, method=method, headers={
                                         "Authorization": "Bearer " + token,
                                         "Accept": "application/vnd.github+json",
                                         "Content-Type": "application/json",
                                         "X-GitHub-Api-Version": "2022-11-28",
                                     })
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def publish(branch, files):
    parent = api("GET", "git/ref/heads/" + branch)["object"]["sha"]
    commit = api("GET", "git/commits/" + parent)
    tree = api("GET", "git/trees/" + commit["tree"]["sha"] + "?recursive=1")
    old = {entry["path"]: entry["sha"] for entry in tree["tree"] if entry["type"] == "blob"}
    changes = []
    for path, content in files.items():
        data = content.encode()
        digest = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        if old.get(path) != digest:
            changes.append({"path": path, "type": "blob", "mode": "100644", "content": content})
    if not changes:
        print(branch + ": already current")
        return
    created = api("POST", "git/trees", {"base_tree": commit["tree"]["sha"], "tree": changes})
    new = api("POST", "git/commits", {"tree": created["sha"], "parents": [parent], "message": "Refresh validated routing rules and source manifest"})
    # Recheck the parent to avoid replacing a concurrent edit on the same branch.
    if api("GET", "git/ref/heads/" + branch)["object"]["sha"] != parent:
        raise RuntimeError(branch + " changed during generation; rerun against its new head")
    api("PATCH", "git/refs/heads/" + branch, {"sha": new["sha"], "force": False})
    print(f"{branch}: {new['sha']} ({len(changes)} files)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("build"))
    parser.add_argument("--templates", action="store_true")
    args = parser.parse_args()
    output = args.output
    rules = {p.name: p.read_text() for p in (output / "optrule").iterdir() if p.suffix == ".list" or p.name == "rules-manifest.json"}
    if args.templates:
        rules["ACL4SSR_Online_Mini_MultiMode.ini"] = (output / "optrule" / "ACL4SSR_Online_Mini_MultiMode.ini").read_text()
    publish("optrule", rules)
    if args.templates:
        publish("oldstore", {p.name: p.read_text() for p in (output / "oldstore").iterdir()})


if __name__ == "__main__":
    main()
