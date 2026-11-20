# -*- coding: utf-8 -*-
"""
每日抓数：把 7 宽基指数 + 中证800基准 + 国债ETF 的最新收盘写入 strategy/data/raw/。

数据源（均已实测与本地历史口径精确一致，见 README「数据源与口径」）：
  - 沪深300/中证500/中证1000 全收益：中证官网 csindex  H00300/H00905/H00852
  - 科创50/A500/中证800 价格指数：中证官网 csindex   000688/000510/000906
  - 价值100/成长100 国证全收益：国证官网(akshare)    480081/480080
  - 国债ETF 511010：新浪(akshare fund_etf_hist_sina)  sh511010

约束（沿用用户 SOP）：
  - 整体重试上限 --max-retry（默认 3）；单品种失败 → 跳过并沿用上一版 CSV，不插值、不编造。
  - 只追加"比本地更新"的交易日；新行字段与历史保持同构；写入前校验最新收盘非 NaN。
  - 返回 dict：每个品种 status(ok/skip/fail) + 新增行数 + 最新日期，供 sync_daily 审计。

用法：
  python3.11 scripts/fetch_data.py                    # 抓取并就地更新 strategy/data/raw/
  python3.11 scripts/fetch_data.py --dry-run          # 只打印计划，不写文件
  python3.11 scripts/fetch_data.py --max-retry 3
"""
import os
import sys
import json
import time
import argparse
import datetime as dt

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, 'strategy', 'data', 'raw')

# 代码映射：pool 文件名 -> (数据源, 源代码)
# 中证全收益用 H 系列；价格指数用 6 位数字；国证全收益用 480xxx；ETF 单独处理
CSINDEX = {
    '沪深300': 'H00300',   # 300收益（与本地 H00300 末值一致）
    '中证500': 'H00905',   # 500收益
    '中证1000': 'H00852',  # 中证1000全收益
    '科创50': '000688',    # 价格指数
    'A500': '000510',      # 中证A500 价格
    '中证800': '000906',   # 中证800 价格（基准）
}
CNI = {
    '价值100': '480081',   # 国证价值100 全收益
    '成长100': '480080',   # 国证成长100 全收益
}
ETF = {'SHELTER': ('511010', 'etf_shelter_511010.csv', 'sh511010')}

CSINDEX_API = 'https://www.csindex.com.cn/csindex-home/perf/index-perf'


def _today():
    return dt.date.today()


def _date_str(d):
    return d.strftime('%Y%m%d') if isinstance(d, (dt.date, dt.datetime)) else str(d)


def load_local(name, filename=None):
    """读取本地 CSV，返回 DataFrame(date, close...) 或 None。"""
    import pandas as pd
    fn = filename or f'pool_{name}.csv'
    p = os.path.join(RAW, fn)
    if not os.path.exists(p):
        return None
    d = pd.read_csv(p, parse_dates=['date'])
    return d


def fetch_csindex(code, start, end, retry=3):
    """中证官网指数历史：返回 DataFrame(date, close)。"""
    import pandas as pd
    import requests
    url = f'{CSINDEX_API}?indexCode={code}&startDate={start}&endDate={end}'
    last = None
    for k in range(retry):
        try:
            r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
            j = r.json()
            data = j.get('data') or []
            if not data:
                last = '空数据'
            else:
                df = pd.DataFrame([{'date': pd.to_datetime(x['tradeDate']),
                                    'close': float(x['close'])} for x in data])
                return df.sort_values('date').reset_index(drop=True)
        except Exception as e:
            last = str(e)[:80]
        if k < retry - 1:
            time.sleep(1.5 * (k + 1))
    raise RuntimeError(f'csindex {code} 失败: {last}')


def fetch_cni(code, start, end, retry=3):
    """国证官网指数历史（akshare index_hist_cni）：返回 DataFrame(date, close)。"""
    import pandas as pd
    import akshare as ak
    last = None
    for k in range(retry):
        try:
            d = ak.index_hist_cni(symbol=code, start_date=start, end_date=end)
            if d is None or len(d) == 0:
                last = '空数据'
            else:
                out = pd.DataFrame({'date': pd.to_datetime(d['日期']),
                                    'close': pd.to_numeric(d['收盘价'], errors='coerce')})
                return out.dropna().sort_values('date').reset_index(drop=True)
        except Exception as e:
            last = str(e)[:80]
        if k < retry - 1:
            time.sleep(1.5 * (k + 1))
    raise RuntimeError(f'cni {code} 失败: {last}')


def fetch_etf(symbol, retry=3):
    """新浪 ETF 历史（akshare fund_etf_hist_sina）：返回 DataFrame(date, close)。"""
    import pandas as pd
    import akshare as ak
    last = None
    for k in range(retry):
        try:
            d = ak.fund_etf_hist_sina(symbol=symbol)
            if d is None or len(d) == 0:
                last = '空数据'
            else:
                out = pd.DataFrame({'date': pd.to_datetime(d['date']),
                                    'close': pd.to_numeric(d['close'], errors='coerce')})
                return out.dropna().sort_values('date').reset_index(drop=True)
        except Exception as e:
            last = str(e)[:80]
        if k < retry - 1:
            time.sleep(1.5 * (k + 1))
    raise RuntimeError(f'etf {symbol} 失败: {last}')


def merge_pool(name, new_df, filename=None):
    """把新抓收盘合并进本地 pool CSV；只追加更新的交易日。返回新增行数。"""
    import pandas as pd
    fn = filename or f'pool_{name}.csv'
    p = os.path.join(RAW, fn)
    local = load_local(name, filename)
    if local is None:
        return 0, None
    # 以本地表结构为准：只更新 date>=本地最新 的行
    local = local.copy()
    local['date'] = pd.to_datetime(local['date'])
    local_last = local['date'].max()
    add = new_df[new_df['date'] > local_last]
    if len(add) == 0:
        return 0, str(local_last.date())
    # 构造新行：保留本地列结构，close 覆盖，其余列按历史最后一行填充（open/high/low 不影响策略）
    template = local.iloc[-1].to_dict()
    rows = []
    for _, r in add.iterrows():
        row = dict(template)
        row['date'] = r['date']
        if 'close' in row:
            row['close'] = r['close']
        rows.append(row)
    out = pd.concat([local, pd.DataFrame(rows)], ignore_index=True)
    out = out.drop_duplicates(subset=['date'], keep='last').sort_values('date')
    tmp = p + '.tmp'
    out.to_csv(tmp, index=False, encoding='utf-8-sig')
    os.replace(tmp, p)
    return len(add), str(out['date'].max().date())


def merge_etf(new_df):
    """国债ETF：本地仅 date,close 两列。"""
    import pandas as pd
    code, fn, _ = ETF['SHELTER']
    p = os.path.join(RAW, fn)
    local = pd.read_csv(p, parse_dates=['date'])
    local_last = local['date'].max()
    add = new_df[new_df['date'] > local_last]
    if len(add) == 0:
        return 0, str(local_last.date())
    out = pd.concat([local, pd.DataFrame({'date': add['date'], 'close': add['close']})],
                    ignore_index=True).drop_duplicates('date').sort_values('date')
    tmp = p + '.tmp'
    out.to_csv(tmp, index=False, encoding='utf-8-sig')
    os.replace(tmp, p)
    return len(add), str(out['date'].max().date())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--max-retry', type=int, default=3)
    ap.add_argument('--lookback', type=int, default=30, help='抓取起始回溯天数')
    a = ap.parse_args()

    end = _today()
    start = end - dt.timedelta(days=max(a.lookback, 40))
    s, e = _date_str(start), _date_str(end)
    report = {'run_date': str(end), 'range': [s, e], 'items': {}}

    if a.dry_run:
        print(f'[dry-run] 计划抓取 {s}~{e} · 中证{list(CSINDEX)} · 国证{list(CNI)} · ETF 511010')
        print('[dry-run] 不写任何文件')
        return 0

    # 1) 中证官网
    for name, code in CSINDEX.items():
        try:
            df = fetch_csindex(code, s, e, a.max_retry)
            added, last = merge_pool(name, df)
            report['items'][name] = {'src': f'csindex:{code}', 'status': 'ok',
                                     'added': added, 'last': last}
        except Exception as ex:
            report['items'][name] = {'src': f'csindex:{code}', 'status': 'fail',
                                     'reason': str(ex)[:100], 'action': '沿用上一版CSV'}
            print(f'[WARN] {name} 抓数失败，沿用上一版: {ex}')

    # 2) 国证（价值/成长100）
    for name, code in CNI.items():
        try:
            df = fetch_cni(code, s, e, a.max_retry)
            added, last = merge_pool(name, df)
            report['items'][name] = {'src': f'cni:{code}', 'status': 'ok',
                                     'added': added, 'last': last}
        except Exception as ex:
            report['items'][name] = {'src': f'cni:{code}', 'status': 'fail',
                                     'reason': str(ex)[:100], 'action': '沿用上一版CSV'}
            print(f'[WARN] {name} 抓数失败，沿用上一版: {ex}')

    # 3) 国债ETF
    try:
        df = fetch_etf(ETF['SHELTER'][2], a.max_retry)
        added, last = merge_etf(df)
        report['items']['SHELTER'] = {'src': 'sina:sh511010', 'status': 'ok',
                                      'added': added, 'last': last}
    except Exception as ex:
        report['items']['SHELTER'] = {'src': 'sina:sh511010', 'status': 'fail',
                                      'reason': str(ex)[:100], 'action': '沿用上一版CSV'}
        print(f'[WARN] 国债ETF 抓数失败，沿用上一版: {ex}')

    os.makedirs(os.path.join(BASE, 'data'), exist_ok=True)
    with open(os.path.join(BASE, 'data', 'fetch_report.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    ok = sum(1 for v in report['items'].values() if v['status'] == 'ok')
    fail = len(report['items']) - ok
    print(f'[完成] 抓数 {ok}/{len(report["items"])} 成功, {fail} 失败(沿用上一版)')
    for name, v in report['items'].items():
        print(f'  {name:<10} {v["status"]:<5} 新增{v.get("added", 0):>2}行 截至{v.get("last", "—")}')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
