import re, json, sys
from pathlib import Path
path = Path("monitoring_report.html")
if not path.exists():
    print("monitoring_report.html がありません"); sys.exit(1)
html = path.read_text(encoding="utf-8")
m = re.search(r'(const ALL_DATA\s*=\s*)({.*?})(;)', html)
if not m:
    print("ALL_DATA が見つかりません"); sys.exit(1)
data = json.loads(m.group(2))
fixes = [
    ("東京都", "adecco",           "2026-09-02", 5826, 1775),
    ("東京都", "adecco",           "2026-08-23", 5811, 1838),
    ("北海道", "recruit_staffing", "2026-08-29",  126, 1402),
    ("宮城県", "recruit_staffing", "2026-08-15",   87, 1325),
    ("大阪府", "recruit_staffing", "2026-07-12",  662, 1625),
    ("広島県", "recruit_staffing", "2026-07-12",   62, 1370),
    ("広島県", "recruit_staffing", "2026-07-13",   61, 1370),
    ("福岡県", "recruit_staffing", "2026-07-12",  250, 1425),
    ("宮城県", "tempstaff",        "2026-05-13",  169, 1325),
]
n = 0
for region, co, date, cnt, wage in fixes:
    for rec in data.get(region, []):
        if rec["date"] == date:
            old = rec.get(co) or {}
            if old.get("count") != cnt:
                rec[co] = {"count": cnt, "wage": wage}
                print(f"  修正 {region} {co} {date}: {old.get('count')} -> {cnt}")
                n += 1
            else:
                print(f"  済み {region} {co} {date}: {cnt}")
if n:
    path.write_text(html[:m.start(2)] + json.dumps(data, ensure_ascii=False) + html[m.end(2):], encoding="utf-8")
    print(f"\n{n}件 修正しました")
else:
    print("\n修正対象なし")
