"""上线版本 v1.0 —— 候选B策略（风格自适应 + ER/DD门控 + cooldown回撤断路器）。

候选B = v0.12 推荐配置：
  K=1 / regime_in_score=True / fit_gate=er_dd / gate_floor=0.2 / dd_crash_th=-0.18
  hedge=0.5 / cooldown断路器 cb_dd_start=-0.10 cb_share=1.0 cb_days=20 cb_reset_peak=True
  freq=10 / cost_bps=8 / 全收益指数口径

本脚本只做"固化与发布"：复用现有引擎生成正式产物，不改动任何策略逻辑。
产物落盘 output5/v1/：净值、信号、权重、分段/分年绩效、看板数据JSON、版本配置快照。
"""
import os, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
import evolve as ev
from style_adaptive import run_style_adaptive, load_shelter_price
from style_factors import build_style_factors

V1_DIR = os.path.join(ev.BASE, "output5", "v1")
os.makedirs(V1_DIR, exist_ok=True)

# ===== v1.0 配置快照（候选B）=====
V1_CONFIG = {
    "version": "v1.0",
    "name": "风格自适应动量轮动 + 回撤断路器（候选B）",
    "released": "2026-11-19",
    "data_basis": "全收益指数口径（A500价格指数）",
    "assets": ["沪深300", "中证500", "中证1000", "科创50", "成长100", "价值100", "A500"],
    "shelter_etf": "511010 国债ETF",
    "params": {
        "K": 1, "freq": 10, "cost_bps": 8,
        "hedge": 0.5, "style_tilt": 0.5, "regime_in_score": True,
        "fit_gate": "er_dd", "gate_floor": 0.2, "dd_crash_th": -0.18,
        "cb_mode": "cooldown", "cb_dd_start": -0.10, "cb_share": 1.0,
        "cb_days": 20, "cb_reset_peak": True,
    },
    "execution": "T日收盘出信号，T+1收盘执行，含8bps单边成本，零前视",
    "note": "候选B：近三年回撤改善最全面且ETF实盘期转正；时间外年化不稀释。",
}

SEGS = {
    "全区间2020-2026": ("2020-01-02", "2026-11-18"),
    "时间外2020-2023": ("2020-01-02", "2023-11-17"),
    "近三年2023-2026": ("2023-11-19", "2026-11-18"),
    "图片同期2024-2026": ("2024-01-02", "2026-11-18"),
}


def main():
    close = ev.load_panel()
    F, R = build_style_factors(close)
    shelter = load_shelter_price().reindex(close.index).ffill()
    p = V1_CONFIG["params"]

    # 正式回测（v1.0）
    # 关键：end 显式取数据最新交易日，不沿用引擎默认 ev.END（发布时的硬编码截止日）。
    # 否则每日抓数追加新交易日后，回测仍截在旧日期，看板无法同步更新。
    end_date = close.index[-1]
    nav, lg, turn, nt, W = run_style_adaptive(close, F, R, shelter,
                                              return_weights=True, end=end_date, **p)

    # 基准：全池等权买入持有、沪深300买入持有
    eq = (1 + close.pct_change().fillna(0).mean(axis=1)).cumprod()
    hs300 = close["沪深300"] / close["沪深300"].iloc[0]

    # 回撤序列
    dd = nav / nav.cummax() - 1.0

    # 分段绩效
    seg_rows = []
    for tag, (s, e) in SEGS.items():
        sub = nav.loc[s:e]
        m = ev.metrics(sub, tag); m["区间"] = tag; seg_rows.append(m)
    segdf = pd.DataFrame(seg_rows)

    # 分年收益
    yr_rows = []
    for y in range(2020, 2027):
        sub = nav.loc[f"{y}-01-01":f"{y}-12-31"]
        if len(sub) > 2:
            r = float(sub.iloc[-1] / sub.iloc[0] - 1)
            yr_rows.append({"年份": y, "v1.0收益": r,
                            "等权基准": float(eq.loc[sub.index[-1]] / eq.loc[sub.index[0]] - 1)})
    yeardf = pd.DataFrame(yr_rows)

    # ---- 落盘 ----
    nav.to_csv(os.path.join(V1_DIR, "v1_净值.csv"), encoding="utf-8-sig")
    lg.to_csv(os.path.join(V1_DIR, "v1_信号日志.csv"), index=False, encoding="utf-8-sig")
    W.to_csv(os.path.join(V1_DIR, "v1_持仓权重.csv"), encoding="utf-8-sig")
    segdf.to_csv(os.path.join(V1_DIR, "v1_分段绩效.csv"), index=False, encoding="utf-8-sig")
    yeardf.to_csv(os.path.join(V1_DIR, "v1_分年收益.csv"), index=False, encoding="utf-8-sig")
    json.dump(V1_CONFIG, open(os.path.join(V1_DIR, "v1_配置快照.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    # ---- 看板数据（内嵌用）----
    board = {
        "config": V1_CONFIG,
        "dates": [d.strftime("%Y-%m-%d") for d in nav.index],
        "nav": [round(float(x), 5) for x in nav.values],
        "eq": [round(float(x), 5) for x in eq.reindex(nav.index).values],
        "hs300": [round(float(x), 5) for x in hs300.reindex(nav.index).values],
        "dd": [round(float(x), 5) for x in dd.values],
        "seg": segdf.to_dict("records"),
        "year": yeardf.to_dict("records"),
        "sig_dates": lg["date"].tolist(),
        "sig_shelter": [round(float(x), 3) for x in lg["shelter_w"]],
        "sig_cb": [int(x) for x in (lg["cb_sh"] > 0)],
        "sig_holdings": lg["holdings"].tolist(),
        "meta": {"turn": round(turn, 3), "ntrade": nt, "n_cb": int((lg["cb_sh"] > 0).sum()),
                 "n_sig": len(lg), "avg_shelter": round(float(lg["shelter_w"].mean()), 4)},
    }
    json.dump(board, open(os.path.join(V1_DIR, "v1_看板数据.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))

    # ---- 控制台摘要 ----
    ev.log("\n=== v1.0 上线版本（候选B）绩效 ===")
    ev.log(segdf[["区间", "累计", "年化", "夏普", "回撤"]].to_string(index=False,
        formatters={"累计": lambda x: f"{x*100:.1f}%", "年化": lambda x: f"{x*100:.1f}%",
                    "回撤": lambda x: f"{x*100:.1f}%", "夏普": lambda x: f"{x:.2f}"}))
    ev.log(f"\n换手 {turn:.2f} 调仓 {nt} 次 熔断 {int((lg['cb_sh']>0).sum())} 次 平均国债仓位 {lg['shelter_w'].mean()*100:.1f}%")
    ev.log(f"[完成] v1.0 产物已落盘 output5/v1/（净值/信号/权重/分段/分年/配置/看板数据）")


if __name__ == "__main__":
    main()
