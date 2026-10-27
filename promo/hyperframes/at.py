import json, sys
t = json.load(open("timings.json")); order = [c["id"] for c in json.load(open("script.json"))["chapters"]]
start, acc = {}, 0.0
for c in order:
    start[c] = acc; acc += t[c]["duration"]
pts = []
for arg in sys.argv[1:]:
    cid, loc = arg.split("@"); pts.append(f"{start[cid] + float(loc):.3f}")
print(",".join(pts))
