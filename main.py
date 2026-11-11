#!/usr/bin/env python3
""":
Roblox Up-and-Coming Forecast Entry (H1 Rebuild).
Implements an empirical rank-transition kernel across lag buckets with H1 enhancements:
cap 90 rows per place, place mass cap 0.95, per-game 24h log playing-growth tilt
with C=5 and unclamped gt60 path, per-game age-conditioned OUT multiplier before h<6 blend,
and MIN_P 0.0005. Standard library only, fully deterministic.
"""
import os
import json
import math
from datetime import datetime, timezone

def parse_iso(t):
    if not t:
        return None
    if isinstance(t, datetime):
        return t
    return datetime.fromisoformat(t.replace("Z", "+00:00"))

def main():
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(output_dir, exist_ok=True)

    # 1. Load history.ndjson
    history_path = os.path.join(input_dir, "history.ndjson")
    snaps = []
    with open(history_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            at_str = r.get("at")
            t = parse_iso(at_str)
            chart = []
            playing_map = {}
            for g in r.get("up_and_coming", []) or []:
                if g and "rank" in g and "universe_id" in g:
                    chart.append({
                        "rank": int(g["rank"]),
                        "universe_id": int(g["universe_id"]),
                        "name": g.get("name"),
                        "playing": g.get("playing")
                    })
                    playing_map[int(g["universe_id"])] = g.get("playing")
            
            details_in = r.get("details") or {}
            details_clean = {}
            if isinstance(details_in, dict):
                for k, v in details_in.items():
                    try:
                        uid_int = int(k)
                        if isinstance(v, dict):
                            details_clean[uid_int] = v
                    except ValueError:
                        pass

            snaps.append({
                "at_str": at_str,
                "at": t,
                "chart": chart,
                "playing": playing_map,
                "details": details_clean
            })

    snaps.sort(key=lambda s: s["at"])
    if not snaps:
        return

    t_end = snaps[-1]["at"]

    # Build created mapping: latest non-null created wins
    created = {}
    for s in snaps:
        for uid, det in s["details"].items():
            if det and det.get("created"):
                c_dt = parse_iso(det["created"])
                if c_dt:
                    created[uid] = c_dt

    # 2. Transition pairs (3.0 <= dt <= 140.0 hours)
    OUT = 999
    pairs = []
    for i in range(len(snaps)):
        ti = snaps[i]["at"]
        m_i = {g["universe_id"]: g["rank"] for g in snaps[i]["chart"]}
        for j in range(i + 1, len(snaps)):
            tj = snaps[j]["at"]
            dt = (tj - ti).total_seconds() / 3600.0
            if dt < 3.0:
                continue
            if dt > 140.0:
                break
            m_j = {g["universe_id"]: g["rank"] for g in snaps[j]["chart"]}
            for uid, r_from in m_i.items():
                r_to = m_j.get(uid, OUT)
                pairs.append((dt, r_from, r_to))

    # 3. Lag buckets
    BUCKET_BOUNDS = [(0, 6), (6, 14), (14, 26), (26, 44), (44, 68), (68, 96), (96, 140)]
    def get_bucket(x):
        for idx, (low, high) in enumerate(BUCKET_BOUNDS):
            if low <= x < high or (idx == len(BUCKET_BOUNDS) - 1 and low <= x <= high):
                return idx
        if x >= 140:
            return len(BUCKET_BOUNDS) - 1
        return 0

    num_buckets = len(BUCKET_BOUNDS)
    bucket_pairs = [[] for _ in range(num_buckets)]
    for p in pairs:
        b = get_bucket(p[0])
        bucket_pairs[b].append(p)

    # 4. Build kernel per bucket
    gt60_dist = {OUT: 0.97}
    for k in range(1, 11):
        gt60_dist[k] = 0.003

    kernels = []
    for b in range(num_buckets):
        bp = bucket_pairs[b]
        bucket_kernel = {}
        for r in range(1, 61):
            target_weights = {t: 0.0 for t in list(range(1, 41)) + [OUT]}
            tot_weight = 0.0
            for dt, r0, r_to in bp:
                diff = (r0 - r) / 2.0
                if abs(diff) > 3.0:
                    continue
                w = math.exp(-(diff * diff))
                if w < 0.05:
                    continue
                t_target = r_to if r_to <= 40 else OUT
                target_weights[t_target] += w
                tot_weight += w

            prior_each = 0.5 / 41.0
            denom = tot_weight + 0.5

            dist = {}
            for t in target_weights:
                dist[t] = (target_weights[t] + prior_each) / denom

            smoothed_1_40 = {}
            for t in range(1, 41):
                p_prev = dist.get(t - 1, 0.0) if t > 1 else 0.0
                p_curr = dist.get(t, 0.0)
                p_next = dist.get(t + 1, 0.0) if t < 40 else 0.0
                smoothed_1_40[t] = 0.25 * p_prev + 0.5 * p_curr + 0.25 * p_next

            for t in range(1, 41):
                dist[t] = smoothed_1_40[t]
            dist[OUT] = dist.get(OUT, 0.0)

            s_sum = sum(dist.values())
            if s_sum > 0:
                for t in dist:
                    dist[t] /= s_sum

            bucket_kernel[r] = dist
        kernels.append(bucket_kernel)

    # 2b. Playing growth (C = 5)
    last_snap = snaps[-1]
    last_chart = last_snap["chart"]
    
    growth = {}
    for g in last_chart:
        uid = g["universe_id"]
        p_now = g.get("playing")
        if p_now is not None and p_now > 0:
            p_then = None
            for s in reversed(snaps[:-1]):
                dt_h = (t_end - s["at"]).total_seconds() / 3600.0
                if 18.0 <= dt_h <= 30.0:
                    if uid in s["playing"] and s["playing"][uid] is not None and s["playing"][uid] > 0:
                        p_then = s["playing"][uid]
                        break
            if p_then is not None and p_then > 0:
                g_val = math.log(p_now / p_then)
                growth[uid] = max(-1.5, min(3.0, g_val))
            else:
                growth[uid] = 0.0
        else:
            growth[uid] = 0.0

    # 5. Forecast loop
    game_accum_p = {g["universe_id"]: {k: 0.0 for k in range(1, 11)} for g in last_chart}
    game_accum_exp_rank = {g["universe_id"]: 0.0 for g in last_chart}

    for g in last_chart:
        uid = g["universe_id"]
        r0 = g["rank"]
        
        g_val = growth.get(uid, 0.0)
        _r_src = int(round(r0 - 5 * g_val))
        
        for h in range(1, 73):
            bucket_idx = get_bucket(h)
            
            if _r_src <= 60:
                src_rank_clamped = max(1, _r_src)
                dist = dict(kernels[bucket_idx].get(src_rank_clamped, gt60_dist))
            else:
                dist = dict(gt60_dist)

            # Per-age age-conditioned OUT multiplier BEFORE h<6 blend
            if uid in created:
                age_days = (t_end - created[uid]).total_seconds() / 86400.0
                if age_days <= 10:
                    m = 0.42
                elif age_days <= 20:
                    m = 0.38
                elif age_days <= 25:
                    m = 0.95
                elif age_days <= 28:
                    m = 1.52
                else:
                    m = 2.13
                if m != 1.0:
                    dist[OUT] = dist.get(OUT, 0.0) * m
                    d_sum = sum(dist.values())
                    if d_sum > 0:
                        for t_key in dist:
                            dist[t_key] /= d_sum

            # h < 6 blend
            if h < 6:
                scale = h / 6.0
                target_key = r0 if r0 <= 40 else OUT
                new_dist = {k: v * scale for k, v in dist.items()}
                new_dist[target_key] = new_dist.get(target_key, 0.0) + (1.0 - scale)
                dist = new_dist

            for k in range(1, 11):
                game_accum_p[uid][k] += dist.get(k, 0.0)
            
            exp_r_h = sum(t * dist.get(t, 0.0) for t in range(1, 41)) + 55.0 * dist.get(OUT, 0.0)
            game_accum_exp_rank[uid] += exp_r_h

    game_avg_p = {}
    game_avg_exp_rank = {}
    for uid in game_accum_p:
        game_avg_p[uid] = {k: v / 72.0 for k, v in game_accum_p[uid].items()}
        game_avg_exp_rank[uid] = game_accum_exp_rank[uid] / 72.0

    # 6. Emit
    MIN_P = 0.0005
    probabilities = []
    
    for k in range(1, 11):
        candidates = []
        for uid, p_dict in game_avg_p.items():
            p_val = p_dict.get(k, 0.0)
            if p_val >= MIN_P:
                candidates.append((uid, p_val))
        
        candidates.sort(key=lambda x: x[1], reverse=True)
        candidates = candidates[:90]
        
        if candidates:
            total_p = sum(c[1] for c in candidates)
            scale = 1.0
            if total_p > 0.90:
                scale = 0.90 / total_p
            
            vals = [(uid, p_val * scale) for uid, p_val in candidates]
            s_pre = sum(v[1] for v in vals)
            if s_pre > 0:
                powered = [(uid, v ** 1.4) for uid, v in vals]
                s_post = sum(p[1] for p in powered)
                if s_post > 0:
                    temp_scale = s_pre / s_post
                    for uid, p_pow in powered:
                        p_final = round(p_pow * temp_scale, 6)
                        if p_final > 0:
                            probabilities.append({
                                "universe_id": int(uid),
                                "place": int(k),
                                "p": p_final
                            })

    sorted_games = sorted(last_chart, key=lambda g: game_avg_exp_rank.get(g["universe_id"], 999.0))
    top10 = [g["universe_id"] for g in sorted_games[:10]]

    forecast = {
        "probabilities": probabilities,
        "top10": top10
    }

    forecast_path = os.path.join(output_dir, "forecast.json")
    with open(forecast_path, "w", encoding="utf-8") as f:
        json.dump(forecast, f, separators=(',', ':'))

if __name__ == "__main__":
    main()
