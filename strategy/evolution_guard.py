"""进化学习引擎（监管层）+ 影子台账。

方法论参考（核桃量化《年化超额收益24%的强化学习行业配置策略》2023-09-22）：
  用强化学习框架的"自适应迭代"对抗 因子IC反转 / 模型退化 / 数据滞后；
  状态 State → 动作 Action → 奖励 Reward → 迭代更新，模型需不断评估与进化。

本实现是"参考思想、不要求一致"的**可解释工程落地**（非黑箱 DQN / 非神经网络）：
  - 冠军 Champion = 已上线 v1.0（配置从 v1_配置快照.json 读取），实盘净值不变。
  - 影子挑战者 Challengers = 围绕 v1.0 的若干参数变体，用同一 run_style_adaptive
    独立回测，只记录虚拟净值/绩效，**不执行、不影响冠军**（Champion-Challenger 影子台账）。
  - 进化引擎（监管）：每 EVAL_FREQ 交易日评估一次，仅用截至 t 的已发生数据（零前视）：
      · State  状态：冠军滚动夏普/回撤、核心因子 rank_mom_20 滚动已实现 RankIC、市场 ER。
      · Reward 奖励：各挑战者相对冠军的滚动风险调整超额（夏普差）。
      · 学习更新：EWMA 在线更新每个挑战者的信誉 Q（表格化 Q-learning，alpha 为学习率）。
      · Action 动作：argmax Q 提名"当期最优挑战者"；连续达标才标 PROMOTE_CANDIDATE（仅建议）。
      · 监管预警：因子IC反转、冠军退化、回撤异常 —— 只告警/提名，绝不擅自切换上线策略。
  - 影子台账：逐评估期记录全部 状态/奖励/Q/动作/预警，可审计、可复现。

复用不重写：run_style_adaptive / build_style_factors / load_shelter_price / ev.load_panel / ev.metrics。
不编造：所有净值、绩效、IC、Q 值均由真实回测与真实因子计算得到。
"""
import os, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
import evolve as ev
from style_adaptive import run_style_adaptive, load_shelter_price
from style_factors import build_style_factors

OUT = os.path.join(ev.BASE, "output5", "evolution")
os.makedirs(OUT, exist_ok=True)
log = ev.log

# ---- 引擎超参（显式、可复现）----
EVAL_FREQ   = 20      # 每 20 交易日评估一次
WARMUP      = 250     # 预热：此前不评估（保证奖励窗口与 IC 有足够历史）
REWARD_WIN  = 120     # 奖励/绩效滚动窗口（交易日）
IC_H        = 10      # 因子 RankIC 的前瞻收益天数（仅用已实现配对，零前视）
IC_FREQ     = 10      # IC 采样步长
ALPHA       = 0.30    # EWMA 学习率（Q 更新）
PROMOTE_STREAK = 5    # 连续达标期数才标晋升候选
PROMOTE_EDGE   = 0.08 # 信誉 Q 门槛（滚动夏普超额需持续显著）
PROMOTE_COOL   = 10   # 晋升候选冷却期（评估期数），避免同一趋势反复刷屏
IC_REVERSAL_TH = -0.02  # 滚动 IC 均值低于此值 → 因子反转预警
CHAMP_SHARPE_TH = 0.0   # 冠军滚动夏普低于此值 → 退化预警
CHAMP_MDD_TH    = -0.15 # 冠军滚动回撤低于此值 → 回撤预警


def load_champion_config():
    """冠军配置从上线快照读取，保证与 v1.0 逐项一致。"""
    snap = json.load(open(os.path.join(ev.BASE, "output5", "v1", "v1_配置快照.json"), encoding="utf-8"))
    return dict(snap["params"])


def build_challengers(champ):
    """影子挑战者 = 围绕 v1.0 的单参数变体（真实可回测，非编造）。"""
    def variant(**over):
        d = dict(champ); d.update(over); return d
    return {
        "冠军v1.0":      variant(),                                  # Champion（基准，也作影子记录）
        "断路器提前":     variant(cb_dd_start=-0.06),                # 更早退守
        "断路器延后":     variant(cb_dd_start=-0.14),                # 更晚退守
        "半仓退守":       variant(cb_share=0.5),                     # 熔断期只退守半仓（真实有效、全区间跑赢）
        "双持有K2":       variant(K=2),                              # 分散持有两只
        "关闭断路器":     variant(cb_dd_start=None),                 # 退回 v0.11（无断路器）
    }


def run_all(close, F, R, sh, configs):
    """对每个配置独立回测，返回对齐的日频净值 DataFrame。"""
    navs = {}
    for name, cfg in configs.items():
        nav = run_style_adaptive(close, F, R, sh, **cfg)[0]
        navs[name] = nav
    return pd.DataFrame(navs)


def win_metrics(nav_win):
    """滚动窗口风险调整指标（夏普年化、最大回撤、区间收益）——只用窗口内数据。"""
    r = nav_win.pct_change().dropna()
    if len(r) < 10:
        return dict(sharpe=np.nan, mdd=np.nan, ret=np.nan)
    sd = r.std()
    sharpe = r.mean() / sd * np.sqrt(ev.TD) if sd > 0 else 0.0
    mdd = float((nav_win / nav_win.cummax() - 1).min())
    ret = float(nav_win.iloc[-1] / nav_win.iloc[0] - 1)
    return dict(sharpe=float(sharpe), mdd=mdd, ret=ret)


def realized_rankic(close, F, t, h=IC_H, freq=IC_FREQ, win=REWARD_WIN, max_back=WARMUP):
    """截至评估日 t 的**已实现** RankIC 均值（零前视）：
    只用 d+h <= t 的 (因子值@d, 未来h日收益@d) 配对，全部信息在 t 前已发生。
    返回 (ic_mean, ic_pos_ratio, n_samples)。
    """
    dates = close.index
    pos = dates.get_loc(t)
    lo = max(0, pos - win)
    fac = F["rank_mom_20"]
    fwd = close.shift(-h) / close - 1.0          # 未来 h 日收益（按日期对齐）
    ics = []
    for d in dates[lo:pos + 1:freq]:
        # 保证 d+h <= t：配对收益在评估日之前已完全实现
        if dates.get_loc(d) + h > pos:
            continue
        x = fac.loc[d]
        y = fwd.loc[d]
        common = x.dropna().index.intersection(y.dropna().index)
        if len(common) < 4:
            continue
        ic = x.loc[common].corr(y.loc[common], method="spearman")
        if pd.notna(ic):
            ics.append(float(ic))
    if not ics:
        return (np.nan, np.nan, 0)
    arr = np.array(ics)
    return (float(arr.mean()), float((arr > 0).mean()), len(arr))


def main():
    close = ev.load_panel()
    F, R = build_style_factors(close)
    sh = load_shelter_price().reindex(close.index).ffill()

    champ = load_champion_config()
    configs = build_challengers(champ)
    names = list(configs.keys())
    challengers = [n for n in names if n != "冠军v1.0"]

    log("=== 影子挑战者独立回测 ===")
    navs = run_all(close, F, R, sh, configs)
    for n in names:
        log(f"  {n:<12} 末值 {navs[n].iloc[-1]:.4f}")

    # 硬校验：冠军净值 == 上线 v1_净值.csv（逐日一致，误差 < 1e-9）
    v1 = pd.read_csv(os.path.join(ev.BASE, "output5", "v1", "v1_净值.csv"), index_col=0).iloc[:, 0]
    v1.index = pd.to_datetime(v1.index)
    champ_diff = float((navs["冠军v1.0"] - v1).abs().max())
    log(f"\n[兼容校验] 冠军 vs v1_净值.csv 逐日最大差 {champ_diff:.2e}")
    assert champ_diff < 1e-9, "冠军净值与上线版本不一致，影子台账不成立"

    # 落盘影子净值
    navs.to_csv(os.path.join(OUT, "影子净值.csv"), encoding="utf-8-sig")

    # ---- 进化引擎：滚动评估 ----
    dates = close.index
    Q = {n: 0.0 for n in challengers}          # 信誉初值
    streak = {n: 0 for n in challengers}        # 连续领先计数
    cool = 0                                    # 晋升候选冷却计数（评估期）
    eval_positions = list(range(WARMUP, len(dates), EVAL_FREQ))
    ledger, events, q_hist = [], [], []

    for pos in eval_positions:
        t = dates[pos]
        w0 = max(0, pos - REWARD_WIN)
        win_sl = slice(w0, pos + 1)

        # State：冠军滚动绩效、已实现因子 IC、市场 ER
        cm = win_metrics(navs["冠军v1.0"].iloc[win_sl])
        ic_mean, ic_pos, ic_n = realized_rankic(close, F, t)
        er = R["er_gv_20"].loc[t] if pd.notna(R["er_gv_20"].loc[t]) else np.nan

        # Reward：各挑战者相对冠军的滚动夏普超额
        rewards = {}
        for n in challengers:
            m = win_metrics(navs[n].iloc[win_sl])
            rewards[n] = (m["sharpe"] - cm["sharpe"]) if pd.notna(m["sharpe"]) and pd.notna(cm["sharpe"]) else 0.0

        # 学习更新：EWMA 在线更新信誉 Q
        for n in challengers:
            Q[n] = (1 - ALPHA) * Q[n] + ALPHA * rewards[n]

        # Action：argmax Q 提名
        leader = max(challengers, key=lambda k: Q[k])
        for n in challengers:
            streak[n] = streak[n] + 1 if (n == leader and Q[n] > PROMOTE_EDGE) else 0

        # 监管判定（多标签，可叠加）
        alerts = []
        if pd.notna(ic_mean) and ic_mean < IC_REVERSAL_TH:
            alerts.append("因子IC反转")
        if pd.notna(cm["sharpe"]) and cm["sharpe"] < CHAMP_SHARPE_TH:
            alerts.append("冠军退化")
        if pd.notna(cm["mdd"]) and cm["mdd"] < CHAMP_MDD_TH:
            alerts.append("回撤预警")

        promoted = None
        if cool > 0:
            cool -= 1
        if (streak[leader] >= PROMOTE_STREAK and Q[leader] > PROMOTE_EDGE
                and "冠军退化" not in alerts and cool == 0):
            promoted = leader
            cool = PROMOTE_COOL
        if promoted:
            alerts.append("晋升候选:" + promoted)
            events.append(dict(date=str(t.date()), type="PROMOTE_CANDIDATE",
                               name=promoted, detail=f"连续{streak[leader]}期信誉领先 Q={Q[leader]:.3f}"))
        for a in [x for x in alerts if x in ("因子IC反转", "冠军退化", "回撤预警")]:
            events.append(dict(date=str(t.date()), type=a,
                               detail=f"IC均值{ic_mean:.3f} 冠军夏普{cm['sharpe']:.2f} 回撤{cm['mdd']:.1%}"))

        row = dict(date=str(t.date()), window=f"{dates[w0].date()}~{t.date()}",
                   champ_sharpe=round(cm["sharpe"], 4) if pd.notna(cm["sharpe"]) else None,
                   champ_mdd=round(cm["mdd"], 4) if pd.notna(cm["mdd"]) else None,
                   champ_ret=round(cm["ret"], 4) if pd.notna(cm["ret"]) else None,
                   ic_mean=round(ic_mean, 4) if pd.notna(ic_mean) else None,
                   ic_pos=round(ic_pos, 3) if pd.notna(ic_pos) else None,
                   ic_n=ic_n, er=round(float(er), 4) if pd.notna(er) else None,
                   leader=leader, leader_Q=round(Q[leader], 4),
                   promoted=promoted or "",
                   alerts="|".join(alerts) if alerts else "正常")
        for n in challengers:
            row["rew_" + n] = round(rewards[n], 4)
            row["Q_" + n] = round(Q[n], 4)
        ledger.append(row)
        q_hist.append(dict(date=str(t.date()), **{("Q_" + n): round(Q[n], 4) for n in challengers}))

    ldf = pd.DataFrame(ledger)
    edf = pd.DataFrame(events)
    qdf = pd.DataFrame(q_hist)
    ldf.to_csv(os.path.join(OUT, "影子台账.csv"), index=False, encoding="utf-8-sig")
    edf.to_csv(os.path.join(OUT, "监管事件.csv"), index=False, encoding="utf-8-sig")
    qdf.to_csv(os.path.join(OUT, "信誉Q演化.csv"), index=False, encoding="utf-8-sig")

    # ---- 摘要 ----
    m_all = {n: ev.metrics(navs[n], n) for n in names}
    n_promote = int(sum(1 for e in events if e["type"] == "PROMOTE_CANDIDATE"))
    n_icrev = int(sum(1 for e in events if e["type"] == "因子IC反转"))
    n_decay = int(sum(1 for e in events if e["type"] == "冠军退化"))
    final_leader = ldf.iloc[-1]["leader"]
    # 全区间谁真的跑赢冠军（诚实）
    champ_ann = m_all["冠军v1.0"]["年化"]
    better = [n for n in challengers if m_all[n]["年化"] > champ_ann]

    summary = dict(
        engine=dict(EVAL_FREQ=EVAL_FREQ, WARMUP=WARMUP, REWARD_WIN=REWARD_WIN,
                    IC_H=IC_H, ALPHA=ALPHA, PROMOTE_STREAK=PROMOTE_STREAK,
                    PROMOTE_EDGE=PROMOTE_EDGE),
        champion_diff=champ_diff,
        n_eval=len(ledger), n_events=len(events),
        n_promote=n_promote, n_icrev=n_icrev, n_decay=n_decay,
        final_leader=final_leader,
        final_Q={n: round(Q[n], 4) for n in challengers},
        range=[str(dates[0].date()), str(dates[-1].date())],
        metrics={n: {k: (round(float(v), 4) if isinstance(v, (int, float, np.floating)) and pd.notna(v) else v)
                     for k, v in m.items()} for n, m in m_all.items()},
        better_than_champion=better,
        eval_first=ledger[0]["date"], eval_last=ledger[-1]["date"],
    )
    json.dump(summary, open(os.path.join(OUT, "进化摘要.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    # 报告用结构化数据（干净、无 NaN）
    report = dict(
        summary=summary,
        dates=[str(d.date()) for d in dates],
        nav={n: [round(float(v), 5) for v in navs[n]] for n in names},
        ledger=ledger, events=events, q_hist=q_hist,
        challengers=challengers, names=names,
    )
    json.dump(report, open(os.path.join(OUT, "进化看板数据.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))

    # ---- 控制台汇报（一行中文关键指标 + 动作）----
    log("\n" + "=" * 90)
    log(f"评估期 {len(ledger)} 期（{ledger[0]['date']}~{ledger[-1]['date']}）| "
        f"晋升候选 {n_promote} 次 | IC反转预警 {n_icrev} 次 | 冠军退化预警 {n_decay} 次 | "
        f"末期领先 {final_leader} | 全区间跑赢冠军的挑战者 {len(better)} 个")
    log(f"冠军全区间年化 {champ_ann*100:.1f}%；" +
        ("无挑战者全区间跑赢" if not better else "跑赢者: " + "/".join(better)))
    log("[结论] 监管层仅记录/预警/提名，未切换上线 v1.0；冠军净值逐日一致。")
    log(f"[完成] output5/evolution/：影子净值.csv / 影子台账.csv / 监管事件.csv / "
        f"信誉Q演化.csv / 进化摘要.json / 进化看板数据.json")


if __name__ == "__main__":
    main()
