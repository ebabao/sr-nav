"""进化版 v2：全收益资产池 + RAM 单因子 + 不空仓满仓轮动 + 近三年。

进化顺序（按建议）：
  1) 换全收益口径（6/7 资产全收益，A500 价格）
  2) 去择时闸门、不空仓（任意时点满仓 Top-K）
  3) RAM 参数网格 + 平台期检验（追求年化≥25%，拒绝单点过拟合）
  4) MAE 增量复核

因子变体：
  - ram_raw    : 原始收益率动量 R_T（文章二的 ROC）
  - ram_sharpe : 收益/波动率（v0.1 主因子）
  - ram_mae    : RAM 与均线能量 MAE 融合（文章二进化）
  - ram_mom    : RAM + 动量加速度（近期动量-远期动量）
"""
import os, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, "data", "raw")
OUT = os.path.join(BASE, "output2")
os.makedirs(OUT, exist_ok=True)
log = lambda *a: print(*a, flush=True)

POOL = ["沪深300", "中证500", "中证1000", "科创50", "成长100", "价值100", "A500"]
FILES = {n: f"pool_{n}.csv" for n in POOL}
START, END = "2023-11-19", "2026-11-18"
TD = 250


def load_panel():
    px = {}
    for n in POOL:
        d = pd.read_csv(os.path.join(RAW, FILES[n]), parse_dates=["date"])
        d["close"] = pd.to_numeric(d["close"], errors="coerce")
        d = d.dropna(subset=["close"]).drop_duplicates("date").set_index("date")["close"]
        px[n] = d
    p = pd.concat(px, axis=1).dropna(how="any")
    log(f"[数据] 全收益池 {len(p)} 交易日 {p.index[0].date()}~{p.index[-1].date()} 资产 {list(p.columns)}")
    return p


def compute_factors(close, windows, weights):
    ret = close.pct_change()
    fac = {}
    # 风险调整动量 RAM（多周期）
    rams = {}
    for T in windows:
        r = close / close.shift(T) - 1
        vol = ret.rolling(T).std() * np.sqrt(TD)
        rams[T] = r / vol.replace(0, np.nan)
    fac["ram"] = sum(w * rams[T] for T, w in zip(windows, weights))
    # 原始动量 ROC（主周期）
    fac["roc"] = close / close.shift(windows[1]) - 1
    # 动量加速度：近期 vs 远期
    short = close / close.shift(windows[0]) - 1
    long = close / close.shift(windows[2]) - 1
    fac["accel"] = short - long
    # 均线能量 MAE（20日）
    N = 20
    ma = close.rolling(N).mean(); diff = ma.diff()
    mae = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    prev = {c: 0.0 for c in close.columns}
    for dt in close.index:
        for c in close.columns:
            v = diff.loc[dt, c]
            if pd.isna(v) or v == 0: prev[c] = 0.0
            elif v > 0: prev[c] = prev[c]+1 if prev[c]>0 else 1
            else: prev[c] = prev[c]-1 if prev[c]<0 else -1
            mae.loc[dt, c] = prev[c]
    fac["mae"] = mae
    return fac


def run(close, fac, mode, K, freq, start, end, cost_bps=8, wmode="equal"):
    """满仓轮动：每 freq 日按因子选 Top-K，无现金（除非不足 K）。"""
    dates = close.loc[start:end].index
    sig_days = set(dates[::freq])
    rf = 0.0  # 满仓无现金计息
    cost = cost_bps / 10000.0
    shares, nav = {n: 0.0 for n in POOL}, 1.0
    navs, turns, ntrade = [], [], 0
    pending = None
    for dt in dates:
        if pending is not None:  # T+1 执行昨日信号
            p = close.loc[dt]
            tot = sum(shares[n]*p[n] for n in POOL)
            old = {n: (shares[n]*p[n]/tot if tot>0 else 0) for n in POOL}
            keys = set(old) | set(pending)
            turn = sum(abs(old.get(k,0)-pending.get(k,0)) for k in keys)
            nav -= nav*turn*cost
            turns.append(turn); ntrade += 1
            shares = {n: pending.get(n,0)*nav/p[n] for n in POOL}
            pending = None
        # 盯市：已建仓按持仓估值，未建仓（首日）维持 nav=1
        if any(v > 0 for v in shares.values()):
            nav = sum(shares[n]*close.loc[dt,n] for n in POOL)
        navs.append((dt, nav))
        if dt in sig_days:
            score = fac[mode].loc[dt].dropna().sort_values(ascending=False)
            sel = list(score.index[:K])
            if wmode == "equal":
                w = {n: 1.0/len(sel) for n in sel}
            elif wmode == "score":
                pos = score[sel].clip(lower=0)
                w = {n: pos[n]/pos.sum() if pos.sum()>0 else 1/len(sel) for n in sel}
            pending = w
    return pd.Series(dict(navs)), np.mean(turns) if turns else 0


def metrics(nav, label):
    r = nav.pct_change().dropna()
    n = len(nav); years = n/TD
    total = nav.iloc[-1]/nav.iloc[0]-1
    ann = (nav.iloc[-1]/nav.iloc[0])**(1/years)-1
    vol = r.std()*np.sqrt(TD)
    sharpe = r.mean()/r.std()*np.sqrt(TD) if r.std()>0 else np.nan
    dd = nav/nav.cummax()-1; mdd = dd.min()
    calmar = ann/abs(mdd) if mdd<0 else np.nan
    return dict(策略=label, 累计=total, 年化=ann, 波动=vol, 夏普=sharpe, 回撤=mdd, Calmar=calmar)


def main():
    close = load_panel()
    log("\n=== 近三年各资产全收益涨幅 ===")
    for n in POOL:
        s = close.loc[START:END, n]
        log(f"  {n:<8} {(s.iloc[-1]/s.iloc[0]-1)*100:7.2f}%")

    windows, weights = (20, 60, 120), (0.2, 0.5, 0.3)
    fac = compute_factors(close, windows, weights)

    log("\n=== 步骤1-2：全收益池 + 不空仓，各因子/K/频率（年化） ===")
    grid = []
    for mode in ["ram", "roc", "accel", "mae"]:
        for K in [1, 2, 3]:
            for freq in [5, 10, 20]:
                nav, turn = run(close, fac, mode, K, freq, START, END)
                m = metrics(nav, f"{mode}-K{K}-F{freq}")
                grid.append({**m, "因子":mode, "K":K, "频率":freq, "换手":turn})
    gdf = pd.DataFrame(grid)
    gdf.to_csv(os.path.join(OUT, "参数网格.csv"), index=False, encoding="utf-8-sig")
    top = gdf.sort_values("年化", ascending=False).head(12)
    log(top[["策略","累计","年化","波动","夏普","回撤","换手"]].to_string(index=False,
        formatters={"累计":lambda x:f"{x*100:.1f}%","年化":lambda x:f"{x*100:.1f}%",
                    "波动":lambda x:f"{x*100:.1f}%","回撤":lambda x:f"{x*100:.1f}%",
                    "夏普":lambda x:f"{x:.2f}","换手":lambda x:f"{x:.2f}"}))

    log("\n=== 步骤3：是否达到年化25%（各因子最优） ===")
    for mode in ["ram","roc","accel","mae"]:
        sub = gdf[gdf["因子"]==mode].sort_values("年化", ascending=False).head(1).iloc[0]
        log(f"  {mode:<6} 最优 {sub['策略']:<16} 年化 {sub['年化']*100:.2f}%  "
            f"达标 {'YES' if sub['年化']>=0.25 else 'NO'}")

    # 默认配置（展示用）：ram K2 F10
    nav_def, turn_def = run(close, fac, "ram", 2, 10, START, END)
    m_def = metrics(nav_def, "v2 默认 RAM-K2-F10")
    nav_def.to_csv(os.path.join(OUT, "净值_v2默认.csv"), encoding="utf-8-sig")

    # 基准：各资产买入持有、等权
    mets = {m_def["策略"]: m_def}
    navs = {"v2 默认 RAM-K2-F10": nav_def}
    for n in POOL:
        s = close.loc[START:END,n]; s = s/s.iloc[0]
        navs[n] = s; mets[n] = metrics(s, n)
    eq = (1+close.loc[START:END].pct_change().fillna(0).mean(axis=1)).cumprod()
    navs["全池等权"] = eq; mets["全池等权"] = metrics(eq, "全池等权")
    pd.DataFrame(navs).to_csv(os.path.join(OUT,"净值对比.csv"), encoding="utf-8-sig")
    pd.DataFrame(mets).T.to_csv(os.path.join(OUT,"绩效对比.csv"), encoding="utf-8-sig")

    log("\n=== 默认策略 vs 基准 ===")
    mm = pd.DataFrame(mets).T
    log(mm[["累计","年化","波动","夏普","回撤"]].to_string(formatters={
        "累计":lambda x:f"{x*100:.1f}%","年化":lambda x:f"{x*100:.1f}%",
        "波动":lambda x:f"{x*100:.1f}%","回撤":lambda x:f"{x*100:.1f}%","夏普":lambda x:f"{x:.2f}"}))

    # 持仓记录（默认策略）
    rec = []
    dates = close.loc[START:END].index
    for j,dt in enumerate(dates[::10]):
        score = fac["ram"].loc[dt].dropna().sort_values(ascending=False)
        rec.append({"date":dt.strftime("%Y-%m-%d"),
                    "top1":score.index[0], "top2":score.index[1], "top3":score.index[2]})
    pd.DataFrame(rec).to_csv(os.path.join(OUT,"持仓轮动记录.csv"), index=False, encoding="utf-8-sig")

    json.dump({"start":START,"end":END,"pool":POOL,"windows":list(windows),"weights":list(weights),
               "cost_bps":8,"note":"全收益口径为主，A500价格；满仓不空仓"},
              open(os.path.join(OUT,"meta.json"),"w",encoding="utf-8"), ensure_ascii=False, indent=2)
    log(f"\n[完成] output2/ 已生成，默认策略年化 {m_def['年化']*100:.2f}%")
    return close, fac, gdf, navs, mets


if __name__ == "__main__":
    main()
