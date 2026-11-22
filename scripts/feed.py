# -*- coding: utf-8 -*-
"""
同源接口构建器（feed）：把 strategy 的 v1 回测输出转换为看板同源接口 data/*.json。

设计原则：
  - 唯一转换器：看板 index.html 只 fetch data/ 接口，不含任何硬编码数据。
  - 数值全部来自 v1 真实回测落盘文件（净值/信号/持仓/分段/分年/归因），不编造。
  - 复用 prepare_dashboard_data 的归因与统计逻辑（同源重算），区间口径严格一致。

生成接口：
  meta.json / nav.json / signal.json / holdings.json / attribution.json / audit.json
"""
import os
import sys
import json
import hashlib
import datetime as dt
import warnings
warnings.filterwarnings('ignore')

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRAT = os.path.join(BASE, 'strategy')
V1 = os.path.join(STRAT, 'output5', 'v1')
DATA = os.path.join(BASE, 'data')
sys.path.insert(0, STRAT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import evolve as ev
from style_adaptive import load_shelter_price

SCHEMA = 'industry-rotation-cta-nav/v1'
TZ = dt.timezone(dt.timedelta(hours=8))
LABEL = {'沪深300': '沪深300', '中证500': '中证500', '中证1000': '中证1000',
         '科创50': '科创50', '成长100': '成长100', '价值100': '价值100',
         'A500': 'A500', 'SHELTER': '国债ETF'}
REQUIRED = ['meta.json', 'nav.json', 'signal.json', 'holdings.json',
            'attribution.json', 'evolution.json', 'audit.json', 'rebalances.CSV']

EVOL = os.path.join(STRAT, 'output5', 'evolution')


def r(x, n=6):
    try:
        v = float(x)
        return round(v, n) if np.isfinite(v) else None
    except Exception:
        return None


def jwrite(name, obj):
    with open(os.path.join(DATA, name), 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))


def read_v1():
    nav = pd.read_csv(os.path.join(V1, 'v1_净值.csv'), index_col=0).iloc[:, 0]
    nav.index = pd.to_datetime(nav.index)
    lg = pd.read_csv(os.path.join(V1, 'v1_信号日志.csv'))
    W = pd.read_csv(os.path.join(V1, 'v1_持仓权重.csv'), index_col=0)
    W.index = pd.to_datetime(W.index)
    seg = pd.read_csv(os.path.join(V1, 'v1_分段绩效.csv'))
    yr = pd.read_csv(os.path.join(V1, 'v1_分年收益.csv'))
    return nav, lg, W, seg, yr


def build_attribution(nav, lg, W):
    """复用 engine_attribution 逻辑：执行日成本、非执行日 W.shift(1)*RET、复利对账。
    关键：一切序列以 nav.index 为准对齐——原始行情可能比净值多最新几日，
    必须 reindex 到 nav 时间轴，否则 contrib/is_exec 长度不一致会崩。"""
    close = ev.load_panel().reindex(nav.index)
    sh = load_shelter_price().reindex(nav.index).ffill()
    idx = close.index
    exec_dates = set()
    for d in pd.to_datetime(lg['date']):
        pos = idx.get_loc(d) if d in idx else -1
        if 0 <= pos + 1 < len(idx):
            exec_dates.add(idx[pos + 1])
    RET = close.pct_change()
    RET['SHELTER'] = sh.pct_change()
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
        yd = yd[1:]
        vals = [float(contrib.loc[yd, c].sum()) for c in W.columns]
        tc = float(cost.loc[yd].sum())
        arith = sum(vals) + tc
        geo = float((1 + navr.loc[yd]).prod() - 1)
        rows = dict(zip(asset_cols, vals))
        leader = max(asset_cols, key=lambda k: rows[k])
        years.append({'year': y, 'contrib': [r(v) for v in vals], 'cost': r(tc),
                      'arith': r(arith), 'compound': r(geo - arith),
                      'strategy': r(geo), 'leader': leader})
    total = [r(float(contrib[c].sum())) for c in W.columns]
    return {'assets': asset_cols, 'years': years, 'total': total,
            'total_cost': r(float(cost.sum()))}


def build_evolution():
    """影子账户（旁路监管）接口：复用 evolution_guard 的真实落盘产物，字段延展。
    不编造：净值/台账/Q/事件/摘要全部来自 strategy/output5/evolution/ 真实回测。"""
    src = os.path.join(EVOL, '进化看板数据.json')
    if not os.path.exists(src):
        return {'available': False}
    d = json.load(open(src, encoding='utf-8'))
    s = d['summary']
    eng = s['engine']
    led = d['ledger'][-1] if d.get('ledger') else {}
    events = d.get('events', [])
    champ = '冠军v1.0'
    # --- 状态 pills 字段延展（参考 mafc-nav，值全部来自真实数据）---
    types = [e.get('type', '') for e in events]
    last_eval = s.get('eval_last', '')
    # 降级状态：最近一期预警类型映射
    alerts = str(led.get('alerts', ''))
    if '回撤预警' in alerts or '冠军退化' in types[-3:]:
        degrade = 'DEGRADED'
    elif '因子IC反转' in alerts:
        degrade = 'WATCH'
    else:
        degrade = 'NORMAL'
    # 实盘观察月数：影子均为历史回灌，无实盘，如实为 0
    live_months = 0
    pills = [
        {'k': '版本', 'v': 's001', 'cls': ''},
        {'k': '状态', 'v': 'NO_NEW_SAMPLE' if not last_eval else 'EVALUATING', 'cls': 'ok'},
        {'k': '降级状态', 'v': degrade, 'cls': 'warn' if degrade != 'NORMAL' else ''},
        {'k': '有效参数', 'v': s.get('final_leader', 'fixed'), 'cls': ''},
        {'k': '本折跑赢', 'v': '是' if s.get('better_than_champion') else '否',
         'cls': 'ok' if s.get('better_than_champion') else ''},
        {'k': '连续跑赢折数', 'v': str(int(s.get('n_promote', 0))), 'cls': ''},
        {'k': '实盘观察', 'v': str(live_months) + ' 月', 'cls': ''},
        {'k': '样本类型', 'v': 'historical_dry_run', 'cls': 'warn'},
    ]
    # --- 样本外绩效（终值口径，来自 metrics）---
    met = s.get('metrics', {})
    def mm(name):
        v = met.get(name, {})
        return {'cagr': r(v.get('年化')), 'sharpe': r(v.get('夏普')),
                'mdd': r(v.get('回撤')), 'calmar': r(v.get('Calmar')),
                'total': r(v.get('累计'))}
    # --- 演练月数：净值轴跨度 ---
    dates_nav = d.get('dates', [])
    months = 0
    if len(dates_nav) >= 2:
        a, b = dates_nav[0][:7], dates_nav[-1][:7]
        ya, ma = int(a[:4]), int(a[5:]); yb, mb = int(b[:4]), int(b[5:])
        months = (yb - ya) * 12 + (mb - ma)
    # --- 解锁降级门槛（引擎超参）---
    gain = {'eval_freq': eng.get('EVAL_FREQ'), 'warmup': eng.get('WARMUP'),
            'reward_win': eng.get('REWARD_WIN'), 'alpha': eng.get('ALPHA'),
            'promote_streak': eng.get('PROMOTE_STREAK'), 'promote_edge': eng.get('PROMOTE_EDGE')}
    return {
        'available': True,
        'as_of': last_eval,
        'range': s.get('range', []),
        'pills': pills,
        'engine': gain,
        'n_eval': s.get('n_eval'), 'n_events': s.get('n_events'),
        'n_promote': s.get('n_promote'), 'n_icrev': s.get('n_icrev'),
        'n_decay': s.get('n_decay'),
        'final_leader': s.get('final_leader'),
        'final_Q': {k: r(v, 4) for k, v in s.get('final_Q', {}).items()},
        'better_than_champion': s.get('better_than_champion', []),
        'champion_diff': s.get('champion_diff'),
        'names': d.get('names', []),
        'dates': dates_nav,
        'nav': d.get('nav', {}),
        'metrics': {name: mm(name) for name in d.get('names', [])},
        'q_hist': d.get('q_hist', []),
        'events': events,
        'months': months,
        'degrade_gate': '连续 ' + str(eng.get('PROMOTE_STREAK')) + ' 折跑赢且 Q 超额 ≥ ' + str(eng.get('PROMOTE_EDGE')),
        'honest': ('影子挑战者均为 v1.0 参数邻域变体，非独立新模型；仅提名不切换，冠军净值逐日不变。'
                   '全部为历史回灌演练(historical_dry_run)，非实盘记录，不代表未来收益。'),
    }


def build(sync_info=None):
    os.makedirs(DATA, exist_ok=True)
    nav, lg, W, seg, yr = read_v1()
    z800 = pd.read_csv(os.path.join(STRAT, 'data', 'raw', 'pool_中证800.csv'),
                       parse_dates=['date']).set_index('date')['close'].reindex(nav.index).ffill()

    nav_n = nav / nav.iloc[0]
    z800_n = z800 / z800.iloc[0]
    dd = nav / nav.cummax() - 1.0

    # ---- nav.json ----
    dates = [d.strftime('%Y-%m-%d') for d in nav.index]
    # 月度收益矩阵
    mret = nav.resample('ME').last().pct_change()
    mret.iloc[0] = nav.resample('ME').last().iloc[0] / nav.iloc[0] - 1
    heat = {}
    for y in sorted(set(d.year for d in mret.index)):
        vals = [None] * 12
        for d, v in mret.items():
            if d.year == y:
                vals[d.month - 1] = r(v, 5)
        heat[str(y)] = vals
    allm = [v for vs in heat.values() for v in vs if v is not None]
    nav_obj = {
        'dates': dates,
        'strategy': [r(x, 5) for x in nav_n.values],
        'benchmark': [r(x, 5) for x in z800_n.values],
        'drawdown': [r(x, 5) for x in dd.values],
        'monthly': heat,
        'monthly_winrate': r(sum(1 for v in allm if v > 0) / len(allm), 4) if allm else None,
        'segments': [{'name': str(row['区间']), 'cagr': r(row['年化'], 4),
                      'sharpe': r(row['夏普'], 4), 'mdd': r(row['回撤'], 4),
                      'calmar': r(row['Calmar'], 4)}
                     for _, row in seg.iterrows()],
        'yearly': [{'year': int(row['年份']), 'strategy': r(row['v1.0收益'], 4),
                    'benchmark': r(row['等权基准'], 4)} for _, row in yr.iterrows()],
    }
    # 分年完整统计（策略 mdd/vol/sharpe/calmar + 中证800 基准 + 超额），供看板年度表。
    # 与 v1 分年收益口径严格一致：年内首末净值。
    yfull = []
    for y in sorted(set(d.year for d in nav.index)):
        sub = nav.loc[f'{y}-01-01':f'{y}-12-31']
        zsub = z800.loc[f'{y}-01-01':f'{y}-12-31']
        if len(sub) < 2:
            continue
        ret = sub.pct_change().dropna()
        tot = float(sub.iloc[-1] / sub.iloc[0] - 1)
        mdd = float((sub / sub.cummax() - 1).min())
        vol = float(ret.std() * np.sqrt(252)) if len(ret) > 1 else 0.0
        shp = float(ret.mean() / ret.std() * np.sqrt(252)) if len(ret) > 1 and ret.std() > 0 else 0.0
        ztot = float(zsub.iloc[-1] / zsub.iloc[0] - 1) if len(zsub) > 1 else 0.0
        yfull.append({'year': y, 'ret': r(tot), 'z800': r(ztot), 'excess': r(tot - ztot),
                      'mdd': r(mdd), 'vol': r(vol), 'sharpe': r(shp),
                      'calmar': r(tot / abs(mdd)) if mdd < 0 else 0.0})
    nav_obj['year_full'] = yfull
    jwrite('nav.json', nav_obj)

    # ---- holdings.json（当前持仓 + 最近调仓）----
    last_w = W.iloc[-1]
    holdings = [{'asset': LABEL.get(c, c), 'weight': r(float(last_w[c]), 4)}
                for c in W.columns if float(last_w[c]) > 0]
    # 完整调仓记录（全部信号日），字段与 v1_信号日志.csv 同源；最近记录在前展示时由看板倒序
    # 关键：signal 日为 T，实际成交在 T+1（数据轴上的下一个交易日，非日历日）
    trade_dates = list(nav.index)
    tpos = {d: i for i, d in enumerate(trade_dates)}
    def eff_date_of(ds):
        """信号日 T 在数据轴上的下一个交易日（T+1 成交日）"""
        try:
            d = pd.Timestamp(ds)
        except Exception:
            return ''
        i = tpos.get(d)
        return trade_dates[i + 1].strftime('%Y-%m-%d') if (i is not None and i + 1 < len(trade_dates)) else ''

    def target_desc_of(hld, sw):
        """精确目标描述：区分纯风格 / 风格+国债按比例 / 100%国债"""
        sw = float(sw or 0)
        eq = 1 - sw
        if sw <= 0.0005:
            return (hld or '—') + ' 100%'
        if sw >= 0.9995:
            return '国债ETF 100%'
        return (hld or '风格') + ' ' + str(int(round(eq * 100))) + '% + 国债 ' + str(int(round(sw * 100))) + '%'

    def actual_of(eff):
        """生效日实际持仓（从 W 读取真实权重，用于核对目标是否落地）"""
        if not eff:
            return ''
        try:
            row = W.loc[pd.Timestamp(eff)]
        except Exception:
            return ''
        parts = []
        for c in W.columns:
            v = float(row[c])
            if v > 0.005:
                parts.append(LABEL.get(c, c) + ' ' + str(int(round(v * 100))) + '%')
        return ' + '.join(parts)

    rebalances = []
    for _, row in lg.iterrows():
        hld = str(row['holdings']) if 'holdings' in row else ''
        sw = r(row['shelter_w'], 3)
        eff = eff_date_of(row['date'])
        rebalances.append({'date': str(row['date']), 'eff_date': eff,
                           'trigger': str(row['trigger']),
                           'risk': str(row['risk']), 'gate': r(row['gate'], 3),
                           'mkt_dd': r(row['mkt_dd'], 3), 'shelter_w': sw,
                           'cb_sh': r(row['cb_sh'], 3), 'holdings': hld,
                           'target_desc': target_desc_of(hld, sw), 'actual': actual_of(eff),
                           'dd_self': r(row['dd_self'], 3), 'er': r(row['er'], 3),
                           'accel': r(row['accel'], 5), 'vol_ratio': r(row['vol_ratio'], 3),
                           'peak': r(row['peak'], 4)})
    # 完整记录导出为 CSV（用户指定的 rebalances.CSV）
    rb_cols = ['date', 'eff_date', 'trigger', 'risk', 'gate', 'mkt_dd', 'dd_self', 'er',
               'accel', 'vol_ratio', 'shelter_w', 'cb_sh', 'peak', 'holdings',
               'target_desc', 'actual']
    with open(os.path.join(DATA, 'rebalances.CSV'), 'w', encoding='utf-8-sig', newline='') as f:
        import csv as _csv
        wr = _csv.writer(f)
        zh = {'date': '信号日T', 'eff_date': '生效日T+1', 'trigger': '触发类型', 'risk': '风险状态',
              'gate': '门控', 'mkt_dd': '市场回撤', 'dd_self': '自身回撤', 'er': '效率比ER',
              'accel': '加速度', 'vol_ratio': '波动比', 'shelter_w': '避险仓位',
              'cb_sh': '断路器份额', 'peak': '净值高点', 'holdings': '风格信号',
              'target_desc': '目标描述', 'actual': '生效日实际持仓'}
        wr.writerow([zh[c] for c in rb_cols])
        for rec in rebalances:
            wr.writerow([rec.get(c, '') for c in rb_cols])
    holdings_obj = {
        'as_of': str(W.index[-1].date()),
        'positions': holdings,
        'equity_weight': r(sum(float(last_w[c]) for c in W.columns if c != 'SHELTER'), 4),
        'shelter_weight': r(float(last_w.get('SHELTER', 0)), 4),
        'rebalances': rebalances,
    }
    jwrite('holdings.json', holdings_obj)

    # ---- signal.json（最新信号读数 + 信号定义）----
    last_sig = lg.iloc[-1]
    signal_obj = {
        'as_of': str(pd.to_datetime(last_sig['date']).date()),
        'current': {
            'trigger': str(last_sig['trigger']), 'risk': str(last_sig['risk']),
            'gate': r(last_sig['gate'], 3), 'er': r(last_sig['er'], 3),
            'mkt_dd': r(last_sig['mkt_dd'], 3), 'accel': r(last_sig['accel'], 5),
            'vol_ratio': r(last_sig['vol_ratio'], 3), 'dd_self': r(last_sig['dd_self'], 3),
        },
        'rules': [
            {'name': '动量轮动', 'rule': '每10个交易日按综合动量得分选最强1个宽基(K=1)，T+1收盘执行'},
            {'name': '风格适配门控', 'rule': 'er_dd门控：ER流畅度+回撤双因子，gate_floor=0.2，深跌时gate→0不押风格'},
            {'name': 'Momentum Crash过滤', 'rule': 'dd_crash_th=-0.18，个股/风格 crash 时剔除信号'},
            {'name': '回撤断路器(cooldown)', 'rule': '自身净值回撤≤-10%→满仓国债20日→强制回补并重置高水位'},
            {'name': '避险资产', 'rule': '退守标的=国债ETF 511010(绝对避险)，hedge=0.5基础对冲仓位'},
        ],
    }
    jwrite('signal.json', signal_obj)

    # ---- attribution.json ----
    attr = build_attribution(nav, lg, W)
    jwrite('attribution.json', attr)

    # ---- evolution.json（影子账户旁路监管）----
    jwrite('evolution.json', build_evolution())

    # ---- meta.json ----
    fp = hashlib.md5((dates[-1] + '|' + str(len(dates)) + '|' + r(nav_n.iloc[-1], 5).__str__()).encode()).hexdigest()[:16]
    # 独立运行 feed.py（未传 sync_info）时保留已有 sync，避免抹掉巡检依赖的 last_sync
    if sync_info is None:
        prev_meta_path = os.path.join(DATA, 'meta.json')
        if os.path.exists(prev_meta_path):
            try:
                sync_info = json.load(open(prev_meta_path, encoding='utf-8')).get('sync', {})
            except Exception:
                sync_info = {}
    meta = {
        'schema': SCHEMA,
        'name': '行业轮动增强版 · 风格自适应动量轮动 v1.0',
        'version': 'v1.0',
        'start': dates[0], 'end': dates[-1], 'bars': len(dates),
        'as_of': dates[-1],
        'data_fingerprint': fp,
        'price_convention': '宽基用全收益指数(沪深300/500/1000 H系列, 价值/成长100 国证480系列); 科创50/A500/中证800用价格指数; 国债用ETF 511010收盘',
        'params': {'K': 1, 'freq': 10, 'cost_bps': 8, 'hedge': 0.5,
                   'fit_gate': 'er_dd', 'gate_floor': 0.2, 'dd_crash_th': -0.18,
                   'cb_mode': 'cooldown', 'cb_dd_start': -0.10, 'cb_share': 1.0, 'cb_days': 20},
        'publish': 'data/ 同源发布目录，静态页 fetch(no-store) 读取，页面无需重建',
        'sync': sync_info or {},
    }
    jwrite('meta.json', meta)

    # ---- audit.json ----
    audit_path = os.path.join(DATA, 'audit.json')
    audit = {'runs': []}
    if os.path.exists(audit_path):
        try:
            audit = json.load(open(audit_path, encoding='utf-8'))
        except Exception:
            pass
    run = {'run_id': dt.datetime.now(TZ).isoformat(timespec='seconds'),
           'data_fp': fp, 'bars': len(dates), 'as_of': dates[-1],
           'status': (sync_info or {}).get('status', 'ok')}
    audit['runs'].insert(0, run)
    audit['runs'] = audit['runs'][:60]
    jwrite('audit.json', audit)

    return {'status': 'ok', 'fp': fp, 'as_of': dates[-1], 'bars': len(dates),
            'files': REQUIRED}


if __name__ == '__main__':
    res = build()
    print('[feed] 生成同源接口:', ', '.join(res['files']))
    print(f'[feed] 指纹 {res["fp"]} · 数据截至 {res["as_of"]} · {res["bars"]} 交易日')
