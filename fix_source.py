import json, re, sys, collections, statistics
from pathlib import Path

DRY = "--dry-run" in sys.argv
data_dir = Path(__file__).parent / "data"
if not data_dir.is_dir():
    print("data/ が見つかりません"); sys.exit(1)

series = collections.defaultdict(lambda: collections.defaultdict(list))
for f in sorted(data_dir.glob("*.json")):
    m = re.match(r"(\d{4}-\d{2}-\d{2})_(.+)\.json$", f.name)
    if not m:
        continue
    try:
        obj = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        print(f"  [skip] JSON 読込失敗: {f.name}"); continue
    for r in obj.get("results", []):
        if r.get("company_id"):
            series[m.group(2)][r["company_id"]].append((m.group(1), f, r))

edits = collections.defaultdict(list)
for region, cos in series.items():
    for co, rows in cos.items():
        rows.sort(key=lambda x: x[0])
        counts = [r.get("count") for _, _, r in rows if r.get("count") is not None]
        if len(counts) < 5:
            continue
        floor = statistics.median(counts) * 0.4
        for i in range(len(rows)):
            dt, path, cur = rows[i]
            cc = cur.get("count")
            if cc is None or cc >= floor:
                continue
            prev = next((r for _, _, r in reversed(rows[:i])
                         if r.get("count") is not None and r["count"] >= floor), None)
            nxt  = next((r for _, _, r in rows[i+1:]
                         if r.get("count") is not None and r["count"] >= floor), None)
            if not prev or not nxt:
                continue
            pc, nc = prev["count"], nxt["count"]
            if not (cc < pc * 0.5 and cc < nc * 0.5):
                continue
            pw, nw = prev.get("avg_wage"), nxt.get("avg_wage")
            new_w = round((pw + nw) / 2) if pw and nw else (pw or nw or cur.get("avg_wage"))
            edits[path].append((co, cc, round((pc + nc) / 2), cur.get("avg_wage"), new_w, region, dt))

if not edits:
    print("異常値は見つかりませんでした。"); sys.exit(0)

total = 0
for path in sorted(edits):
    obj = json.loads(path.read_text(encoding="utf-8"))
    for co, old_c, new_c, old_w, new_w, region, dt in edits[path]:
        for r in obj["results"]:
            if r.get("company_id") == co:
                r["count"], r["avg_wage"] = new_c, new_w
                r["note"] = "スクレイピング異常値のため前後日から補間"
        print(f"  {region} {dt} {co}: count {old_c}->{new_c}, wage {old_w}->{new_w}")
        total += 1
    if not DRY:
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"\n{total} 件 " + ("検出（--dry-run のため未変更）" if DRY else "修正しました"))
