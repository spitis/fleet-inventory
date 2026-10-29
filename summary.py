#!/usr/bin/env python3
"""Build reports/index.html from the saved reports: one line per server that expands to its details, and a table of
GPUs across the fleet. Runs locally, reads only the reports folder, writes only index.html.   python3 summary.py reports"""
import collections, datetime, glob, html, os, re, sys

folder = sys.argv[1] if len(sys.argv) > 1 else "reports"
this_year = datetime.date.today().year
esc = html.escape


def sections(path):
    """Report text -> {section title: [lines]}; {} if the file is missing."""
    out, title = {}, None
    if not os.path.exists(path):
        return out
    for line in open(path, errors="replace").read().splitlines():
        if line.startswith("== "):
            title = line[3:].strip()
            out[title] = []
        elif title is not None and line.strip():
            out[title].append(line)
    return out


def grab(lines, pattern):
    """First group of the first line matching pattern, or ''."""
    for line in lines:
        m = re.search(pattern, line)
        if m:
            return m.group(1).strip()
    return ""


def natural(name):
    """Sort key that puts node3 before node11."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def size_gb(s):
    """'10.9T', '457G', '511M' (as lsblk and df print them) -> GB."""
    m = re.match(r"([\d.]+)([KMGTP]?)", s)
    return float(m.group(1)) * {"": 1e-9, "K": 1e-6, "M": 1e-3, "G": 1, "T": 1e3, "P": 1e6}[m.group(2)] if m else 0


def tb(gb):
    return f"{gb / 1000:.1f}" if gb >= 100 else f"{gb / 1000:.2f}"


def describe(user, root):
    """One server's two reports -> (facts, problems). Problems are (severity, text), severity 'red' or 'amber'."""
    get = lambda name: user.get(name, [])
    f, problems = {}, []
    red = lambda text: problems.append(("red", text))
    amber = lambda text: problems.append(("amber", text))

    f["when"] = (get("host") or root.get("identity", []) or ["", ""])[1]
    f["os"] = grab(get("host"), r'PRETTY_NAME="(.*)"') + (" / " + get("host")[-1] if get("host") else "")
    dmi = {}
    for line in get("system model and firmware date"):  # /sys/class/dmi/id/NAME:VALUE
        name, _, value = line.partition(":")
        dmi[name.split("/")[-1]] = value
    f["model"] = f"{dmi.get('sys_vendor', '')} {dmi.get('product_name', '')}".strip()
    f["serial"] = (root.get("identity", []) + [""] * 5)[4]

    years = [int(y) for y in re.findall(r"(\d{4})$", dmi.get("bios_date", ""))]
    os_year = grab(root.get("root filesystem created (ext4 only; usually the OS install date)", []), r"(\d{4})$")
    years += [int(os_year)] if os_year else []
    hours = [int(h) for l in root.get("disk health", []) for h in re.findall(r"Power.On.Hours.*?(\d+)$", l.replace(",", ""))]
    years += [this_year - max(hours) // 8766] if hours else []
    f["age"] = f"{this_year - min(years)}y ({min(years)})" if years else ""
    f["age_how"] = "oldest of: firmware date, OS install date, longest disk power-on time"

    cpu = get("cpu")
    sockets = int(grab(cpu, r"^Socket\(s\):\s+(\d+)") or 1)
    cores = int(grab(cpu, r"^Core\(s\) per socket:\s+(\d+)") or 0) * sockets
    threads = grab(cpu, r"^CPU\(s\):\s+(\d+)")
    mhz = grab(cpu, r"^CPU max MHz:\s+([\d.]+)")
    model = grab(cpu, r"^Model name:\s+(.*)")
    name = " ".join(re.sub(r"CPU|Processor|@.*|Intel |AMD |Xeon |\d+-Core", "", re.sub(r"\(R\)|\(TM\)", "", model)).split())
    ghz = f"{float(mhz) / 1000:.1f} GHz" if mhz else ""
    f["cpu_short"] = f"{cores}c/{threads}t {ghz} {name}" if cpu else ""
    f["cpu"] = f"{sockets}x {model}, {cores} cores, {threads} threads, max {ghz}" if cpu else ""

    mem = grab(get("memory"), r"^Mem:\s+(\d+)")
    slots = root.get("memory slots", [])
    sizes = [l for l in slots if re.match(r"\s+Size:", l)]
    ddr = grab(slots, r"Type: (DDR\d)")
    f["mem_short"] = f"{mem} GB {ddr}" if mem else ""
    filled = sum(bool(re.search(r"\d+ [GT]B", l)) for l in sizes)
    f["mem"] = f"{mem} GB" + (f", {filled} of {len(sizes)} slots used" if sizes else "")
    parts, size = collections.Counter(), ""
    for l in slots:  # count part numbers only for slots that hold a module
        size = l if re.match(r"\s+Size:", l) else size
        if "Part Number:" in l and re.search(r"\d+ [GT]B", size):
            parts[grab([l], r"Part Number:\s*(\S+)")] += 1
    f["mem"] += "".join(f", {n}x {p}" for p, n in parts.items() if p and p not in ("Unknown", "NO", "Not"))

    # GPUs: NVIDIA from nvidia-smi's table, AMD from lspci (vendor 1002)
    gpus = get("gpus")
    nv = [l.split(", ") for l in gpus if re.match(r"\d+, [0-9A-Fa-f]{8}:", l)]
    f["gpu_names"] = [r[2].replace("NVIDIA ", "").replace("GeForce ", "") for r in nv]
    f["gpu_names"] += [re.sub(r".*\[(.*?)\] \[1002:.*", r"\1", l) for l in gpus if re.search(r"\[03(00|02|80)\]: .*\[1002:", l)]
    f["gpu_short"] = ", ".join(f"{n}x {m}" for m, n in collections.Counter(f["gpu_names"]).items())
    caps = sorted({r[9].replace(".00", "") for r in nv})
    f["gpus"] = f["gpu_short"] + (f", power cap {'/'.join(caps)}" if caps else "")
    f["pcie"] = "Gen" + max(r[11] for r in nv) if nv and nv[0][11].isdigit() else ""
    # Peak estimate: GPU power caps + about 7 W per CPU core + 150 W for the rest of the server
    gpu_w = sum(float(r[9].split()[0]) for r in nv if re.match(r"[\d.]+ W", r[9]))
    f["peak"] = f"~{(gpu_w + 7 * cores + 150) / 1000:.1f} kW" if cpu else ""
    f["peak_how"] = f"{gpu_w:.0f} W GPU caps + {7 * cores} W for {cores} CPU cores + 150 W other" if cpu else ""
    if not nv and any("[10de:" in l for l in gpus):
        amber("NVIDIA GPUs present but nvidia-smi failed")

    holders = [l.split() for l in get("gpu holders (gpu, user, pid, memory)") if re.match(r"(\w+:\w+:\w+\.\d|amd) \S+ \d+", l)]
    busy = {h[0].lower() for h in holders if h[0] != "amd"}
    by_user = collections.Counter()
    for bus, who in {(h[0].lower(), h[1]) for h in holders}:
        by_user[who] += 1
    f["free"] = sum(1 for r in nv if r[1].lower() not in busy)
    f["free_short"] = f"{f['free']}/{len(nv)}" if nv else ""
    f["holders"] = ", ".join(f"{u} ({n} GPU{'s' if n > 1 else ''})" for u, n in by_user.most_common()) or ("none" if nv else "")

    # Disks: total and used per kind, attributing each mounted filesystem to the disk it sits on in lsblk's tree
    disk_lines = get("disks")
    df = {l.split()[-1]: size_gb(l.split()[2]) for l in disk_lines if re.match(r"/dev/\S+\s+\S+\s+\S+\s+\S+\s+\d+%\s+/", l)}
    kind, total, used, current = {}, collections.Counter(), collections.Counter(), None
    for l in disk_lines:
        cols = l.split()
        if re.match(r"\S+\s+\S+\s+disk\s+[01]\s", l) and cols[1] != "0B" and "usb" not in cols[4:5]:
            current = "HDD" if cols[3] == "1" else "SSD"
            total[current] += size_gb(cols[1])
        elif re.match(r"\S+\s+\S+\s+disk", l):
            current = None
        if current and cols[-1].startswith("/") and cols[-1] in df:
            used[current] += df.pop(cols[-1])
    for k in ("SSD", "HDD"):
        f[k] = f"{tb(used[k])} / {tb(total[k])} TB" if total[k] else ""
    for l in disk_lines:
        m = re.search(r"\s(\d+)% (/\S*)$", l)
        if m and int(m.group(1)) >= 90:
            (red if int(m.group(1)) >= 98 else amber)(f"{m.group(2)} is {m.group(1)}% full")

    # Power and BMC
    f["power"] = grab(root.get("bmc: whole-server power now", []), r"Instantaneous power reading:\s+([1-9]\d* W)")
    bmc = root.get("bmc: power supplies, fans, temperatures and event log (last 30)", [])
    sensors = [l for l in bmc if l.count("|") == 4]
    supplies = [l for l in sensors if "Presence detected" in l]
    f["supplies"] = f"{len(supplies)} present" if supplies else ""
    for l in sensors:
        if re.search(r"failure|AC lost|predictive|\|\s*(cr|nr|nc)\s*\|", l, re.I):
            red("BMC sensor " + " ".join(x.strip() for x in l.split("|")[0::4]))
    events = [l for l in bmc if re.match(r"\s*[0-9a-f]+ \| \d\d/\d\d/", l)]
    alarms = [l for l in events if re.search(r"Critical|Failure|AC lost|Predictive|Uncorrectable", l) and "Deasserted" not in l]
    if alarms:
        amber(f"{len(alarms)} alarms in the BMC event log, latest: " + " ".join(x.strip() for x in alarms[-1].split("|")[1:5]))

    # Health and history
    for line in root.get("disk health", []):
        if re.search(r"overall-health|SMART Health Status", line) and not re.search(r"PASSED|OK\s*$", line):
            red("disk health: " + line.strip())
    errors = root.get("kernel errors, last 180 days (latest 100)", [])
    for word, sev in [("Xid", red), ("mce:", red), ("Hardware Error", red), ("AER", amber), ("I/O error", amber), ("NVRM", amber)]:
        n = sum(word in l for l in errors)
        if n:
            sev(f"{n} kernel '{word.rstrip(':')}' errors among the latest 100 kernel errors")
    restarts = get("restarts and shutdowns, newest first (a reboot with no shutdown below it = unclean restart)") + root.get(
        "restarts and shutdowns, older months, newest first (a reboot with no shutdown below it = unclean restart)", [])
    kinds = [l.split()[0] for l in restarts if re.match(r"(reboot|shutdown)\s", l)]
    unclean = sum(a == b == "reboot" for a, b in zip(kinds, kinds[1:]))
    if unclean:
        amber(f"{unclean} restarts with no recorded shutdown (crashes, power loss or hard resets)")
    for l in get("failed services"):
        if re.match(r"[●*] ", l):
            amber("failed service " + l.split()[1])
    return f, problems


def not_collected():
    """'host: reason' lines that collect.sh wrote for its last user and root runs."""
    out = []
    for kind in ("user", "root"):
        path = f"{folder}/not-collected-{kind}.log"
        if os.path.exists(path):
            out += [re.sub(r"^FAILED\s+(\S+): ", rf"\1 ({kind} report): ", l) for l in open(path).read().splitlines() if l.strip()]
    return out


def usage_samples(days):
    """Snapshots from the usage logs of the last `days` days: {host, time, gpus: {gpu: util %}, holders: {gpu: user}}."""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    out, cur = [], None
    for path in sorted(glob.glob(f"{folder}/usage-*.log"))[-2:]:
        for line in open(path, errors="replace"):
            head = re.match(r"== (\S+) (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)$", line)
            if head:
                cur = {"host": head[1], "time": datetime.datetime.fromisoformat(head[2]), "gpus": {}, "holders": {}}
            elif cur and line.startswith("== END"):
                if cur["time"] >= cutoff:
                    out.append(cur)
                cur = None
            elif cur:
                nv = re.match(r"\d+, ([0-9A-Fa-f:.]+), (\d+) %", line)                        # NVIDIA GPU line
                amd = re.match(r"(/sys/class/drm/card\d+)/device/gpu_busy_percent:(\d+)", line)  # AMD GPU line
                held = re.match(r"(\w+:\w+:\w+\.\d) (\S+) \d+", line)                          # NVIDIA holder line
                if nv:
                    cur["gpus"][nv[1].lower()] = int(nv[2])
                elif amd:
                    cur["gpus"][amd[1]] = int(amd[2])
                elif held:
                    cur["holders"][held[1].lower()] = held[2]
    return out


def usage_section(days=7):
    """HTML for GPU use over the last `days` days, or '' if there are no usage logs."""
    samples = usage_samples(days)
    collect = os.path.join(os.path.dirname(os.path.abspath(__file__)), "collect.sh")
    where = os.path.dirname(os.path.abspath(folder))
    how = ("<p>To record usage every 10 minutes, run <code>crontab -e</code> on this machine and add:</p>"
           f"<pre>*/10 * * * * cd {esc(where)} &amp;&amp; {esc(collect)} hosts.txt usage &gt; /dev/null</pre>"
           "<p class=\"mute\">Each snapshot takes about a second on each server. This section fills in as snapshots arrive.</p>")
    if not samples:
        return f"<p>No usage snapshots in the last {days} days.</p>" + how
    age = datetime.datetime.now() - max(x["time"] for x in samples)
    stale = (f'<p><span class="tag amber">The newest snapshot is {age.total_seconds() / 3600:.0f} hours old. '
             "Is the cron job still running?</span></p>" + how) if age > datetime.timedelta(hours=1) else ""
    now = datetime.datetime.now().replace(minute=0, second=0, microsecond=0)
    hours = [now - datetime.timedelta(hours=h) for h in range(days * 24 - 1, -1, -1)]
    by_host = collections.defaultdict(list)
    for x in samples:
        by_host[x["host"]].append(x)
    fleet_users, rows = collections.Counter(), []
    for host in sorted(by_host, key=natural):
        xs = sorted(by_host[host], key=lambda x: x["time"])
        n = max(len(x["gpus"]) for x in xs)
        if not n:
            continue
        gaps = sorted((b["time"] - a["time"]).total_seconds() / 3600 for a, b in zip(xs, xs[1:])) or [1 / 6]
        step = min(gaps[len(gaps) // 2], 1)                    # hours each snapshot stands for (usually 10 minutes)
        users = collections.Counter()
        for x in xs:
            for user in x["holders"].values():
                users[user] += step
        fleet_users.update(users)
        held = sum(len(x["holders"]) for x in xs) / len(xs)
        busy = sum(sum(u >= 10 for u in x["gpus"].values()) for x in xs) / len(xs)
        per_hour = collections.defaultdict(list)
        for x in xs:
            per_hour[x["time"].replace(minute=0, second=0)].append(len(x["holders"]) / n)
        cells = ""
        for h in hours:
            if per_hour.get(h):
                frac = sum(per_hour[h]) / len(per_hour[h])
                cells += f'<i style="opacity:{0.12 + 0.88 * frac:.2f}" title="{h:%a %b %d %H:00}: {frac * n:.1f} of {n} GPUs in use"></i>'
            else:
                cells += f'<i class="none" title="{h:%a %b %d %H:00}: no snapshot"></i>'
        top = ", ".join(f"{u} {g:.{0 if g >= 10 else 1}f}" for u, g in users.most_common(4))
        rows.append(f"<tr><td><b>{esc(host)}</b></td><td>{n}</td><td>{held:.1f} ({held / n:.0%})</td><td>{busy:.1f} ({busy / n:.0%})</td>"
                    f'<td>{esc(top) or "&ndash;"}</td><td><div class="strip">{cells}</div></td></tr>')
    first, last = min(x["time"] for x in samples), max(x["time"] for x in samples)
    totals = ", ".join(f"{u} {g:.{0 if g >= 10 else 1}f}" for u, g in fleet_users.most_common(10))
    return (stale + f'<p class="mute">{len(samples)} snapshots from {first:%b %d %H:%M} to {last:%b %d %H:%M}. In use = a process holds the GPU; '
            "busy = GPU utilisation at least 10%. Each strip cell is one hour; darker = more GPUs in use; dashed = no snapshot. "
            "Hover over a cell for its numbers.</p>"
            + (f"<p><b>GPU-hours by user:</b> {esc(totals)}</p>" if totals else "")
            + '<div class="wrap"><table><tr><th>Machine</th><th>GPUs</th><th>In use (avg)</th><th>Busy (avg)</th>'
            f"<th>Top users, GPU-hours</th><th>Last {days} days, hour by hour</th></tr>" + "".join(rows) + "</table></div>")


CSS = """
:root{--bg:#fff;--fg:#1d1d1f;--mute:#6e6e73;--line:#e3e3e6;--link:#0b57d0;--red:#b3261e;--redbg:#fde7e4;--amber:#7a5200;--amberbg:#fdf0d5}
@media (prefers-color-scheme:dark){:root{--bg:#161618;--fg:#e8e8ea;--mute:#9a9aa1;--line:#2f2f34;--link:#8ab4f8;
 --red:#ff9b91;--redbg:#3b1815;--amber:#ffd27a;--amberbg:#3a2d0e}}
body{margin:0 auto;max-width:1600px;padding:16px;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}
h1{font-size:20px;margin:4px 0 2px} p{margin:4px 0 10px} a{color:var(--link)} .mute{color:var(--mute)}
.wrap{overflow-x:auto} table{border-collapse:collapse}
th,td{padding:5px 16px 5px 0;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:12px;font-weight:600;color:var(--mute);white-space:nowrap}
.tag{display:inline-block;padding:1px 6px;border-radius:4px;margin:1px 4px 1px 0;font-size:12.5px}
.red{background:var(--redbg);color:var(--red)} .amber{background:var(--amberbg);color:var(--amber)}
summary{cursor:pointer} details.sec>summary{font-size:16px;font-weight:600;margin:22px 0 6px}
.grid{min-width:880px} .grid .r{display:grid;gap:0 10px;padding:6px 0;
 grid-template-columns:minmax(80px,1.1fr) minmax(60px,.8fr) minmax(110px,2fr) minmax(65px,1fr) minmax(100px,1.8fr) 42px minmax(70px,1fr) minmax(70px,1fr) 60px 60px 48px minmax(60px,1fr)}
.grid .h{font-size:12px;font-weight:600;color:var(--mute);border-bottom:1px solid var(--line)}
.grid details{border-bottom:1px solid var(--line)} .grid summary{list-style:none}
.grid summary::-webkit-details-marker{display:none} .grid summary b:before{content:"▸ ";color:var(--mute)}
.grid details[open] summary b:before{content:"▾ "} .grid .more{padding:0 0 12px 1.2em}
pre{font:12.5px/1.4 ui-monospace,Menlo,Consolas,monospace;overflow-x:auto;padding:8px;border:1px solid var(--line)}
ul.att{list-style:none;padding:0;margin:6px 0 12px} ul.att li{margin:2px 0}
.strip{display:flex;gap:1px;min-width:504px} .strip i{flex:1;height:16px;background:var(--link)} .strip i.none{background:none;border:1px dashed var(--line)}
"""

hosts = sorted({re.sub(r"-(user|root)\.txt$", "", os.path.basename(p)) for p in glob.glob(f"{folder}/*-user.txt") + glob.glob(f"{folder}/*-root.txt")},
               key=natural)
heads = ["Machine", "Age", "CPU", "Memory", "GPUs", "PCIe", "SSD used / total", "HDD used / total", "Power now", "Peak (est.)", "Free GPUs", "Attention"]
rows, fleet = [], collections.defaultdict(lambda: [0, 0, set()])
for host in hosts:
    f, problems = describe(sections(f"{folder}/{host}-user.txt"), sections(f"{folder}/{host}-root.txt"))
    for name in f["gpu_names"]:
        fleet[name][0] += 1
        fleet[name][2].add(host.split(".")[0])
    if f["gpu_names"] and len(set(f["gpu_names"])) == 1:
        fleet[f["gpu_names"][0]][1] += f["free"]
    count = collections.Counter(sev for sev, _ in problems)
    badges = " ".join(f'<span class="tag {s}">{count[s]}</span>' for s in ("red", "amber") if count[s]) or '<span class="mute">&ndash;</span>'
    line = [f["age"], f["cpu_short"], f["mem_short"], f["gpu_short"], f["pcie"], f["SSD"], f["HDD"], f["power"], f["peak"], f["free_short"]]
    reports = " · ".join(f'<a href="{esc(n)}">{k} report</a>' for k, n in (("user", f"{host}-user.txt"), ("root", f"{host}-root.txt"))
                         if os.path.exists(f"{folder}/{n}"))
    detail = [("Model", f["model"]), ("Serial", f["serial"]), ("OS", f["os"]), ("Age", f["age"] and f"{f['age']}, {f['age_how']}"),
              ("CPU", f["cpu"]), ("Memory", f["mem"]), ("GPUs", f["gpus"]), ("GPU holders", f["holders"]),
              ("Power", ", ".join(x for x in (f["power"] and f["power"] + " now", f["supplies"] and "power supplies: " + f["supplies"]) if x)),
              ("Peak (est.)", f["peak"] and f"{f['peak']}: {f['peak_how']}"),
              ("Collected", f["when"]), ("Reports", None)]
    rows.append('<details><summary class="r">' + f"<b>{esc(host.split('.')[0])}</b>"
                + "".join(f"<span>{esc(v) or '&ndash;'}</span>" for v in line) + f"<span>{badges}</span></summary><div class=\"more\">"
                + ('<ul class="att">' + "".join(f'<li><span class="tag {s}">{esc(t)}</span></li>' for s, t in problems) + "</ul>" if problems else "")
                + "<table>" + "".join(f"<tr><th>{k}</th><td>{reports if v is None else esc(v)}</td></tr>" for k, v in detail if v or v is None)
                + "</table></div></details>")

missing = not_collected()
sec = lambda title, inner: f'<details class="sec" open><summary>{title}</summary>{inner}</details>'
body = (f"<h1>Server inventory</h1><p class=\"mute\">{len(hosts)} servers, page built {datetime.datetime.now():%Y-%m-%d %H:%M}. "
        'Click a machine for details and its full reports. <span class="tag red">red</span> = failing now, '
        '<span class="tag amber">amber</span> = worth a look.</p>')
if missing:
    body += '<p><b>Not collected in the last run:</b></p><ul class="att">' + "".join(f"<li>{esc(m)}</li>" for m in missing) + "</ul>"
body += sec(f"Machines ({len(hosts)})", '<div class="wrap"><div class="grid"><div class="r h">' + "".join(f"<span>{h}</span>" for h in heads)
            + "</div>" + "".join(rows) + "</div></div>")
if fleet:
    body += sec("GPUs in the fleet", '<p class="mute">Free = no process on the GPU when its report was collected.</p><div class="wrap"><table>'
                "<tr><th>Model</th><th>GPUs</th><th>Free</th><th>Machines</th></tr>"
                + "".join(f"<tr><td>{esc(m)}</td><td>{n}</td><td>{free}</td><td>{esc(', '.join(sorted(where, key=natural)))}</td></tr>"
                          for m, (n, free, where) in sorted(fleet.items(), key=lambda x: -x[1][0]))
                + "</table></div>")

body += sec("Usage over time", usage_section())

page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Server inventory</title><style>{CSS}</style></head><body>{body}</body></html>\n")
open(f"{folder}/index.html", "w").write(page)
print(f"wrote {folder}/index.html ({len(hosts)} servers)")
