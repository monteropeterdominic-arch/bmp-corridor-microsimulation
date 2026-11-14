#!/usr/bin/env python3
"""
Bai Matabay Plang Avenue (USM frontage) - SUMO microsimulation kit.

Builds a calibrated SUMO model of the entry-to-gate corridor from the field
counts in field_data.json, runs the baseline and improvement scenarios for the
morning, midday and evening peaks over several random seeds, validates the
baseline against observed 15-min gate counts (GEH), and exports
results/summary.csv, results/validation.csv and results/results.json
(the latter can be dropped into the web dashboard).

Usage (from this folder):
    python run_bmp.py                 # build + run everything
    python run_bmp.py --dry-run       # only generate SUMO input files
    python run_bmp.py --gui S0_baseline morning   # open one case in sumo-gui
    python run_bmp.py --replay        # export vehicle trajectories for the 3D web simulation

Requirements: Python 3.8+, Eclipse SUMO >= 1.15 (https://eclipse.dev/sumo/).
Set SUMO_HOME or put sumo/netconvert on PATH. matplotlib is optional (figures).
"""
import argparse, csv, json, math, os, random, shutil, statistics, subprocess, sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "build")
RESULTS = os.path.join(HERE, "results")

CLASSES = ["car", "motorcycle", "tricycle", "jeepney", "truck"]

VTYPES = {
    # id: attributes (SUMO vType). Tricycle = motorcycle with sidecar, typical of Mindanao towns.
    "car": dict(vClass="passenger", length="4.5", width="1.8", minGap="2.0", accel="2.0", decel="4.5",
                maxSpeed="16.7", speedFactor="normc(0.9,0.1,0.6,1.2)", latAlignment="center",
                color="0.30,0.55,0.85"),
    "motorcycle": dict(vClass="motorcycle", length="2.0", width="0.8", minGap="0.6", accel="2.5", decel="5.0",
                       maxSpeed="16.7", speedFactor="normc(1.0,0.1,0.7,1.3)", latAlignment="arbitrary",
                       lcSublane="2.0", minGapLat="0.3", color="0.95,0.60,0.10"),
    "tricycle": dict(vClass="motorcycle", length="3.0", width="1.5", minGap="1.0", accel="1.2", decel="3.5",
                     maxSpeed="11.1", speedFactor="normc(0.85,0.1,0.6,1.1)", latAlignment="arbitrary",
                     minGapLat="0.4", guiShape="motorcycle", color="0.20,0.70,0.40"),
    "jeepney": dict(vClass="bus", length="7.0", width="2.0", minGap="2.0", accel="1.0", decel="4.0",
                    maxSpeed="13.9", speedFactor="normc(0.85,0.1,0.6,1.1)", latAlignment="center",
                    color="0.80,0.20,0.60"),
    "truck": dict(vClass="truck", length="8.0", width="2.3", minGap="2.5", accel="0.8", decel="4.0",
                  maxSpeed="13.9", latAlignment="center", color="0.45,0.45,0.45"),
}


# --------------------------------------------------------------------------- utils
def load_json(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return json.load(f)


def sumo_bin(name):
    exe = name + (".exe" if os.name == "nt" else "")
    if os.environ.get("SUMO_HOME"):
        p = os.path.join(os.environ["SUMO_HOME"], "bin", exe)
        if os.path.exists(p):
            return p
    p = shutil.which(name)
    if p:
        return p
    sys.exit(f"Cannot find '{name}'. Install SUMO and set SUMO_HOME (or add SUMO's bin folder to PATH).")


def write_xml(root, path):
    ET.indent(root) if hasattr(ET, "indent") else None
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)


def ensure(d):
    os.makedirs(d, exist_ok=True)
    return d


# --------------------------------------------------------------------------- network
def build_network(cfg, dry):
    g = cfg["geometry"]
    Le, Lm = float(g["entry_segment_length_m"]), float(g["mid_segment_length_m"])
    spd = g["speed_limit_kph"] / 3.6
    lanes, w = int(g["lanes"]), float(g["lane_width_m"])
    sx = Le + float(g.get("side_street_offset_m", 0))
    nd = ET.Element("nodes")
    sy = 40 if cfg["friction"].get("side", "left") == "left" else -40   # +y = left of the direction of travel
    for nid, x, y, typ in [("A", 0, 0, "priority"), ("M", sx, 0, "priority"), ("S", sx, sy, "priority"),
                           ("G", Le + Lm, 0, "traffic_light"), ("X", Le + Lm + 60, 0, "priority")]:
        ET.SubElement(nd, "node", id=nid, x=str(x), y=str(y), type=typ)
    ed = ET.Element("edges")
    common = dict(speed=f"{spd:.2f}", width=str(w))
    ET.SubElement(ed, "edge", id="E_entry", **{"from": "A", "to": "M"}, numLanes=str(lanes), priority="3", **common)
    ET.SubElement(ed, "edge", id="E_side", **{"from": "S", "to": "M"}, numLanes="1", priority="1", **common)
    ET.SubElement(ed, "edge", id="E_mid", **{"from": "M", "to": "G"}, numLanes=str(lanes), priority="3", **common)
    ET.SubElement(ed, "edge", id="E_exit", **{"from": "G", "to": "X"}, numLanes=str(lanes), priority="3", **common)
    d = ensure(BUILD)
    write_xml(nd, os.path.join(d, "bmp.nod.xml"))
    write_xml(ed, os.path.join(d, "bmp.edg.xml"))
    net = os.path.join(d, "bmp.net.xml")
    if not dry:
        subprocess.run([sumo_bin("netconvert"), "-n", "bmp.nod.xml", "-e", "bmp.edg.xml", "-o", "bmp.net.xml",
                        "--no-turnarounds", "true", "--tls.default-type", "static"], cwd=d, check=True)
    return net


def tls_link_count(net, default):
    if not os.path.exists(net):
        return default
    n = 0
    for c in ET.parse(net).getroot().iter("connection"):
        if c.get("tl") == "G":
            n = max(n, int(c.get("linkIndex")) + 1)
    return n or default


# --------------------------------------------------------------------------- pedestrian signal program
def ped_blocks(period, cfg, scen, rng):
    """Return sorted list of (start, end) seconds during which pedestrians block the gate."""
    p, sim = cfg["pedestrians"], cfg["simulation"]
    warm = sim["warmup_s"]
    peds = [period["peds_gate"][0]] + period["peds_gate"]          # warm-up repeats interval 1
    blocks = []
    for k, n in enumerate(peds):
        t0 = 0 if k == 0 else warm + (k - 1) * 900
        if scen["controlled_crossing"]:
            if n <= 0:
                continue
            cyc = p["controlled_cycle_s"]
            t = t0 + cyc - p["controlled_ped_phase_s"]
            while t < t0 + 900:
                blocks.append((t, t + p["controlled_ped_phase_s"]))
                t += cyc
        else:
            groups = math.ceil(n / p["group_size"])
            for _ in range(groups):                                  # random (Poisson-like) crossings
                s = t0 + rng.uniform(0, 900 - p["crossing_block_s"])
                blocks.append((s, s + p["crossing_block_s"]))
    blocks.sort()
    merged = []
    for s, e in blocks:                                              # merge overlaps
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def tls_program(blocks, nlinks, horizon):
    phases, t = [], 0
    for s, e in blocks:
        s, e = int(round(s)), int(round(e))
        if s - t >= 1:
            phases.append((s - t, "G" * nlinks))
            t = s
        if e - t >= 1:
            phases.append((e - t, "r" * nlinks))
            t = e
    phases.append((max(1, horizon - t), "G" * nlinks))
    return phases


# --------------------------------------------------------------------------- demand + friction
def build_case(cfg, field, scen_id, period_id, seed, nlinks):
    scen, period = cfg["scenarios"][scen_id], field["periods"][period_id]
    g, fr, sim = cfg["geometry"], cfg["friction"], cfg["simulation"]
    rng = random.Random(seed * 1000 + sum(map(ord, period_id + scen_id)))
    Lm = float(g["mid_segment_length_m"])
    zs, ze = fr["friction_zone_start_frac"] * Lm, fr["friction_zone_end_frac"] * Lm
    warm = sim["warmup_s"]
    horizon = warm + 3600 + sim["clearance_s"]
    # curb lane where stops, parking and the loading bay are: leftmost lane by default (side streets are on the west)
    curb = int(g["lanes"]) - 1 if fr.get("side", "left") == "left" else 0
    CURB = f"E_mid_{curb}"

    entry = [period["entry_by_class"][0]] + period["entry_by_class"]
    gate = [period["gate_total"][0]] + period["gate_total"]
    tstop = [period["tricycle_stops"][0]] + period["tricycle_stops"]
    pstop = [period["puv_stops"][0]] + period["puv_stops"]
    parked = [period["parked_events"][0]] + period["parked_events"]
    dwell = [period["tricycle_dwell_s"][0]] + period["tricycle_dwell_s"]

    vehicles = []   # (depart, xml-element)
    vid = 0

    def veh(depart, vtype, route, **kw):
        nonlocal vid
        vid += 1
        e = ET.Element("vehicle", id=f"{vtype[:3]}{vid}", type=vtype, route=route, depart=f"{depart:.1f}",
                       departLane="best", departSpeed="max", **kw)
        vehicles.append((depart, e))
        return e

    for k in range(5):
        t0 = 0 if k == 0 else warm + (k - 1) * 900
        # main-entry vehicles
        main = []
        for ci, c in enumerate(CLASSES):
            for _ in range(int(entry[k][ci])):
                main.append(veh(t0 + rng.uniform(0, 900), c, "r_main"))
        # Extra inflow observed at the gate but not at the entry (side streets / roadside origins).
        # Parking and side-street-intrusion events are taken out of this extra inflow, so total
        # demand is identical in every scenario; only their roadside behaviour changes.
        extra = max(0, int(gate[k]) - sum(entry[k]))
        tot = max(1, sum(entry[k]))
        shares = [entry[k][ci] / tot for ci in range(len(CLASSES))]
        for _ in range(max(0, extra - int(parked[k]))):
            c = rng.choices(CLASSES, weights=shares)[0]
            veh(t0 + rng.uniform(0, 900), c, "r_side")
        for _ in range(int(parked[k])):
            pos = rng.uniform(zs, ze)
            e = veh(t0 + rng.uniform(0, 900), "car", "r_mid")
            e.set("departLane", str(curb)); e.set("departSpeed", "0")
            if scen["no_parking"]:
                e.set("departPos", f"{pos:.1f}")          # same trip, but no roadside dwell
            else:
                e.set("departPos", f"{pos + 8:.1f}")
                ET.SubElement(e, "stop", lane=CURB, startPos=f"{pos:.1f}", endPos=f"{pos + 8:.1f}",
                              duration=str(fr["parked_event_duration_s"]))
        # tricycle loading/unloading stops
        trikes = [e for e in main if e.get("type") == "tricycle"]
        for e in rng.sample(trikes, min(len(trikes), int(tstop[k]))):
            d = max(3.0, rng.gauss(dwell[k], fr["dwell_cv"] * dwell[k]))
            if scen["tricycle_bay"]:
                ET.SubElement(e, "stop", parkingArea="trike_bay", duration=f"{d:.0f}")
            else:
                pos = rng.uniform(zs, ze)
                ET.SubElement(e, "stop", lane=CURB, startPos=f"{pos:.1f}", endPos=f"{pos + 4:.1f}",
                              duration=f"{d:.0f}")
        # jeepney / car (PUV) stops
        puvs = [e for e in main if e.get("type") in ("jeepney", "car") and len(e) == 0]
        for e in rng.sample(puvs, min(len(puvs), int(pstop[k]))):
            pos = rng.uniform(zs, ze)
            ET.SubElement(e, "stop", lane=CURB, startPos=f"{pos:.1f}", endPos=f"{pos + 8:.1f}",
                          duration=str(fr["puv_stop_dwell_s"]))

    # ---- write routes
    root = ET.Element("routes")
    for vt, attrs in VTYPES.items():
        ET.SubElement(root, "vType", id=vt, **attrs)
    ET.SubElement(root, "route", id="r_main", edges="E_entry E_mid E_exit")
    ET.SubElement(root, "route", id="r_side", edges="E_side E_mid E_exit")
    ET.SubElement(root, "route", id="r_mid", edges="E_mid E_exit")
    for _, e in sorted(vehicles, key=lambda x: x[0]):
        root.append(e)
    case = ensure(os.path.join(BUILD, scen_id, period_id, f"seed{seed}"))
    write_xml(root, os.path.join(case, "routes.rou.xml"))

    # ---- additional: tls program, parking bay, detectors, edge data
    add = ET.Element("additional")
    tl = ET.SubElement(add, "tlLogic", id="G", type="static", programID="peds", offset="0")
    for dur, st in tls_program(ped_blocks(period, cfg, scen, rng), nlinks, horizon):
        ET.SubElement(tl, "phase", duration=str(dur), state=st)
    bay = cfg["tricycle_bay"]
    bs = bay["position_frac"] * Lm
    ET.SubElement(add, "parkingArea", id="trike_bay", lane=CURB, startPos=f"{bs:.1f}",
                  endPos=f"{bs + bay['length_m']:.1f}", roadsideCapacity=str(bay["capacity"]), friendlyPos="true")
    for i in range(int(g["lanes"])):
        ET.SubElement(add, "inductionLoop", id=f"det_entry_{i}", lane=f"E_entry_{i}", pos="5",
                      period="900", file="det_entry.xml")
        ET.SubElement(add, "inductionLoop", id=f"det_gate_{i}", lane=f"E_exit_{i}", pos="5",
                      period="900", file="det_gate.xml")
    ET.SubElement(add, "edgeData", id="ed900", period="900", begin=str(warm), end=str(warm + 3600),
                  file="edgedata.xml", excludeEmpty="false")
    write_xml(add, os.path.join(case, "add.xml"))
    return case, horizon


def sumo_cmd(cfg, case, horizon, seed, gui=False):
    sim = cfg["simulation"]
    net = os.path.relpath(os.path.join(BUILD, "bmp.net.xml"), case)
    return [sumo_bin("sumo-gui" if gui else "sumo"), "-n", net, "-r", "routes.rou.xml", "-a", "add.xml",
            "--begin", "0", "--end", str(horizon), "--step-length", str(sim["step_length_s"]),
            "--lateral-resolution", str(sim["lateral_resolution_m"]), "--seed", str(seed),
            "--tripinfo-output", "tripinfo.xml", "--device.emissions.probability", "1",
            "--summary-output", "summary.xml", "--time-to-teleport", "300",
            "--no-step-log", "true", "--duration-log.disable", "true", "--ignore-route-errors", "true"]


# --------------------------------------------------------------------------- output parsing
def parse_case(cfg, case):
    warm = cfg["simulation"]["warmup_s"]
    tt, loss, wait, co2, n_main = [], [], [], 0.0, 0
    for ti in ET.parse(os.path.join(case, "tripinfo.xml")).getroot().iter("tripinfo"):
        dep = float(ti.get("depart"))
        if not (warm <= dep < warm + 3600):
            continue
        em = ti.find("emissions")
        if em is not None:
            co2 += float(em.get("CO2_abs", 0)) / 1e6        # mg -> kg
        if ti.get("id").startswith(tuple(c[:3] for c in CLASSES)) and ti.get("departLane", "").startswith("E_entry"):
            n_main += 1
            tt.append(float(ti.get("duration")))
            loss.append(float(ti.get("timeLoss")))
            wait.append(float(ti.get("waitingTime")))
    gate = [0, 0, 0, 0]
    for it in ET.parse(os.path.join(case, "det_gate.xml")).getroot().iter("interval"):
        b = float(it.get("begin"))
        k = int((b - warm) // 900)
        if 0 <= k < 4:
            gate[k] += int(float(it.get("nVehContrib")))
    speed = None
    for it in ET.parse(os.path.join(case, "edgedata.xml")).getroot().iter("interval"):
        sp = [float(e.get("speed")) for e in it.iter("edge") if e.get("id") == "E_mid" and e.get("speed")]
        if sp:
            speed = (speed or []) + sp
    halting = 0
    for st in ET.parse(os.path.join(case, "summary.xml")).getroot().iter("step"):
        if float(st.get("time")) >= warm:
            halting = max(halting, int(st.get("halting", 0)))
    mean = lambda x: statistics.mean(x) if x else float("nan")
    return dict(travel_time_s=mean(tt), time_loss_s=mean(loss), waiting_s=mean(wait),
                mid_speed_kph=mean(speed or []) * 3.6, max_halting=halting, co2_kg=co2,
                gate_counts=gate, gate_total=sum(gate), n_trips=n_main)


def geh(m, c):
    m, c = m * 4, c * 4            # 15-min counts -> hourly flow rates
    return math.sqrt(2 * (m - c) ** 2 / (m + c)) if (m + c) else 0.0



# --------------------------------------------------------------------------- 3D replay export
def net_offset(net):
    loc = ET.parse(net).getroot().find("location")
    ox, oy = (float(v) for v in loc.get("netOffset", "0,0").split(","))
    return ox, oy


REPLAY_INTERVALS = {"morning": 2, "midday": 3, "evening": 1}   # busiest 15 min of each peak (highest gate arrivals)


def export_replays(cfg, field, nlinks):
    for period, interval in REPLAY_INTERVALS.items():
        export_replay(cfg, field, nlinks, period=period, interval=interval)


def export_replay(cfg, field, nlinks, scen_ids=("S0_baseline", "S4_combined"), period="morning", interval=2):
    """Run one seed of each scenario with floating-car-data output and write the vehicle
    trajectories of one 15-min interval to replay/."""
    sim, g = cfg["simulation"], cfg["geometry"]
    seed, warm = sim["seeds"][0], sim["warmup_s"]
    t0 = warm + interval * 900
    t1 = t0 + 900
    ox, oy = net_offset(os.path.join(BUILD, "bmp.net.xml"))
    out_dir = ensure(os.path.join(HERE, "replay"))
    for sid in scen_ids:
        case, _ = build_case(cfg, field, sid, period, seed, nlinks)
        cmd = sumo_cmd(cfg, case, t1, seed) + ["--fcd-output", "fcd.xml"]
        print(f"replay {sid} {period}", flush=True)
        subprocess.run(cmd, cwd=case, check=True, stdout=subprocess.DEVNULL)
        tracks, order = {}, []
        for _, ts in ET.iterparse(os.path.join(case, "fcd.xml")):
            if ts.tag != "timestep":
                continue
            t = float(ts.get("time"))
            if t0 <= t < t1 and abs(t - round(t)) < 1e-6:
                k = int(round(t - t0))
                for v in ts.iter("vehicle"):
                    vid = v.get("id")
                    tr = tracks.get(vid)
                    if tr is None or tr["start"] + len(tr["x"]) != k:      # new vehicle (or after a gap)
                        if tr is not None:
                            vid = vid + "_" + str(k)
                        tr = tracks[vid] = {"type": CLASSES.index(v.get("type")) if v.get("type") in CLASSES else 0,
                                            "start": k, "x": [], "y": [], "v": []}
                        order.append(vid)
                    tr["x"].append(round(float(v.get("x")) - ox, 1))
                    tr["y"].append(round(float(v.get("y")) - oy, 2))
                    tr["v"].append(round(float(v.get("speed")) * 3.6, 1))
            ts.clear()
        # pedestrian signal (red intervals) inside the window
        red, t = [], 0.0
        for ph in ET.parse(os.path.join(case, "add.xml")).getroot().iter("phase"):
            dur = float(ph.get("duration"))
            if ph.get("state", "G")[0] == "r" and t + dur > t0 and t < t1:
                red.append([round(max(t, t0) - t0, 1), round(min(t + dur, t1) - t0, 1)])
            t += dur
        data = {
            "scenario": sid, "label": cfg["scenarios"][sid]["label"], "period": period,
            "window": field["periods"][period]["intervals"][interval], "duration": 900, "seed": seed,
            "geom": {"Le": g["entry_segment_length_m"], "Lm": g["mid_segment_length_m"], "exit": 60,
                     "lanes": g["lanes"], "laneW": g["lane_width_m"]},
            "types": CLASSES, "vtype_dims": {c: [float(VTYPES[c]["length"]), float(VTYPES[c]["width"])] for c in CLASSES},
            "ped_red": red,
            "veh": [[tracks[i]["type"], tracks[i]["start"], tracks[i]["x"], tracks[i]["y"], tracks[i]["v"]] for i in order],
        }
        path = os.path.join(out_dir, f"replay_{sid}_{period}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        print(f"  wrote {path} ({len(order)} vehicles)")

# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--gui", nargs=2, metavar=("SCENARIO", "PERIOD"))
    ap.add_argument("--replay", action="store_true", help="export trajectories for the 3D web simulation")
    a = ap.parse_args()
    cfg, field = load_json("config.json"), load_json("field_data.json")

    net = build_network(cfg, a.dry_run)
    nlinks = tls_link_count(net, int(cfg["geometry"]["lanes"]))

    if a.replay:
        if a.dry_run:
            sys.exit("--replay needs SUMO; run it without --dry-run")
        export_replays(cfg, field, nlinks)
        return

    if a.gui:
        case, hz = build_case(cfg, field, a.gui[0], a.gui[1], cfg["simulation"]["seeds"][0], nlinks)
        subprocess.run(sumo_cmd(cfg, case, hz, cfg["simulation"]["seeds"][0], gui=True), cwd=case)
        return

    rows, per_seed = [], {}
    for sid in cfg["scenarios"]:
        for pid in field["periods"]:
            for seed in cfg["simulation"]["seeds"]:
                case, hz = build_case(cfg, field, sid, pid, seed, nlinks)
                if a.dry_run:
                    continue
                print(f"running {sid:18s} {pid:8s} seed {seed}", flush=True)
                subprocess.run(sumo_cmd(cfg, case, hz, seed), cwd=case, check=True,
                               stdout=subprocess.DEVNULL)
                per_seed.setdefault((sid, pid), []).append(parse_case(cfg, case))
    if a.dry_run:
        print("Dry run complete: SUMO input files written to", BUILD)
        return

    ensure(RESULTS)
    keys = ["travel_time_s", "time_loss_s", "waiting_s", "mid_speed_kph", "max_halting", "co2_kg", "gate_total"]
    out = {"generated_with": "run_bmp.py", "config": cfg, "results": {}, "validation": {}}
    for (sid, pid), runs in per_seed.items():
        r = {"scenario": sid, "label": cfg["scenarios"][sid]["label"], "period": pid}
        for k in keys:
            v = [x[k] for x in runs]
            r[k] = round(statistics.mean(v), 2)
            r[k + "_sd"] = round(statistics.stdev(v), 2) if len(v) > 1 else 0.0
        r["gate_counts"] = [round(statistics.mean(x["gate_counts"][i] for x in runs), 1) for i in range(4)]
        rows.append(r)
        out["results"].setdefault(sid, {})[pid] = r

    # change vs. baseline
    for r in rows:
        b = out["results"]["S0_baseline"][r["period"]]
        for k in ("travel_time_s", "time_loss_s", "co2_kg"):
            r[k + "_chg_pct"] = round(100 * (r[k] - b[k]) / b[k], 1) if b[k] else None

    with open(os.path.join(RESULTS, "summary.csv"), "w", newline="", encoding="utf-8") as f:
        cols = ["scenario", "label", "period"] + [c for k in keys for c in (k, k + "_sd")] + \
               ["travel_time_s_chg_pct", "time_loss_s_chg_pct", "co2_kg_chg_pct"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

    # validation (baseline vs observed gate counts)
    vrows = []
    for pid, period in field["periods"].items():
        sim = out["results"]["S0_baseline"][pid]["gate_counts"]
        for i, obs in enumerate(period["gate_total"]):
            vrows.append(dict(period=pid, interval=period["intervals"][i], observed=obs, simulated=sim[i],
                              GEH=round(geh(sim[i], obs), 2)))
    share = 100 * sum(v["GEH"] < 5 for v in vrows) / len(vrows)
    out["validation"] = {"rows": vrows, "pct_GEH_below_5": round(share, 1)}
    with open(os.path.join(RESULTS, "validation.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(vrows[0])); w.writeheader(); w.writerows(vrows)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)

    try:
        make_figures(out, field)
    except ImportError:
        print("matplotlib not installed - skipped figures")
    print(f"\nDone. {share:.0f}% of baseline 15-min gate counts have GEH < 5.")
    print("Results in", RESULTS)


def make_figures(out, field):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    res = out["results"]
    scen = list(res)
    periods = list(field["periods"])
    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=200)
    wdt = 0.8 / len(scen)
    for i, s in enumerate(scen):
        ax.bar([p + i * wdt for p in range(len(periods))], [res[s][p]["time_loss_s"] for p in periods],
               wdt, yerr=[res[s][p]["time_loss_s_sd"] for p in periods], label=res[s][periods[0]]["label"],
               capsize=2)
    ax.set_xticks([p + 0.4 - wdt / 2 for p in range(len(periods))]); ax.set_xticklabels([p.title() for p in periods])
    ax.set_ylabel("Mean time loss per vehicle (s)"); ax.legend(fontsize=7, frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(os.path.join(RESULTS, "fig_time_loss.png"))

    v = out["validation"]["rows"]
    fig, ax = plt.subplots(figsize=(3.6, 3.6), dpi=200)
    ax.scatter([r["observed"] for r in v], [r["simulated"] for r in v], s=18)
    m = max(max(r["observed"] for r in v), max(r["simulated"] for r in v)) * 1.1
    ax.plot([0, m], [0, m], lw=0.8, color="grey")
    ax.set_xlabel("Observed 15-min gate count"); ax.set_ylabel("Simulated 15-min gate count")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(os.path.join(RESULTS, "fig_validation.png"))


if __name__ == "__main__":
    main()
