"""One-shot label audit: out-of-range class ids / coords / degenerate boxes."""
import glob
import os

for split in ("train", "val"):
    mx = -1
    bad = []
    n_files = n_lines = 0
    for f in glob.glob(rf"C:\RadiusData\radius\{split}\labels\*.txt"):
        n_files += 1
        for ln in open(f, encoding="utf-8", errors="replace"):
            p = ln.split()
            if len(p) < 5:
                continue
            n_lines += 1
            try:
                c = int(p[0])
                vals = [float(v) for v in p[1:5]]
            except ValueError:
                bad.append((os.path.basename(f), "unparseable", ln.strip()[:60]))
                continue
            mx = max(mx, c)
            if (c > 8 or c < 0 or any(v < -0.001 or v > 1.001 for v in vals)
                    or vals[2] <= 0 or vals[3] <= 0):
                bad.append((os.path.basename(f), c, vals))
    print(f"{split}: files={n_files} boxes={n_lines} max_class={mx} bad={len(bad)}")
    for b in bad[:6]:
        print("  BAD:", b)
