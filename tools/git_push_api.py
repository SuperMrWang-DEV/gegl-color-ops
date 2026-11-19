#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用 GitHub Git Data API 推送，绕过 github.com:443 不可达。

背景：本机到 github.com 的 HTTPS（直连、换 IP、走系统代理）全部超时，git push
永远卡在 "schannel: server closed abruptly"，但 api.github.com 一直可通，且
credential manager 里存着带 repo/workflow 权限的 token。

做法：本地 commit 照常做，然后把这个提交链的对象逐个传给 REST API
    POST /git/blobs     （按需，同样的 sha 直接复用远端的）
    POST /git/trees     （自下而上重建，内容未变的子树直接复用远端 sha）
    POST /git/commits   （parent 接上远端 head）
    PATCH /git/refs/heads/main
重建出来的 commit sha 通常与本地完全一致（tree、parent、author、committer 都对
得上），不一致也不影响内容。

用法:
    python tools/git_push_api.py --dry-run     # 只打印将要做什么
    python tools/git_push_api.py               # 真推
    python tools/git_push_api.py --branch main --remote origin

token 来源（按顺序）: 环境变量 GITHUB_TOKEN / GH_TOKEN，或 git credential fill。
"""
from __future__ import annotations

import argparse
import base64
import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"


def git(*args: str, binary: bool = False):
    out = subprocess.run(["git", *args], check=True, stdout=subprocess.PIPE)
    return out.stdout if binary else out.stdout.decode("utf-8").strip()


def token_from_credential() -> str:
    p = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        text=True, stdout=subprocess.PIPE, check=True,
    )
    m = re.search(r"^password=(.+)$", p.stdout, re.M)
    if not m:
        raise SystemExit("✗ git credential 里没有 host=github.com 的密码/token")
    return m.group(1).strip()


def repo_from_remote(remote: str) -> tuple[str, str]:
    url = git("remote", "get-url", remote)
    m = re.search(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?$", url)
    if not m:
        raise SystemExit(f"✗ 无法从 {url} 解析 owner/repo")
    return m.group(1), m.group(2)


class Api:
    def __init__(self, token: str, dry_run: bool):
        self.token = token
        self.dry_run = dry_run
        self.blob_cache: dict[str, str] = {}
        self.tree_cache: dict[str, str] = {}
        self.uploaded = 0
        self.quiet = False

    def call(self, method: str, path: str, payload=None):
        body = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(
            API + path, data=body, method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "gegl-color-ops-push",
            },
        )
        # 走本地代理时偶发 502/429，重试几次比整个流程重跑便宜
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=90) as r:
                    raw = r.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(1 + 2 * attempt)
                    continue
                detail = e.read().decode("utf-8", "replace")[:600]
                raise SystemExit(f"✗ {method} {path} -> {e.code}\n{detail}")
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < 3:
                    time.sleep(1 + 2 * attempt)
                    continue
                raise SystemExit(f"✗ {method} {path} -> {e}")


def ls_tree_local(sha: str):
    """git ls-tree -z -> [(path, mode, type, sha)]，路径按原始字节解码。"""
    raw = git("ls-tree", "-z", sha, binary=True)
    entries = []
    for rec in raw.split(b"\0"):
        if not rec:
            continue
        meta, path = rec.split(b"\t", 1)
        mode, typ, obj = meta.decode().split()
        entries.append((path.decode("utf-8", "surrogateescape"), mode, typ, obj))
    return entries


def prefetch_blobs(api: Api, local_tree: str, base_tree: str | None, jobs: int) -> None:
    """把本地 tree 里远端还没有的 blob 一次性并发传完。

    逐个串行上传时每个请求都要一次往返，18MB / 18KB 的文件量能跑二十分钟，
    先并发铺开再让 build_tree 命中缓存。
    """
    want = {obj for _, _, typ, obj in ls_tree_local_recursive(local_tree) if typ == "blob"}
    have: set[str] = set()
    if base_tree:
        try:
            data = api.call("GET", f"/repos/{api.owner}/{api.repo}/git/trees/{base_tree}?recursive=1")
            have = {e["sha"] for e in data.get("tree", []) if e.get("type") == "blob"}
            if data.get("truncated"):
                have.clear()
        except SystemExit:
            have = set()
    todo = [s for s in want if s not in have and s not in api.blob_cache]
    if not todo:
        return
    print(f"    预取 {len(todo)} 个 blob（{jobs} 路并发）")
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futs = {pool.submit(upload_blob, api, s): s for s in todo}
        for f in as_completed(futs):
            f.result()


def ls_tree_local_recursive(sha: str):
    raw = git("ls-tree", "-r", "-z", sha, binary=True)
    entries = []
    for rec in raw.split(b"\0"):
        if not rec:
            continue
        meta, path = rec.split(b"\t", 1)
        mode, typ, obj = meta.decode().split()
        entries.append((path.decode("utf-8", "surrogateescape"), mode, typ, obj))
    return entries


def remote_tree(api: Api, sha: str) -> dict[str, dict]:
    """读远端 tree 的直接子项。

    GitHub 有个怪癖：部分刚创建的 tree 用非递归 GET 会 404，同一个 sha 加
    ?recursive=1 却正常返回。所以 404 时退回递归读取，再筛掉带 `/` 的深层条目。
    """
    path = f"/repos/{api.owner}/{api.repo}/git/trees/{sha}"
    try:
        data = api.call("GET", path)
    except SystemExit as e:
        if "-> 404" not in str(e):
            raise
        data = api.call("GET", path + "?recursive=1")
        return {e["path"]: e for e in data.get("tree", []) if "/" not in e["path"]}
    if data.get("truncated"):
        raise SystemExit(f"✗ 远端 tree {sha} 被截断，脚本暂不支持这么大的目录")
    return {e["path"]: e for e in data.get("tree", [])}


def upload_blob(api: Api, sha: str) -> str:
    if sha in api.blob_cache:
        return api.blob_cache[sha]
    content = git("cat-file", "blob", sha, binary=True)
    if api.dry_run:
        api.uploaded += len(content)
        print(f"    blob {sha[:8]} {len(content):>9,} B (dry-run)")
        api.blob_cache[sha] = sha
        return sha
    data = api.call("POST", f"/repos/{api.owner}/{api.repo}/git/blobs",
                    {"content": base64.b64encode(content).decode(), "encoding": "base64"})
    api.blob_cache[sha] = data["sha"]
    api.uploaded += len(content)
    if not api.quiet:
        print(f"    blob {sha[:8]} {len(content):>9,} B -> {data['sha'][:8]}")
    return data["sha"]


def build_tree(api: Api, local_sha: str, base_sha: str | None, label: str) -> str:
    """把本地 tree 同步成远端 tree，返回远端可用的 sha。

    注意：即使某一层内容没变也要真的 POST 一次。GitHub 的 tree 是内容寻址的，
    重复提交同一份内容只会返回同一个 sha；而「直接用本地 sha 当结果」会造出
    一个引用不存在对象的悬空 tree（commit 建得出来，GET 却 404），所以这里不做
    「相同就跳过」的优化。
    """
    local = ls_tree_local(local_sha)
    base = remote_tree(api, base_sha) if base_sha else {}

    new_entries = []
    for path, mode, typ, obj in local:
        b = base.get(path)
        if typ == "tree":
            new = build_tree(api, obj, b["sha"] if b and b["type"] == "tree" else None,
                             f"{label}/{path}")
        else:
            same = b and b["type"] == "blob" and b["sha"] == obj and b["mode"] == mode
            new = obj if same else upload_blob(api, obj)
        new_entries.append({"path": path, "mode": mode, "type": typ, "sha": new})

    if api.dry_run:
        print(f"    tree {label or '<root>'}: {len(new_entries)} 项 -> (dry-run)")
        return "0" * 40
    data = api.call("POST", f"/repos/{api.owner}/{api.repo}/git/trees",
                    {"tree": new_entries})
    print(f"    tree {label or '<root>'}: {len(new_entries)} 项 -> {data['sha'][:8]}")
    return data["sha"]


def commit_meta(rev: str):
    raw = git("show", "-s", "--format=%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI%x00%B", rev)
    an, ae, ad, cn, ce, cd, msg = raw.split("\0", 6)
    return {
        # GitHub 会把 message 末尾的换行去掉再存，所以这里也去掉：虽然本地 commit
        # 的 sha 因此和远端不同，但内容逐字节一致，重建时用同一规则才能对上。
        "message": msg.rstrip("\n"),
        "author": {"name": an, "email": ae, "date": ad},
        "committer": {"name": cn, "email": ce, "date": cd},
    }


def render_commit(c: dict, offset_minutes: int) -> bytes:
    """按远端 commit 的 JSON 描述还原成 git commit 对象。"""
    def stamp(txt: str) -> tuple[int, str]:
        dt = datetime.datetime.strptime(txt, "%Y-%m-%dT%H:%M:%SZ")
        dt = dt.replace(tzinfo=datetime.timezone.utc)
        sign = "+" if offset_minutes >= 0 else "-"
        tz = f"{sign}{abs(offset_minutes)//60:02d}{abs(offset_minutes) % 60:02d}"
        return int(dt.timestamp()), tz

    a_ts, a_tz = stamp(c["author"]["date"])
    c_ts, c_tz = stamp(c["committer"]["date"])
    body = f"tree {c['tree']['sha']}\n"
    body += "".join(f"parent {p['sha']}\n" for p in c["parents"])
    body += f"author {c['author']['name']} <{c['author']['email']}> {a_ts} {a_tz}\n"
    body += f"committer {c['committer']['name']} <{c['committer']['email']}> {c_ts} {c_tz}\n\n"
    body += c["message"]
    return body.encode()


def adopt_remote(api: Api, new_head: str, branch: str, remote: str) -> None:
    """把远端新建的 commit 对象搬回本地，替代 fetch。

    github.com:443 不通时没法 fetch，本地这条链的 sha 又因为 message 尾换行
    （GitHub 会去掉）必然和远端不同。这里用 API 的 JSON 还原 commit 文本、
    hash-object -w 写进对象库，再把 refs 对上，本地就不会显示分叉。
    """
    chain, cur = [], new_head
    while True:
        try:
            git("cat-file", "-e", cur)
            break
        except subprocess.CalledProcessError:
            pass
        c = api.call("GET", f"/repos/{api.owner}/{api.repo}/git/commits/{cur}")
        chain.append(c)
        if not c["parents"]:
            break
        cur = c["parents"][0]["sha"]
        if len(chain) > 200:
            raise SystemExit("✗ 回溯 commit 链超过 200 个，放弃")

    for c in reversed(chain):
        for off in (480, 0, 330, -480, 60, -300, 540, -540):
            obj = render_commit(c, off)
            sha = subprocess.run(["git", "hash-object", "-t", "commit", "-w", "--stdin"],
                                 input=obj, stdout=subprocess.PIPE, check=True
                                 ).stdout.decode().strip()
            if sha == c["sha"]:
                break
        else:
            print(f"  ! {c['sha'][:8]} 无法还原（时区未知），只更新 remote ref")

    git("update-ref", f"refs/remotes/{remote}/{branch}", new_head)
    # 只有内容完全一致才动本地分支，避免把用户的工作树带偏
    if git("rev-parse", "HEAD^{tree}") == api.call(
            "GET", f"/repos/{api.owner}/{api.repo}/git/commits/{new_head}")["tree"]["sha"]:
        git("update-ref", f"refs/heads/{branch}", new_head)
        print(f"· 本地 {branch} 已对齐 {new_head[:8]}（内容相同，仅 sha 不同）")
    else:
        print(f"· 本地工作区与远端不一致，未移动本地分支；origin/{branch} 已指向 {new_head[:8]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", default="main")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--jobs", type=int, default=12, help="并发上传 blob 的线程数")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or token_from_credential()
    owner, repo = repo_from_remote(args.remote)

    api = Api(token, args.dry_run)
    api.owner, api.repo = owner, repo

    ref = api.call("GET", f"/repos/{owner}/{repo}/git/ref/heads/{args.branch}")
    remote_sha = ref["object"]["sha"]
    print(f"· 远端 {owner}/{repo} {args.branch} = {remote_sha[:8]}")

    try:
        git("merge-base", "--is-ancestor", remote_sha, "HEAD")
    except subprocess.CalledProcessError:
        raise SystemExit("✗ 远端有本地没有的提交，先 fetch/rebase；本脚本只做快进推送")

    revs = git("rev-list", "--reverse", f"{remote_sha}..HEAD").split()
    if not revs:
        print("· 没有需要推送的提交")
        return
    print(f"· 待推 {len(revs)} 个提交")

    parent = remote_sha
    # 每个 commit 的 base tree：第一个用远端 head 的 tree，之后用刚建出来的远端 tree
    # （重建后的 tree sha 与本地不一定相同，不能拿本地 sha 去 API 查）
    parent_tree = git("rev-parse", f"{remote_sha}^{{tree}}")
    for i, rev in enumerate(revs, 1):
        local_tree = git("rev-parse", f"{rev}^{{tree}}")
        print(f"  [{i}/{len(revs)}] {git('log', '-1', '--format=%h %s', rev)}")
        api.quiet = True
        prefetch_blobs(api, local_tree, parent_tree if not api.dry_run else None, args.jobs)
        api.quiet = False
        new_tree = build_tree(api, local_tree, parent_tree, "")
        parent_tree = local_tree if api.dry_run else new_tree
        meta = commit_meta(rev)
        if api.dry_run:
            print(f"    commit -> (dry-run) parent {parent[:8]}")
            parent = rev
            continue
        data = api.call("POST", f"/repos/{owner}/{repo}/git/commits",
                        {"message": meta["message"], "tree": new_tree,
                         "parents": [parent], "author": meta["author"],
                         "committer": meta["committer"]})
        parent = data["sha"]
        print(f"    commit -> {parent[:8]}")

    if api.dry_run:
        print(f"· dry-run 结束，将上传约 {api.uploaded/1048576:.1f} MB blob")
        return

    api.call("PATCH", f"/repos/{owner}/{repo}/git/refs/heads/{args.branch}",
             {"sha": parent, "force": False})
    print(f"✓ 已更新 {args.branch} -> {parent[:8]}（上传 {api.uploaded/1048576:.1f} MB）")

    adopt_remote(api, parent, args.branch, args.remote)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
