#!/usr/bin/env python3
"""Cold archive: move idle local folders to S3 as verified tar.zst objects, and restore them.

    cold_archive.py archive PLAN.json            # PLAN = JSON list of absolute folder paths
    cold_archive.py restore SOURCE_PATH [--dest DIR]
    cold_archive.py status                       # catalog summary

Per folder (archive):
  1. manifest: every file's relpath, size, mode, mtime_ns, sha256 (symlinks + hard links recorded)
  2. tar (pax, no AppleDouble) | zstd -12 --long=27  ->  local temp file; sha256 of the archive
  3. verify: decompress + read every tar member, compare with the manifest
  4. upload archive (GLACIER_IR) + manifest (STANDARD); re-download the archive and compare sha256
  4. re-check the source is unchanged and not in use, then delete it locally
  5. append a catalog row: local maintenance catalog + s3://BUCKET/catalog/catalog.jsonl
Nothing is deleted unless steps 3-5 pass. AWS profile/region come from AWS_PROFILE/AWS_REGION
(default epoch / us-west-2).
"""
import argparse, datetime, gzip, hashlib, io, json, os, shutil, socket, stat, subprocess, sys, tarfile, threading, time, queue

BUCKET = os.environ.get("COLD_ARCHIVE_BUCKET", "epoch-cold-archive-836951909127-us-west-2")
HOME = os.path.expanduser("~")
HOST = "macbook-" + os.environ.get("USER", "user")
CATALOG = os.environ.get("COLD_ARCHIVE_CATALOG", os.path.join(HOME, "zerg-embedded/corsair/runs/maintenance/cold-archive/catalog.jsonl"))
TMP = os.path.join(HOME, ".cache/cold-archive/tmp")
ZSTD = ["zstd", "-q", "-T0", "-12", "--long=27"]
MIN_FREE = int(float(os.environ.get("COLD_ARCHIVE_MIN_FREE_GIB", "20")) * 2**30)
IDLE_SECONDS = float(os.environ.get("COLD_ARCHIVE_IDLE_DAYS", "7")) * 86400
ENV = dict(os.environ, AWS_PROFILE=os.environ.get("AWS_PROFILE", "epoch"),
           AWS_REGION=os.environ.get("AWS_REGION", "us-west-2"))


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(8 << 20), b""):
            h.update(b)
    return h.hexdigest()


def under_home(p):
    return p == HOME or p.startswith(HOME + "/")


def display(p):
    return "~/" + os.path.relpath(p, HOME) if under_home(p) else p


def s3_key(src):
    # paths outside ~ (e.g. /private/tmp) live under _abs/ so keys never contain ".."
    rel = os.path.relpath(src, HOME) if under_home(src) else "_abs" + src
    return f"{HOST}/{rel}"


def aws(*args, capture=True, input_bytes=None):
    r = subprocess.run(["aws", *args], env=ENV, capture_output=capture, input=input_bytes)
    if r.returncode != 0:
        raise RuntimeError(f"aws {' '.join(args[:3])} failed: {r.stderr.decode()[:500] if r.stderr else ''}")
    return r.stdout


def build_manifest(src):
    parent, name = os.path.split(src.rstrip("/"))
    files, dirs, links, specials = [], [], [], []
    seen_ino = {}
    newest = 0.0
    logical = 0
    for dp, dn, fn in os.walk(src):
        st = os.lstat(dp)
        dirs.append({"p": os.path.relpath(dp, parent), "mode": stat.S_IMODE(st.st_mode), "mtime_ns": st.st_mtime_ns})
        for f in sorted(fn) + [d for d in dn if os.path.islink(os.path.join(dp, d))]:
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, parent)
            st = os.lstat(p)
            newest = max(newest, st.st_mtime)
            if stat.S_ISLNK(st.st_mode):
                links.append({"p": rel, "target": os.readlink(p)})
            elif stat.S_ISREG(st.st_mode):
                if st.st_nlink > 1 and st.st_ino in seen_ino:
                    sha = seen_ino[st.st_ino][1]
                else:
                    sha = sha256_file(p)
                    if st.st_nlink > 1:
                        seen_ino[st.st_ino] = (rel, sha)
                files.append({"p": rel, "size": st.st_size, "mode": stat.S_IMODE(st.st_mode),
                              "mtime_ns": st.st_mtime_ns, "sha256": sha})
                logical += st.st_size
            else:
                specials.append({"p": rel, "type": stat.filemode(st.st_mode)[0]})
    return {"schema": "cold-archive-manifest/v1", "source": src, "host": socket.gethostname(),
            "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "files": files, "dirs": dirs, "symlinks": links, "skipped_special": specials,
            "file_count": len(files), "logical_bytes": logical, "newest_mtime": newest}


def make_archive(src, out):
    parent, name = os.path.split(src.rstrip("/"))
    excl = []
    with open(out, "wb") as fo:
        tar = subprocess.Popen(["tar", "--no-mac-metadata", "--format", "pax", "-cf", "-", "-C", parent, name],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        z = subprocess.Popen(ZSTD + ["-c"], stdin=tar.stdout, stdout=fo)
        tar.stdout.close()
        _, terr = tar.communicate()
        z.wait()
    terr = terr.decode(errors="replace")
    real_errors = [l for l in terr.splitlines() if l.strip() and "socket" not in l.lower()]
    if tar.returncode not in (0,) and real_errors or z.returncode != 0:
        raise RuntimeError(f"tar/zstd failed rc={tar.returncode}/{z.returncode}: {terr[:500]}")
    return sha256_file(out)


def verify_stream(stream, manifest):
    want = {f["p"]: f for f in manifest["files"]}
    sym = {l["p"]: l["target"] for l in manifest["symlinks"]}
    seen = set()
    with tarfile.open(fileobj=stream, mode="r|") as t:
        for m in t:
            if m.isreg():
                h = hashlib.sha256()
                f = t.extractfile(m)
                for b in iter(lambda: f.read(8 << 20), b""):
                    h.update(b)
                w = want.get(m.name)
                if not w or w["sha256"] != h.hexdigest() or w["size"] != m.size:
                    raise RuntimeError(f"archive member mismatch: {m.name}")
                seen.add(m.name)
            elif m.islnk():
                w = want.get(m.name)
                tgt = want.get(m.linkname)
                if not w or not tgt or w["sha256"] != tgt["sha256"]:
                    raise RuntimeError(f"hard link mismatch: {m.name} -> {m.linkname}")
                seen.add(m.name)
            elif m.issym():
                if sym.get(m.name) != m.linkname:
                    raise RuntimeError(f"symlink mismatch: {m.name}")
    missing = set(want) - seen
    if missing:
        raise RuntimeError(f"{len(missing)} files missing from archive, e.g. {sorted(missing)[:3]}")
    return len(seen)


def verify_archive(path, manifest):
    z = subprocess.Popen(["zstd", "-dc", "--long=27", path], stdout=subprocess.PIPE)
    n = verify_stream(z.stdout, manifest)
    z.wait()
    if z.returncode != 0:
        raise RuntimeError("zstd decode failed")
    return n


def stream_upload(src, akey, expected):
    """tar | zstd | aws s3 cp - : no local temp copy. Returns (sha256, bytes) of the uploaded object."""
    parent, name = os.path.split(src.rstrip("/"))
    os.makedirs(TMP, exist_ok=True)
    terr_path = os.path.join(TMP, "tar.stderr")
    uerr_path = os.path.join(TMP, "upload.stderr")
    with open(terr_path, "wb") as terr, open(uerr_path, "wb") as uerr:
        tar = subprocess.Popen(["tar", "--no-mac-metadata", "--format", "pax", "-cf", "-", "-C", parent, name],
                               stdout=subprocess.PIPE, stderr=terr)
        z = subprocess.Popen(ZSTD + ["-c"], stdin=tar.stdout, stdout=subprocess.PIPE)
        tar.stdout.close()
        up = subprocess.Popen(["aws", "s3", "cp", "-", f"s3://{BUCKET}/{akey}", "--storage-class", "GLACIER_IR",
                               "--expected-size", str(max(expected, 1 << 20)), "--only-show-errors"],
                              env=ENV, stdin=subprocess.PIPE, stderr=uerr)
        h = hashlib.sha256()
        n = 0
        for b in iter(lambda: z.stdout.read(8 << 20), b""):
            h.update(b)
            n += len(b)
            up.stdin.write(b)
        up.stdin.close()
        tar.wait(); z.wait(); up.wait()
    terr_txt = open(terr_path, errors="replace").read()
    real_errors = [l for l in terr_txt.splitlines() if l.strip() and "socket" not in l.lower()]
    if (tar.returncode != 0 and real_errors) or z.returncode != 0 or up.returncode != 0:
        raise RuntimeError(f"stream upload failed tar={tar.returncode} zstd={z.returncode} aws={up.returncode}: "
                           f"{terr_txt[:300]} {open(uerr_path, errors='replace').read()[:300]}")
    return h.hexdigest(), n


def verify_remote(akey, manifest):
    """Re-download the object, hash it, decompress and check every member against the manifest."""
    dl = subprocess.Popen(["aws", "s3", "cp", f"s3://{BUCKET}/{akey}", "-"], env=ENV, stdout=subprocess.PIPE)
    z = subprocess.Popen(["zstd", "-dc", "--long=27"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    h = hashlib.sha256()
    err = []

    def pump():
        try:
            for b in iter(lambda: dl.stdout.read(8 << 20), b""):
                h.update(b)
                z.stdin.write(b)
        except Exception as e:
            err.append(e)
        finally:
            z.stdin.close()

    th = threading.Thread(target=pump)
    th.start()
    n = verify_stream(z.stdout, manifest)
    th.join(); dl.wait(); z.wait()
    if err or dl.returncode != 0 or z.returncode != 0:
        raise RuntimeError(f"remote verify failed: {err} dl={dl.returncode} zstd={z.returncode}")
    return h.hexdigest(), n


def in_use(src):
    ps = subprocess.run(["ps", "-axo", "pid,command"], capture_output=True, text=True).stdout
    me = str(os.getpid())
    named = [l for l in ps.splitlines() if src in l and "cold_archive.py" not in l and not l.strip().startswith(me)]
    lsof = subprocess.run(["/usr/sbin/lsof", "-nP", "-u", str(os.getuid()), "-Fn"], capture_output=True, text=True).stdout
    opened = [l for l in lsof.splitlines() if l.startswith("n" + src + "/")]
    return named[:3] + opened[:3]


def unchanged(src, manifest):
    n = 0
    total = 0
    newest = 0.0
    for dp, dn, fn in os.walk(src):
        for f in fn:
            st = os.lstat(os.path.join(dp, f))
            if stat.S_ISREG(st.st_mode):
                n += 1
                total += st.st_size
            newest = max(newest, st.st_mtime)
    return n == manifest["file_count"] and total == manifest["logical_bytes"] and newest <= manifest["newest_mtime"]


def rmtree_force(path):
    def onerror(func, p, exc):
        os.chmod(os.path.dirname(p), 0o700)
        if os.path.isdir(p) and not os.path.islink(p):
            os.chmod(p, 0o700)
        func(p)
    for dp, dn, fn in os.walk(path):
        for d in dn:
            q = os.path.join(dp, d)
            if not os.path.islink(q):
                os.chmod(q, 0o700)
    os.chmod(path, 0o700)
    shutil.rmtree(path, onerror=onerror)


def append_catalog(row):
    os.makedirs(os.path.dirname(CATALOG), exist_ok=True)
    with open(CATALOG, "a") as f:
        f.write(json.dumps(row) + "\n")
    aws("s3", "cp", CATALOG, f"s3://{BUCKET}/catalog/{os.path.basename(CATALOG)}", "--only-show-errors")


def prepare(src):
    t0 = time.time()
    if not os.path.isdir(src):
        raise RuntimeError("source missing")
    m = build_manifest(src)
    if time.time() - m["newest_mtime"] < IDLE_SECONDS:
        raise RuntimeError("source written within the idle window")
    m["manifest_seconds"] = round(time.time() - t0)
    return m


def ship(src, m):
    key = s3_key(src)
    akey, mkey = key + ".tar.zst", key + ".manifest.json.gz"
    t0 = time.time()
    sha, n = stream_upload(src, akey, m["logical_bytes"])
    m["archive_sha256"], m["archive_bytes"] = sha, n
    m["upload_seconds"] = round(time.time() - t0)
    aws("s3api", "put-object-tagging", "--bucket", BUCKET, "--key", akey, "--tagging",
        json.dumps({"TagSet": [{"Key": "sha256", "Value": sha}, {"Key": "files", "Value": str(m["file_count"])}]}))
    head = json.loads(aws("s3api", "head-object", "--bucket", BUCKET, "--key", akey))
    if head["ContentLength"] != n:
        raise RuntimeError("uploaded object size mismatch")
    rsha, members = verify_remote(akey, m)
    if rsha != sha:
        raise RuntimeError("re-downloaded archive sha256 mismatch")
    m["verified_members"] = members
    os.makedirs(TMP, exist_ok=True)
    mtmp = os.path.join(TMP, "manifest.json.gz")
    open(mtmp, "wb").write(gzip.compress(json.dumps(m).encode()))
    aws("s3", "cp", mtmp, f"s3://{BUCKET}/{mkey}", "--only-show-errors")
    os.remove(mtmp)
    busy = in_use(src)
    if busy:
        raise RuntimeError(f"source in use, kept local: {busy}")
    if not unchanged(src, m):
        raise RuntimeError("source changed after manifest, kept local")
    rmtree_force(src)
    row = {"source": src, "bucket": BUCKET, "archive_key": akey, "manifest_key": mkey,
           "archive_sha256": sha, "archive_bytes": n,
           "logical_bytes": m["logical_bytes"], "files": m["file_count"], "storage_class": "GLACIER_IR",
           "archived_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
           "newest_mtime": datetime.datetime.fromtimestamp(m["newest_mtime"]).isoformat(timespec="seconds"),
           "skipped_special": len(m["skipped_special"])}
    append_catalog(row)
    return row


def cmd_archive(plan_path):
    plan = json.load(open(plan_path))
    done = set()
    if os.path.exists(CATALOG):
        done = {json.loads(l)["source"] for l in open(CATALOG) if l.strip()}
    todo = [p for p in plan if p not in done and os.path.isdir(p)]
    log(f"{len(todo)} folders to archive ({len(plan) - len(todo)} done or missing)")
    q = queue.Queue(maxsize=1)
    failures = []

    def producer():
        for src in todo:
            while shutil.disk_usage(HOME).free < MIN_FREE:
                log("free space below floor; waiting")
                time.sleep(60)
            try:
                m = prepare(src)
                q.put((src, m))
            except Exception as e:
                failures.append({"source": src, "stage": "prepare", "error": str(e)[:300]})
                log("PREPARE FAILED", src, e)
        q.put(None)

    threading.Thread(target=producer, daemon=True).start()
    freed = 0
    while True:
        item = q.get()
        if item is None:
            break
        src, m = item
        try:
            row = ship(src, m)
            freed += m["logical_bytes"]
            log(f"ARCHIVED {display(src)}  {m['logical_bytes']/2**30:.1f} GiB -> "
                f"{m['archive_bytes']/2**30:.2f} GiB  free {shutil.disk_usage(HOME).free/2**30:.0f} GiB")
        except Exception as e:
            failures.append({"source": src, "stage": "ship", "error": str(e)[:300]})
            log("SHIP FAILED (kept local)", src, e)
    json.dump(failures, open(os.path.join(os.path.dirname(CATALOG), "failures-latest.json"), "w"), indent=1)
    log(f"DONE archived logical {freed/2**30:.1f} GiB, failures {len(failures)}")


def cmd_restore(src, dest):
    rows = [json.loads(l) for l in open(CATALOG)] if os.path.exists(CATALOG) else []
    row = next((r for r in reversed(rows) if r["source"] == src), None)
    if not row:
        key = s3_key(src)
        row = {"archive_key": key + ".tar.zst", "manifest_key": key + ".manifest.json.gz"}
    dest = dest or os.path.dirname(src)
    m = json.loads(gzip.decompress(aws("s3", "cp", f"s3://{BUCKET}/{row['manifest_key']}", "-")))
    os.makedirs(TMP, exist_ok=True)
    arc = os.path.join(TMP, "restore-" + hashlib.sha1(src.encode()).hexdigest()[:16] + ".tar.zst")
    aws("s3", "cp", f"s3://{BUCKET}/{row['archive_key']}", arc, "--only-show-errors")
    if sha256_file(arc) != m["archive_sha256"]:
        raise RuntimeError("downloaded archive sha256 mismatch")
    verify_archive(arc, m)
    z = subprocess.Popen(["zstd", "-dc", "--long=27", arc], stdout=subprocess.PIPE)
    subprocess.run(["tar", "-xpf", "-", "-C", dest], stdin=z.stdout, check=True)
    z.wait()
    os.remove(arc)
    parent = os.path.dirname(m["source"])
    bad = [f["p"] for f in m["files"] if sha256_file(os.path.join(dest, f["p"])) != f["sha256"]]
    for f in m["files"]:
        os.utime(os.path.join(dest, f["p"]), ns=(f["mtime_ns"], f["mtime_ns"]))
    log(f"restored {len(m['files'])} files to {os.path.join(dest, os.path.basename(m['source']))}, mismatches {len(bad)}")


VAULT_CATALOG = os.path.join(HOME, "Library/Mobile Documents/iCloud~md~obsidian/Documents/idanbeck/"
                             "Epoch/Engineering/Storage/Cold Archive Catalog.md")


def cmd_catalog_md(out):
    rows = [json.loads(l) for l in open(CATALOG)] if os.path.exists(CATALOG) else []
    lb = sum(r["logical_bytes"] for r in rows)
    ab = sum(r["archive_bytes"] for r in rows)
    by_root = {}
    for r in rows:
        rel = display(r["source"]).split("/")
        k = "/".join(rel[:5]) if rel[:4] == ["~", "zerg-embedded", "corsair", "runs"] else "/".join(rel[:3])
        a = by_root.setdefault(k, [0, 0, 0])
        a[0] += 1; a[1] += r["logical_bytes"]; a[2] += r["archive_bytes"]
    lines = ["# Cold Archive Catalog", "",
             f"**Generated:** {datetime.datetime.now().astimezone().isoformat(timespec='minutes')} by "
             "`~/.claude/skills/aws-skill/cold_archive.py catalog-md` (do not hand-edit; regenerate)",
             f"**Bucket:** `{BUCKET}` (us-west-2, GLACIER_IR)",
             f"**Machine-readable catalog:** `s3://{BUCKET}/catalog/catalog.jsonl` and `{os.path.relpath(CATALOG, HOME)}`",
             f"**Totals:** {len(rows)} folders, {lb/2**30:,.1f} GiB original, {ab/2**30:,.1f} GiB stored",
             "", "Restore any folder byte-identically:", "",
             "```bash", "python3 ~/.claude/skills/aws-skill/cold_archive.py restore /absolute/original/path", "```",
             "", "## By area", "", "| Area | Folders | Original GiB | Stored GiB |", "|---|---:|---:|---:|"]
    for k, v in sorted(by_root.items(), key=lambda kv: -kv[1][1]):
        lines.append(f"| `{k}` | {v[0]} | {v[1]/2**30:,.1f} | {v[2]/2**30:,.2f} |")
    lines += ["", "## Folders", "", "| Original path | Files | Original GiB | Stored GiB | Last write | Archived |",
              "|---|---:|---:|---:|---|---|"]
    for r in sorted(rows, key=lambda r: r["source"]):
        lines.append(f"| `{display(r['source'])}` | {r['files']:,} | {r['logical_bytes']/2**30:,.2f} | "
                     f"{r['archive_bytes']/2**30:,.2f} | {r['newest_mtime'][:10]} | {r['archived_at'][:10]} |")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w").write("\n".join(lines) + "\n")
    print(f"wrote {out} ({len(rows)} rows)")


def cmd_status():
    rows = [json.loads(l) for l in open(CATALOG)] if os.path.exists(CATALOG) else []
    lb = sum(r["logical_bytes"] for r in rows)
    ab = sum(r["archive_bytes"] for r in rows)
    print(json.dumps({"bucket": BUCKET, "archived_folders": len(rows), "logical_GiB": round(lb / 2**30, 1),
                      "stored_GiB": round(ab / 2**30, 1), "catalog": CATALOG}, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("archive"); a.add_argument("plan")
    r = sp.add_parser("restore"); r.add_argument("source"); r.add_argument("--dest")
    sp.add_parser("status")
    c = sp.add_parser("catalog-md"); c.add_argument("--out", default=VAULT_CATALOG)
    args = ap.parse_args()
    if args.cmd == "archive":
        cmd_archive(args.plan)
        cmd_catalog_md(VAULT_CATALOG)
    elif args.cmd == "restore":
        cmd_restore(args.source, args.dest)
    elif args.cmd == "catalog-md":
        cmd_catalog_md(args.out)
    else:
        cmd_status()
