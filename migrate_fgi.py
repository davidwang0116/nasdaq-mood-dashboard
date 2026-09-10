"""One-time migration: fix Sunday→Friday timezone shift in cached FGI history."""
import json
import os
from pathlib import Path

p = Path(__file__).parent / "cache" / "fgi_history.json"
if not p.exists():
    print("No fgi_history.json to migrate.")
    raise SystemExit(0)

d = json.loads(p.read_text(encoding="utf-8"))
dates = d.get("dates", [])
values = d.get("values", [])

fixed_seen = {}
for ds, v in zip(dates, values):
    import datetime
    t = datetime.date.fromisoformat(ds)
    # weekday(): Mon=0 … Sun=6
    if t.weekday() == 6:          # Sunday → belongs to previous Friday
        t = t - datetime.timedelta(days=2)
    elif t.weekday() == 5:        # Saturday → belongs to previous Friday
        t = t - datetime.timedelta(days=1)
    fixed_seen[t.isoformat()] = v  # keep last if duplicate

d["dates"] = sorted(fixed_seen)
d["values"] = [fixed_seen[k] for k in d["dates"]]
p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
print(f"修复完成，剩余 {len(d['dates'])} 天")

# Verify no weekends remain
bad = [x for x in d["dates"] if datetime.date.fromisoformat(x).weekday() >= 5]
print(f"周末日期数量: {len(bad)}")
assert len(bad) == 0, f"仍有周末日期: {bad}"
print("验收通过")
