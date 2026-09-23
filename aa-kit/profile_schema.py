"""Generates ACTUAL-AA-SCHEMA.md from a decrypted UAT payload.
Derived from the real response - never from the documentation."""
import json, sys
from collections import Counter, defaultdict
from pathlib import Path

def walk(node, prefix="", out=None, depth=0):
    out = out if out is not None else defaultdict(Counter)
    if depth > 12: return out
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{prefix}.{k}" if prefix else k
            out[p][type(v).__name__] += 1
            walk(v, p, out, depth+1)
    elif isinstance(node, list):
        out[prefix + "[]"]["len_" + str(len(node))] += 1
        for item in node[:50]:
            walk(item, prefix + "[]", out, depth+1)
    return out

def sample_values(node, path, acc=None, prefix="", depth=0):
    acc = acc if acc is not None else defaultdict(list)
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{prefix}.{k}" if prefix else k
            if not isinstance(v, (dict, list)) and len(acc[p]) < 3:
                acc[p].append(v)
            sample_values(v, path, acc, p, depth+1)
    elif isinstance(node, list):
        for item in node[:50]:
            sample_values(item, path, acc, prefix + "[]", depth+1)
    return acc

def main(path):
    data = json.loads(Path(path).read_text())
    fields = walk(data)
    samples = sample_values(data, path)
    lines = ["# ACTUAL AA SCHEMA", "",
             f"Derived from `{Path(path).name}` — the real UAT response, not documentation.", ""]
    # session-level summary
    if isinstance(data, list):
        lines += [f"**Sessions returned: {len(data)}**", ""]
        for i, s in enumerate(data):
            if isinstance(s, dict):
                lines.append(f"- session {i}: fipId=`{s.get('fipId')}` "
                             f"masked=`{s.get('maskedAccNumber')}` "
                             f"keys={sorted(s.keys())}")
        lines.append("")
    lines += ["| Field path | Types seen | Sample values |", "|---|---|---|"]
    for p in sorted(fields):
        t = ", ".join(f"{k}×{v}" for k, v in fields[p].most_common(4))
        sv = samples.get(p, [])
        sv = ", ".join(f"`{str(x)[:40]}`" for x in sv[:3]) or "—"
        lines.append(f"| `{p}` | {t} | {sv} |")
    Path("ACTUAL-AA-SCHEMA.md").write_text("\n".join(lines))
    print(f"wrote ACTUAL-AA-SCHEMA.md — {len(fields)} distinct field paths")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "captures/decrypted.json")
