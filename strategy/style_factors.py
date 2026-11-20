"""行情风格适配性因子族（增量模块，不改动 ml_factors.py）—— 无前视。

设计动机（来自 v0.8 诊断）：
  时间外2020-2023 风格反转快→长周期动量失效(roc_60 IC=-0.059)、短周期有效(roc_20 IC=0.073)；
  近三年是单边慢牛。故需"识别当前风格状态 + 选当前最强"，而非固定长周期动量。

因子依据（均可查证）：
  - 相对强弱 RS：Jegadeesh & Titman (1993) 横截面动量；资产收益 - 池等权收益
  - 横截面排名动量 rank_mom：Qlib Alpha158 的 csrank 思想；排名分位的变化
  - 趋势效率 trend_eff：净位移/路径长度，趋势持续性代理（类似 "趋势纯度"）
  - 风格暴露 beta：资产对 成长/价值、大/小盘 比价收益的滚动 beta（Fama-French 风格因子思想）
  - 市场 regime（时序）：等权组合 MAE/动量、风格比价动量、波动状态

所有因子仅用 T 日及之前数据；横截面标准化在主程序用 ml_factors._cs_z。
"""
import warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")


def _cs_rank(df):
    """当日横截面排名分位（0~1）。"""
    return df.rank(axis=1, pct=True)


def build_style_factors(close, growth="成长100", value="价值100",
                        small="中证1000", large="沪深300"):
    """返回 (raw_factors dict, regime DataFrame)。
    raw_factors[k] = DataFrame(index=date, columns=assets) 横截面因子。
    regime[k] = Series(index=date) 市场级时序状态（全资产共享）。
    """
    idx, cols = close.index, close.columns
    ret = close.pct_change()
    ew = ret.mean(axis=1)                      # 资产池等权日收益（无前视）
    ew_nav = (1 + ew.fillna(0)).cumprod()      # 等权组合净值，作为市场代理

    F = {}   # 横截面因子
    # ---- 1) 相对强弱 RS：资产 - 池等权（20/60日）----
    for T in (20, 60):
        asset_cum = close / close.shift(T) - 1
        bench_cum = ew_nav / ew_nav.shift(T) - 1
        F[f"rs_{T}"] = asset_cum.sub(bench_cum, axis=0)

    # ---- 2) 横截面排名动量：当前20日收益排名 - 20日前排名 ----
    r20 = close / close.shift(20) - 1
    rank_now = _cs_rank(r20)
    rank_prev = rank_now.shift(20)
    F["rank_mom_20"] = (rank_now - rank_prev).astype(float)

    # ---- 3) 趋势效率：|净位移| / 路径长度（20/60日），越高越"平滑单边" ----
    for T in (20, 60):
        net = (close - close.shift(T)).abs()
        path = ret.abs().rolling(T).sum() * close.shift(T).abs()
        F[f"trend_eff_{T}"] = (net / path.replace(0, np.nan))

    # ---- 4) 风格暴露 beta：资产对 成长/价值、小盘/大盘 比价收益的滚动 beta（60日）----
    gv_ret = (close[growth] / close[growth].shift(1) - 1) - (close[value] / close[value].shift(1) - 1)
    ls_ret = (close[small] / close[small].shift(1) - 1) - (close[large] / close[large].shift(1) - 1)
    gv_var = gv_ret.rolling(60).var()
    ls_var = ls_ret.rolling(60).var()
    beta_gv, beta_ls = {}, {}
    for c in cols:
        beta_gv[c] = ret[c].rolling(60).cov(gv_ret) / gv_var.replace(0, np.nan)
        beta_ls[c] = ret[c].rolling(60).cov(ls_ret) / ls_var.replace(0, np.nan)
    F["style_beta_gv"] = pd.DataFrame(beta_gv)
    F["style_beta_ls"] = pd.DataFrame(beta_ls)

    # ---- 5) 短周期反转/加速度：捕捉风格反转拐点 ----
    F["rs_accel"] = F["rs_20"] - F["rs_60"]        # 相对强弱的加速度
    F["roc_5"] = close / close.shift(5) - 1        # 超短周期（反转快时更有效）

    for k in F:
        F[k] = F[k].replace([np.inf, -np.inf], np.nan)

    # ================= 时序 regime 因子（市场级） =================
    R = pd.DataFrame(index=idx)
    R["mkt_nav"] = ew_nav
    R["mkt_mom_20"] = ew_nav / ew_nav.shift(20) - 1
    R["mkt_mom_60"] = ew_nav / ew_nav.shift(60) - 1
    # 等权组合均线能量（20日）
    ma = ew_nav.rolling(20).mean(); diff = ma.diff()
    mae = pd.Series(0.0, index=idx); prev = 0.0
    for dt in idx:
        v = diff.loc[dt]
        if pd.isna(v) or v == 0: prev = 0.0
        elif v > 0: prev = prev + 1 if prev > 0 else 1
        else: prev = prev - 1 if prev < 0 else -1
        mae.loc[dt] = prev
    R["mkt_mae_20"] = mae
    # 风格比价动量：>0 表示该风格占优
    R["regime_gv"] = (close[growth] / close[value]).pct_change(20)   # >0 成长占优
    R["regime_ls"] = (close[small] / close[large]).pct_change(20)    # >0 小盘占优
    R["mkt_vol"] = ew.rolling(20).std() * np.sqrt(252)

    # ---- 6) 早期预警（改造v0.10）：降低避险滞后 ----
    # 短期5日动量与20日动量之差除以各自天数 = 日均收益加速度；<0 表示动能减速
    R["mkt_mom_5"] = ew_nav / ew_nav.shift(5) - 1
    R["mkt_accel"] = R["mkt_mom_5"] / 5 - R["mkt_mom_20"] / 20
    # 波动跳升比：当前20日波动 / 过去60日平均波动；>1 表示波动放大（风险抬升）
    R["mkt_vol_ratio"] = R["mkt_vol"] / R["mkt_vol"].rolling(60).mean()

    # ---- 7) fit门控特征（改造v0.11，来自GitHub方法+gate_signal_test验证）----
    # Kaufman效率比率 ER：风格比价净位移/路径总长。高=趋势干净可信，低=震荡切换（KAMA思想）
    gv_ratio = close[growth] / close[value]
    er_dir = (gv_ratio - gv_ratio.shift(20)).abs()
    er_vol = gv_ratio.diff().abs().rolling(20).sum()
    R["er_gv_20"] = er_dir / er_vol.replace(0, np.nan)
    # Momentum Crash 熊市指示（Daniel & Moskowitz 2016）：市场距近60日高点回撤
    R["mkt_dd"] = ew_nav / ew_nav.rolling(60).max() - 1

    return F, R


if __name__ == "__main__":
    import evolve as ev
    close = ev.load_panel()
    F, R = build_style_factors(close)
    print(f"横截面风格因子 {len(F)}: {list(F.keys())}")
    print(f"时序 regime: {[c for c in R.columns]}")
    for k in ["rs_20", "rank_mom_20", "trend_eff_20", "style_beta_gv"]:
        print(f"  {k:<16} 非空{F[k].notna().sum().sum()}")
    print("\nregime 尾部:")
    print(R[["mkt_mom_20", "mkt_mae_20", "regime_gv", "regime_ls"]].tail(3).round(3).to_string())
