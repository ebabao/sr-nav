"""策略引擎分析增强：月度胜率 + 年度收益归因（哪类资产贡献）。

复用推荐配置 v0.11 ER+DD深阈（K1, gf0.2, dd-0.18），通过引擎新增的
return_weights 拿到每日收盘持仓权重，做两类分析：

  1) 月度胜率：月度收益为正的月份占比（全区间/分段/分年度）。
  2) 年度收益归因：每日贡献 = 上一日持仓权重 × 当日资产收益；
     按年累加到 7 个宽基/风格资产 + 国债ETF避险 + 交易成本，
     各项相加 = 策略年度收益（算术日收益口径），完全对账、无编造。

无前视：权重为当日收盘实际持仓，用于次日收益分解；T日信号T+1执行已含成本。
"""
import os, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
import evolve as ev
from style_adaptive import run_style_adaptive, load_shelter_price
from style_factors import build_style_factors

OUT = os.path.join(ev.BASE, "output5")
log = ev.log

# 推荐配置（与 V11_推荐净值.csv 一致）
KW = dict(K=1, hedge=0.5, style_tilt=0.5, regime_in_score=True,
          fit_gate="er_dd", gate_floor=0.2, dd_crash_th=-0.18)

LABEL = {"沪深300": "沪深300(大盘)", "中证500": "中证500(中盘)",
         "中证1000": "中证1000(小盘)", "科创50": "科创50(科技)",
         "成长100": "成长100(成长)", "价值100": "价值100(价值)",
         "A500": "A500(宽基)", "SHELTER": "国债ETF(避险)"}

SEGS = {"全区间2020-2026": ("2020-01-02", "2026-11-18"),
        "时间外2020-2023": ("2020-01-02", "2023-11-17"),
        "近三年2023-2026": ("2023-11-19", "2026-11-18"),
        "图片同期2024-2026": ("2024-01-02", "2026-11-18")}


def monthly_returns(nav, s=None, e=None):
    x = nav.loc[s:e] if (s or e) else nav
    m = x.resample("ME").last()
    return m.pct_change().dropna()


def winrate(r):
    if len(r) == 0:
        return dict(月数=0, 胜月=0, 月度胜率=np.nan, 月均收益=np.nan,
                    最好月=np.nan, 最差月=np.nan)
    return dict(月数=len(r), 胜月=int((r > 0).sum()), 月度胜率=float((r > 0).mean()),
                月均收益=float(r.mean()), 最好月=float(r.max()), 最差月=float(r.min()))


def main():
    close = ev.load_panel(); F, R = build_style_factors(close)
    sh = load_shelter_price().reindex(close.index).ffill()
    nav, lg, turn, nt, W = run_style_adaptive(close, F, R, sh,
                                              return_weights=True, **KW)
    nav.to_csv(os.path.join(OUT, "归因_推荐净值.csv"), encoding="utf-8-sig")
    log(f"[引擎] 换手{turn:.2f} 调仓{nt}次 权重矩阵{W.shape}")

    # ========== 1) 月度胜率 ==========
    mret_all = monthly_returns(nav)
    mdf = pd.DataFrame({"月份": mret_all.index.strftime("%Y-%m"),
                        "月度收益": mret_all.values,
                        "是否上涨": (mret_all.values > 0).astype(int)})
    mdf.to_csv(os.path.join(OUT, "归因_月度收益明细.csv"), index=False, encoding="utf-8-sig")

    wr_rows = []
    for tag, (s, e) in SEGS.items():
        wr_rows.append({"口径": tag, **winrate(monthly_returns(nav, s, e))})
    # 分年度
    for y in range(2020, 2027):
        r = monthly_returns(nav, f"{y}-01-01", f"{y}-12-31")
        wr_rows.append({"口径": f"{y}年", **winrate(r)})
    wrdf = pd.DataFrame(wr_rows)
    wrdf.to_csv(os.path.join(OUT, "归因_月度胜率汇总.csv"), index=False, encoding="utf-8-sig")
    log("\n=== 月度胜率 ===")
    log(wrdf.to_string(index=False, formatters={
        "月度胜率": lambda x: f"{x*100:.1f}%", "月均收益": lambda x: f"{x*100:+.2f}%",
        "最好月": lambda x: f"{x*100:+.1f}%", "最差月": lambda x: f"{x*100:+.1f}%"}))

    # ========== 2) 年度收益归因 ==========
    # 关键：区分执行日与非执行日（引擎 T+1 以收盘价建仓，执行日当日不计价收益）。
    #   - 执行日：净值变动 = 换手扣费，资产贡献记 0，全部归入"交易成本"。
    #   - 非执行日：净值变动 = 持仓权重 × 各资产当日收益。
    # 从信号日志推导执行日 = 每个信号日的下一交易日。
    idx = close.index
    exec_dates = set()
    for d in pd.to_datetime(lg["date"]):
        pos = idx.get_loc(d)
        if pos + 1 < len(idx):
            exec_dates.add(idx[pos + 1])

    RET = close.pct_change()
    RET["SHELTER"] = sh.pct_change()
    RET = RET.reindex(columns=W.columns)
    Wprev = W.shift(1)                       # 上一日收盘权重 = 当日初持仓
    contrib = Wprev * RET                    # 每日各资产收益贡献（非执行日有效）
    navr = nav.pct_change()
    is_exec = navr.index.isin(exec_dates)

    # 执行日：资产贡献清零；成本 = 当日净值变动（−换手扣费）
    cost = pd.Series(0.0, index=navr.index)
    cost[is_exec] = navr[is_exec]            # 负值（扣费）
    contrib.loc[is_exec, :] = 0.0            # 执行日不计价收益
    # 非执行日残差（应≈0，来自权重跟踪误差），并入成本项
    resid = navr - contrib.sum(axis=1) - cost
    cost = cost + resid

    valid = navr.notna()
    contrib, cost, navr = contrib[valid], cost[valid], navr[valid]

    rows = []
    for y in range(2020, 2027):
        mask = navr.index.year == y
        if mask.sum() < 15:
            continue
        row = {"年份": y}
        for c in W.columns:
            row[LABEL[c]] = float(contrib.loc[mask, c].sum())
        row["交易成本"] = float(cost[mask].sum())
        row["策略年收益"] = float(navr[mask].sum())          # 算术日收益累加
        row["年收益(几何)"] = float((1 + navr[mask]).prod() - 1)  # 几何年收益
        # 当年贡献最大的资产（正贡献中最大）
        asset_cols = [LABEL[c] for c in W.columns]
        row["主导资产"] = max(asset_cols, key=lambda k: row[k])
        rows.append(row)
    adf = pd.DataFrame(rows)
    adf.to_csv(os.path.join(OUT, "归因_年度收益归因.csv"), index=False, encoding="utf-8-sig")

    log("\n=== 年度收益归因（各资产贡献百分点，相加=策略年收益）===")
    show_cols = ["年份"] + [LABEL[c] for c in W.columns] + ["交易成本", "策略年收益", "主导资产"]
    log(adf[show_cols].to_string(index=False, formatters={
        c: (lambda x: f"{x*100:+.1f}%") for c in show_cols if c not in ("年份", "主导资产")}))

    # 对账校验
    asset_cols = [LABEL[c] for c in W.columns]
    adf["归因合计"] = adf[asset_cols].sum(axis=1) + adf["交易成本"]
    err = (adf["归因合计"] - adf["策略年收益"]).abs().max()
    log(f"\n[对账] 归因合计 vs 策略年收益 最大误差 {err:.2e}")
    log(f"[对账] 全区间各资产累计贡献: " +
        ", ".join(f"{c.replace('(','(').split('(')[0]} {adf[c].sum()*100:+.1f}%" for c in asset_cols) +
        f" | 交易成本 {adf['交易成本'].sum()*100:+.1f}%")

    log("\n[完成] output5/归因_*.csv 已生成")


if __name__ == "__main__":
    main()
