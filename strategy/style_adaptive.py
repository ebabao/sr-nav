"""风格自适应择时轮动策略：选当前最强 + 风格regime倾斜 + 熊市避险。无前视、无训练窗。

核心（来自 v0.8 诊断 + v0.9 IC验证）：
  - 横截面选最强用 rank_mom_20（时间外IC 0.134/正占66%，唯一跨期同号因子），
    取代"固定长周期动量"（roc_60 时间外IC=-0.059 已失效）。
  - 风格 regime 倾斜：regime_gv/regime_ls 判断成长/价值、大/小盘占优，
    对风格 beta 匹配的资产加权 → "择时最强的行情"。
  - 熊市避险：等权组合 mkt_mae+mkt_mom 双确认，切国债ETF（非空仓）。
  - 无训练窗：因子当日即算，2020-01 全程有信号，消除空仓踏空。

无前视：所有因子/regime 在 T 日收盘用 T 日及之前数据算，T+1 执行。
"""
import os, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
import evolve as ev
from style_factors import build_style_factors

OUT = os.path.join(ev.BASE, "output5")
os.makedirs(OUT, exist_ok=True)
log = ev.log


def load_shelter_price(code="511010"):
    d = pd.read_csv(os.path.join(ev.RAW, f"etf_shelter_{code}.csv"), parse_dates=["date"])
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    return d.dropna(subset=["close"]).set_index("date")["close"]


def csz(df):
    return df.sub(df.mean(axis=1), axis=0).div(df.std(axis=1).replace(0, np.nan), axis=0)


def run_style_adaptive(close, F, R, shelter, K=2, freq=10, start="2020-01-02", end=ev.END,
                       hedge=0.5, mae_th=0, mom_th=-0.03, style_tilt=0.5, cost_bps=8,
                       regime_in_score=False, early_mode="trend", accel_th=-0.003,
                       vol_ratio_th=1.3, vol_th=0.0, fit_gate="off", gate_floor=0.2,
                       dd_crash_th=-0.12, return_weights=False,
                       cb_dd_start=None, cb_dd_full=-0.18, shelter_cap=1.0,
                       cb_mode="cppi", cb_share=0.5, cb_days=10, cb_reset_peak=True,
                       ext_warn=None):
    """风格自适应回测。T日信号，T+1执行，含成本。

    return_weights=True 时额外返回第5个值 W（每日收盘持仓权重 DataFrame，
    index=交易日, columns=ASSETS+["SHELTER"]），用于月度胜率/年度收益归因。
    默认 False 时返回值与旧版完全一致（4个），所有既有调用不受影响。

    v0.10 增量改造（默认参数完全等同旧行为，便于A/B对照）：
      regime_in_score : True=把风格契合度直接加进选股score参与排序（K1也能择时最强行情）；
                        False=旧逻辑仅调权重（K1时倾斜恒为0）。
      early_mode      : "trend"=旧双确认(MAE<=0且mom<=th,滞后)；
                        "early"=早期预警(动能减速accel<=th 或 波动跳升且动量为负)；
                        "combine"=两种任一触发(更早、覆盖更全)。
      accel_th        : 日均收益加速度阈值，越接近0越敏感。
      vol_ratio_th    : 波动跳升比阈值。
      vol_th          : early模式下波动跳升触发要求的动量为负上限。
      fit_gate        : v0.11门控。"off"=旧行为；"er"=Kaufman效率比率门控；
                        "er_dd"=ER+市场回撤双门控（含Momentum Crash防护）。
      gate_floor      : 门控下限（保留最小风格押注，避免完全不信）。
      dd_crash_th     : er_dd模式下市场深度回撤阈值，跌破则fit归零(退回纯动量)+切国债避险。

    v0.12 增量改造（GitHub CPPI / equity-curve drawdown control）：
      cb_dd_start     : 断路器启动回撤（相对策略自身净值高水位线，如 -0.06）。回撤未达此
                        值不退守(保留满仓收益敞口→收益不稀释)。None=关闭断路器(默认,兼容v0.11)。
      cb_dd_full      : 完全退守回撤（如 -0.18），回撤越深退守国债比例越高、连续缩放。
      shelter_cap     : 国债仓位上限(≤1)。退守比例 = clip((|dd|-|start|)/(|full|-|start|),0,1)*cap。
      cb_mode         : "cppi"=连续缩放(状态依赖,回撤不恢复就一直退守)；
                        "cooldown"=事件驱动熔断(用户诉求):回撤触阈值→退守cb_share国债、
                        持续cb_days个交易日后强制回补、并重置高水位线(打断死亡螺旋,
                        避免长期低仓位稀释收益)。
      cb_share        : cooldown模式熔断期固定国债仓位(如0.5)。
      cb_days         : cooldown模式熔断持续交易日数(如10)。
      cb_reset_peak   : cooldown熔断结束是否重置高水位线为当时净值(True=防重复触发)。
      ——机理：基于策略净值(路径依赖)而非市场，浅回撤不打扰、与既有hedge取max(不叠加)。
         T日收盘用截至T净值算、T+1执行，零前视。

    风险预警增强（第28节，ext_warn）：
      ext_warn        : 可选 pd.Series(index=交易日, bool)，市场级领先风险预警信号（如ML/领先因子
                        预测的"未来快速下跌"）。True 时与自身回撤断路器"取或"触发同样cooldown退守，
                        但用因果扩张窗口阈值判定，零前视。None=关闭(默认,完全兼容既有行为)。
                        机理：自身回撤是滞后指标(跌完才触发)，领先因子在峰值前报警→更早避险。
    """
    dates = close.loc[start:end].index
    sig_days = list(dates[::freq]); sig_set = set(sig_days)
    cost = cost_bps / 10000.0
    ASSETS = list(close.columns)
    S = "SHELTER"

    # 主选股分数：rank_mom 为主 + rs_accel + 短动量（均为 z-score）
    score = csz(F["rank_mom_20"]) + 0.4 * csz(F["rs_accel"]) + 0.3 * csz(F["roc_5"])
    # 风格 beta 标准化（用于 tilt）
    bgv = csz(F["style_beta_gv"]); bls = csz(F["style_beta_ls"])

    shares = {n: 0.0 for n in ASSETS + [S]}; nav = 1.0
    pending = None; navs = []; logrows = []; ntrade = 0; turns = []
    wrows = []  # 每日收盘持仓权重（供归因）
    peak_nav = 1.0          # v0.12 断路器：策略净值高水位线（路径依赖，零前视）
    cb_end_idx = -1         # cooldown模式：熔断结束的交易日序号
    cb_events = 0           # 熔断触发次数（日志用）

    for j, dt in enumerate(dates):
        # T+1 执行昨日信号
        if pending is not None:
            p = close.loc[dt]
            tot = sum(shares[n] * (shelter.loc[dt] if n == S else p[n])
                      for n in ASSETS + [S] if n in shares)
            old = {n: (shares[n] * (shelter.loc[dt] if n == S else p[n]) / tot if tot > 0 else 0)
                   for n in ASSETS + [S]}
            keys = set(old) | set(pending)
            turn = sum(abs(old.get(k, 0) - pending.get(k, 0)) for k in keys)
            nav -= nav * turn * cost; turns.append(turn); ntrade += 1
            for n in ASSETS + [S]:
                px = shelter.loc[dt] if n == S else p[n]
                shares[n] = pending.get(n, 0) * nav / px
            pending = None
        # 盯市
        p = close.loc[dt]
        tot = sum(shares[n] * (shelter.loc[dt] if n == S else p[n]) for n in ASSETS + [S])
        if tot > 0: nav = tot
        navs.append((dt, nav))
        if nav > peak_nav: peak_nav = nav   # 更新高水位线（用截至今日净值，零前视）
        if return_weights:
            wrows.append({n: (shares[n] * (shelter.loc[dt] if n == S else p[n]) / tot
                              if tot > 0 else 0.0) for n in ASSETS + [S]})

        # 信号日
        if dt in sig_set:
            gv = R.loc[dt, "regime_gv"]; ls = R.loc[dt, "regime_ls"]
            # 全池风格契合度：当前占优风格 × 资产风格beta（正=契合占优风格）
            fit = pd.Series(0.0, index=ASSETS)
            if pd.notna(gv):
                d_gv = 1 if gv > 0 else -1            # >0成长占优
                fit += d_gv * bgv.loc[dt].fillna(0)
            if pd.notna(ls):
                d_ls = 1 if ls > 0 else -1            # >0小盘占优
                fit += d_ls * bls.loc[dt].fillna(0)

            # ★改造v0.11：fit门控（Kaufman ER + Momentum Crash，GitHub方法论）
            eff = 1.0
            crash = False
            if fit_gate != "off":
                er = R.loc[dt, "er_gv_20"]; dd = R.loc[dt, "mkt_dd"]
                er_sig = 1.0
                if pd.notna(er):
                    # ER相对强度：0.15~0.40 映射到 0~1（该池er均值约0.25）
                    er_sig = float(np.clip((er - 0.15) / 0.25, 0.0, 1.0))
                if fit_gate == "er":
                    eff = gate_floor + (1 - gate_floor) * er_sig
                elif fit_gate == "er_dd":
                    # 熊市指示：市场在60日高点附近(dd≈0)信号强，深跌(dd<=th)信号弱/crash
                    dd_sig = 1.0
                    if pd.notna(dd):
                        dd_sig = float(np.clip((dd - dd_crash_th) / abs(dd_crash_th), 0.0, 1.0))
                        crash = bool(dd <= dd_crash_th)
                    eff = gate_floor + (1 - gate_floor) * (0.5 * er_sig + 0.5 * dd_sig)
                    if crash: eff = 0.0   # 深度回撤+可能崩盘：完全不押风格
                eff = float(np.clip(eff, 0.0, 1.0))
            gated_fit = fit * eff

            if regime_in_score:
                # ★改造1：风格契合度直接加进选股score参与排序——K1也能真正择时最强行情
                total = score.loc[dt] + style_tilt * gated_fit
                sc = total.dropna().sort_values(ascending=False)
            else:
                # 旧逻辑：先用原始score选集合，再仅倾斜权重（K1时无效）
                sc = score.loc[dt].dropna().sort_values(ascending=False)
            if len(sc) == 0: continue
            sel = list(sc.index[:K])

            if regime_in_score:
                # 已把fit融入score，权重按score相对强度 softly 分配（避免极端集中）
                sv = sc.loc[sel].clip(lower=0)
                wts = (sv / sv.sum()) if sv.sum() > 0 else pd.Series(1.0/len(sel), index=sel)
            else:
                # 旧逻辑：倾斜只调整权重，不改变入选集合
                tilt_score = fit.reindex(sel)
                wts = pd.Series(1.0 / len(sel), index=sel) + style_tilt * 0.1 * tilt_score
                wts = wts.clip(lower=0).fillna(1.0/len(sel)); wts = wts / wts.sum()

            # 熊市避险判定（★改造2：可切换早期预警）
            mae = R.loc[dt, "mkt_mae_20"]; mom = R.loc[dt, "mkt_mom_20"]
            accel = R.loc[dt, "mkt_accel"]; vr = R.loc[dt, "mkt_vol_ratio"]
            trend_off = (pd.notna(mae) and mae <= mae_th) and (pd.notna(mom) and mom <= mom_th)
            # 早期预警：动能明显减速，或(波动跳升且动量已转负)
            early_off = ((pd.notna(accel) and accel <= accel_th) or
                         (pd.notna(vr) and pd.notna(vr) and vr >= vol_ratio_th and
                          pd.notna(mom) and mom <= vol_th))
            if early_mode == "early":
                risk_off = bool(early_off)
            elif early_mode == "combine":
                risk_off = bool(trend_off or early_off)
            else:  # "trend" 旧行为
                risk_off = bool(trend_off)
            # Momentum Crash 防护：深度回撤时强制避险
            if crash:
                risk_off = True

            # ★改造v0.12：回撤断路器（基于策略自身净值高水位线，路径依赖，零前视）
            #   dd = nav/peak - 1 (≤0)。与趋势hedge取max(不叠加)。
            cb_sh = 0.0
            dd_self = nav / peak_nav - 1.0 if peak_nav > 0 else 0.0
            # 领先风险预警（可选，市场级，零前视）：与自身回撤"取或"触发cooldown
            warn_hit = bool(ext_warn.loc[dt]) if (ext_warn is not None and dt in ext_warn.index) else False
            cb_active = cb_dd_start is not None
            if cb_active:
                if cb_mode == "cooldown":
                    # 事件驱动熔断：回撤/预警触阈值→退守cb_share国债cb_days日→强制回补+重置高位
                    if (dd_self <= cb_dd_start or warn_hit) and j > cb_end_idx:
                        cb_end_idx = j + int(cb_days)   # 熔断持续到该序号（含）
                        cb_events += 1
                        if cb_reset_peak:
                            peak_nav = nav              # 重置高水位：防"越退越低"重复触发
                    if j <= cb_end_idx:
                        cb_sh = float(np.clip(cb_share, 0.0, 1.0))
                else:  # "cppi" 连续缩放（对照用）
                    denom = abs(cb_dd_full) - abs(cb_dd_start)
                    if denom > 0 and dd_self <= cb_dd_start:
                        cb_sh = float(np.clip((abs(dd_self) - abs(cb_dd_start)) / denom, 0.0, 1.0))
                        cb_sh *= shelter_cap
            shelter_w = max(hedge if risk_off else 0.0, cb_sh)
            shelter_w = float(np.clip(shelter_w, 0.0, 1.0))
            w = {n: wts[n] * (1 - shelter_w) for n in sel}
            if shelter_w > 0: w[S] = shelter_w
            pending = w
            logrows.append({"date": dt.strftime("%Y-%m-%d"),
                            "cb_sh": round(cb_sh, 3), "dd_self": round(dd_self, 4),
                            "peak": round(peak_nav, 3), "shelter_w": round(shelter_w, 3),
                            "risk": "OFF" if risk_off else "ON",
                            "trigger": ("crash" if crash else
                                        "early" if (early_off and not trend_off) else
                                        "trend" if (trend_off and not early_off) else
                                        "both" if (trend_off and early_off) else ""),
                            "gate": round(eff, 2),
                            "er": round(R.loc[dt, "er_gv_20"], 3) if pd.notna(R.loc[dt, "er_gv_20"]) else None,
                            "mkt_dd": round(R.loc[dt, "mkt_dd"], 3) if pd.notna(R.loc[dt, "mkt_dd"]) else None,
                            "accel": round(accel, 4) if pd.notna(accel) else None,
                            "vol_ratio": round(vr, 2) if pd.notna(vr) else None,
                            "gv": round(gv, 3) if pd.notna(gv) else None,
                            "ls": round(ls, 3) if pd.notna(ls) else None,
                            "holdings": "+".join(sel)})

    out = (pd.Series(dict(navs)), pd.DataFrame(logrows),
           np.mean(turns) if turns else 0, ntrade)
    if return_weights:
        W = pd.DataFrame(wrows, index=close.loc[start:end].index)
        return out + (W,)
    return out


def main():
    close = ev.load_panel()
    F, R = build_style_factors(close)
    shelter = load_shelter_price()
    shelter = shelter.reindex(close.index).ffill()   # 对齐交易日

    SEGS = {
        "全区间2020-2026": ("2020-01-02", "2026-11-18"),
        "时间外2020-2023": ("2020-01-02", "2023-11-17"),
        "近三年2023-2026": ("2023-11-19", "2026-11-18"),
        "图片同期2024-2026": ("2024-01-02", "2026-11-18"),
    }

    # 主方案 + 消融对照
    configs = [
        ("风格自适应(完整)", dict(K=2, hedge=0.5, style_tilt=0.5)),
        ("无避险(纯选最强)", dict(K=2, hedge=0.0, style_tilt=0.5)),
        ("无风格倾斜", dict(K=2, hedge=0.5, style_tilt=0.0)),
        ("K1集中", dict(K=1, hedge=0.5, style_tilt=0.5)),
    ]
    allres = []
    for name, kw in configs:
        nav, lg, turn, nt = run_style_adaptive(close, F, R, shelter, **kw)
        rows = []
        for tag, (s, e) in SEGS.items():
            sub = nav.loc[s:e]
            if len(sub) < 20: continue
            m = ev.metrics(sub, name); m["区间"] = tag; m["方案"] = name
            rows.append(m)
        df = pd.DataFrame(rows); allres.append(df)
        log(f"\n--- {name} (换手{turn:.2f} 调仓{nt}次 避险信号触发率{(lg.risk=='OFF').mean()*100:.0f}%) ---")
        log(df[["区间", "累计", "年化", "夏普", "回撤"]].to_string(index=False,
            formatters={"累计": lambda x: f"{x*100:.1f}%", "年化": lambda x: f"{x*100:.1f}%",
                        "回撤": lambda x: f"{x*100:.1f}%"}))
        if name == "风格自适应(完整)":
            nav.to_csv(os.path.join(OUT, "风格自适应_净值.csv"), encoding="utf-8-sig")
            lg.to_csv(os.path.join(OUT, "风格自适应_信号日志.csv"), index=False, encoding="utf-8-sig")

    res = pd.concat(allres, ignore_index=True)
    res.to_csv(os.path.join(OUT, "风格自适应_分段验证.csv"), index=False, encoding="utf-8-sig")
    log("\n[完成] output5/风格自适应_* 已生成")


if __name__ == "__main__":
    main()
