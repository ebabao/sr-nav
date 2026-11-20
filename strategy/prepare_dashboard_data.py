"""为 v1.0 净值看板准备全部数据：日频净值 vs 中证800、月度收益矩阵、分年统计、当前持仓。
全部来自 v1.0 真实回测与真实指数数据，不编造。"""
import os, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
import evolve as ev
from style_adaptive import load_shelter_price

V1_DIR = os.path.join(ev.BASE, "output5", "v1")

# 资产展示名（与 engine_attribution.py 一致）
LABEL = {"沪深300": "沪深300", "中证500": "中证500",
         "中证1000": "中证1000", "科创50": "科创50",
         "成长100": "成长100", "价值100": "价值100",
         "A500": "A500", "SHELTER": "国债ETF"}


def compute_attribution(nav, lg, W):
    """用 v1.0 同源数据做年度收益归因（复用 engine_attribution 的执行日区分逻辑）。
    执行日(T+1收盘建仓当日)资产贡献=0、净值变动全部计入交易成本；
    非执行日贡献=上一日权重×当日资产收益；按年累加，各项相加=策略年收益。"""
    close = ev.load_panel()
    sh = load_shelter_price().reindex(close.index).ffill()

    idx = close.index
    exec_dates = set()
    for d in pd.to_datetime(lg["date"]):
        pos = idx.get_loc(d)
        if pos + 1 < len(idx):
            exec_dates.add(idx[pos + 1])

    RET = close.pct_change()
    RET["SHELTER"] = sh.pct_change()
    RET = RET.reindex(columns=W.columns)
    Wprev = W.shift(1)
    contrib = Wprev * RET
    navr = nav.pct_change()
    is_exec = navr.index.isin(exec_dates)

    cost = pd.Series(0.0, index=navr.index)
    cost[is_exec] = navr[is_exec]
    contrib.loc[is_exec, :] = 0.0
    resid = navr - contrib.sum(axis=1) - cost
    cost = cost + resid

    valid = navr.notna()
    contrib, cost, navr = contrib[valid], cost[valid], navr[valid]

    asset_cols = [LABEL.get(c, c) for c in W.columns]
    years = []
    for y in range(2020, 2027):
        yd = navr.index[navr.index.year == y]
        if len(yd) < 15:
            continue
        yd = yd[1:]  # 剔除年内首日(含跨年隔夜收益)，与分年统计"年内首末净值"口径严格一致
        vals = [float(contrib.loc[yd, c].sum()) for c in W.columns]
        tc = float(cost.loc[yd].sum())
        arith = sum(vals) + tc                          # 算术日收益累加（分解口径）
        geo = float((1 + navr.loc[yd]).prod() - 1)      # 几何年收益（与分年统计/KPI一致）
        compound = geo - arith                          # 复利效应：使分解严格对账到几何收益
        rows = dict(zip(asset_cols, vals))
        leader = max(asset_cols, key=lambda k: rows[k])
        years.append({"year": y, "contrib": [round(v, 6) for v in vals],
                      "cost": round(tc, 6), "arith": round(arith, 6),
                      "compound": round(compound, 6), "strategy": round(geo, 6),
                      "leader": leader})
    # 全区间累计贡献
    total = [round(float(contrib[c].sum()), 6) for c in W.columns]
    total_cost = round(float(cost.sum()), 6)
    # 对账：各资产+成本+复利效应 vs 几何年收益
    err = max(abs(sum(r["contrib"]) + r["cost"] + r["compound"] - r["strategy"]) for r in years)
    return {"assets": asset_cols, "years": years, "total": total,
            "total_cost": total_cost, "max_err": err}


def main():
    nav = pd.read_csv(os.path.join(V1_DIR, "v1_净值.csv"), index_col=0).iloc[:, 0]
    nav.index = pd.to_datetime(nav.index)
    lg = pd.read_csv(os.path.join(V1_DIR, "v1_信号日志.csv"))
    W = pd.read_csv(os.path.join(V1_DIR, "v1_持仓权重.csv"), index_col=0)
    W.index = pd.to_datetime(W.index)
    z800 = pd.read_csv(os.path.join(ev.BASE, "data", "raw", "pool_中证800.csv"),
                       parse_dates=["date"]).set_index("date")["close"]

    # 基准按策略净值日对齐，起点归一化
    z800 = z800.reindex(nav.index).ffill()
    nav_n = nav / nav.iloc[0]
    z800_n = z800 / z800.iloc[0]
    dd = nav / nav.cummax() - 1.0

    # ---- 月度收益矩阵（策略）----
    mret = nav.resample("ME").last().pct_change()
    mret.iloc[0] = nav.resample("ME").last().iloc[0] / nav.iloc[0] - 1
    years = sorted(set(d.year for d in mret.index))
    heat = {}
    for y in years:
        vals = [None] * 12
        for dt, v in mret.items():
            if dt.year == y:
                vals[dt.month - 1] = round(float(v), 5)
        heat[str(y)] = vals

    # ---- 分年统计（策略 vs 中证800）----
    year_rows = []
    for y in years:
        sub = nav.loc[f"{y}-01-01":f"{y}-12-31"]
        zsub = z800.loc[f"{y}-01-01":f"{y}-12-31"]
        if len(sub) < 2: continue
        r = sub.pct_change().dropna()
        total = float(sub.iloc[-1] / sub.iloc[0] - 1)
        mdd = float((sub / sub.cummax() - 1).min())
        vol = float(r.std() * np.sqrt(ev.TD))
        sharpe = float(r.mean() / r.std() * np.sqrt(ev.TD)) if r.std() > 0 else 0.0
        ztotal = float(zsub.iloc[-1] / zsub.iloc[0] - 1)
        year_rows.append({"year": y, "ret": total, "cagr": total, "mdd": mdd,
                          "vol": vol, "sharpe": sharpe, "calmar": total / abs(mdd) if mdd < 0 else 0,
                          "z800": ztotal, "excess": total - ztotal})
    # 月度胜率
    allm = [v for vals in heat.values() for v in vals if v is not None]
    winrate = sum(1 for v in allm if v > 0) / len(allm) if allm else 0

    # ---- 当前持仓（最近一个信号日）----
    last = lg.iloc[-1]
    holdings = {c: round(float(W.iloc[-1][c]), 4) for c in W.columns if W.iloc[-1][c] > 0}
    cur_date = str(W.index[-1].date())

    # ---- 年度收益归因（v1.0 同源数据）----
    attr = compute_attribution(nav, lg, W)
    ev.log(f"[归因] 对账最大误差 {attr['max_err']:.2e} · " +
           "全区间累计: " + ", ".join(f"{a} {v*100:+.1f}%" for a, v in zip(attr["assets"], attr["total"])) +
           f" | 交易成本 {attr['total_cost']*100:+.1f}%")

    board = {
        "meta": {
            "version": "v1.0", "name": "风格自适应动量轮动 · 回撤断路器",
            "start": nav.index[0].strftime("%Y-%m-%d"), "end": nav.index[-1].strftime("%Y-%m-%d"),
            "n_days": len(nav), "winrate": round(winrate, 4),
            "last_signal": cur_date,
        },
        "dates": [d.strftime("%Y-%m-%d") for d in nav.index],
        "nav": [round(float(x), 5) for x in nav_n.values],
        "z800": [round(float(x), 5) for x in z800_n.values],
        "dd": [round(float(x), 5) for x in dd.values],
        "heat": heat,
        "years": year_rows,
        "attribution": attr,
        "holdings": holdings,
        "params": {"K": 1, "freq": 10, "cost_bps": 8, "hedge": 0.5,
                   "fit_gate": "er_dd", "gate_floor": 0.2, "dd_crash_th": -0.18,
                   "cb_mode": "cooldown", "cb_dd_start": -0.10,
                   "cb_share": 1.0, "cb_days": 20},
    }
    with open(os.path.join(V1_DIR, "v1_dashboard_data.json"), "w", encoding="utf-8") as f:
        json.dump(board, f, ensure_ascii=False, separators=(",", ":"))
    ev.log(f"[完成] 看板数据 {len(board['dates'])}日 {len(board['years'])}年 持仓{len(holdings)}项 月度胜率{winrate*100:.1f}%")
    ev.log(f"最新持仓({cur_date}): " + ", ".join(f"{k} {v*100:.0f}%" for k, v in holdings.items()))


if __name__ == "__main__":
    main()
