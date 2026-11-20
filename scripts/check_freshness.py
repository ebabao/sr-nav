# -*- coding: utf-8 -*-
"""
停更巡检（watchdog）：检查 data/ 接口是否按时同步，超阈值可自动下发 workflow_dispatch 重启。

沿用你既有时间线巡检的习惯：一行中文汇报「接口数 / 数据截至 / 距上次同步 / 重启状态」。
退出码：0=正常，2=停摆（供 GitHub Actions 决定是否触发重启），1=接口缺失/错误。

用法：
  python3.11 scripts/check_freshness.py                       # 仅巡检并汇报
  python3.11 scripts/check_freshness.py --threshold 26        # 自定义小时阈值
  python3.11 scripts/check_freshness.py --restart            # 停摆时下发 workflow_dispatch
"""
import os
import sys
import json
import argparse
import datetime as dt
import subprocess

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'data')
META = os.path.join(DATA, 'meta.json')
TZ = dt.timezone(dt.timedelta(hours=8))
# 必需接口：缺任一即判定「接口异常」。
# 注：holdings.json（底层资产与调仓信号）是可选增强接口——feed.py 生成失败不阻塞主链路，
# 页面 fetch 亦有 catch 降级。故意不列入 REQUIRED，避免一次可选失败被误判为同步停摆。
REQUIRED = ['meta.json', 'nav.json', 'signal.json', 'holdings.json',
            'attribution.json', 'audit.json']


def parse_time(s):
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--threshold', type=float, default=26.0, help='停摆阈值（小时）')
    ap.add_argument('--restart', action='store_true', help='停摆时下发 workflow_dispatch')
    ap.add_argument('--workflow', default='daily_sync.yml')
    a = ap.parse_args()

    now = dt.datetime.now(TZ)
    present = [f for f in REQUIRED if os.path.exists(os.path.join(DATA, f))]
    missing = [f for f in REQUIRED if f not in present]

    if not os.path.exists(META):
        print(f'同步状态：异常 · 接口文件 {len(present)}/{len(REQUIRED)} · meta.json 缺失 · 重启指令：未下发')
        if a.restart:
            subprocess.run(['gh', 'workflow', 'run', a.workflow], check=False)
        return 1

    with open(META, encoding='utf-8') as f:
        m = json.load(f)
    sync = m.get('sync', {})
    last = parse_time(sync.get('last_sync', ''))
    if last is None:
        print(f'同步状态：异常 · 接口文件 {len(present)}/{len(REQUIRED)} · 上次同步时间不可解析 · 重启指令：未下发')
        return 1
    if last.tzinfo is None:
        last = last.replace(tzinfo=TZ)

    mins = (now - last).total_seconds() / 60.0
    hours = mins / 60.0
    stale = hours > a.threshold or bool(missing)
    bars = m.get('bars', '—')
    as_of = m.get('as_of', '—')
    status = '停摆' if stale else '正常'

    restarted = '未下发'
    if stale and a.restart:
        p = subprocess.run(['gh', 'workflow', 'run', a.workflow],
                           capture_output=True, text=True)
        restarted = '已下发' if p.returncode == 0 else f'下发失败({p.returncode})'

    reason = ''
    if missing:
        reason = f' · 缺失 {",".join(missing)}'
    elif hours > a.threshold:
        reason = f' · 超阈值 {a.threshold:g}h'
    if sync.get('fallback'):
        reason += ' · 上次为回放回退'

    print(f'同步状态：{status} · 接口 {len(present)}/{len(REQUIRED)} 个 · 数据截至 {as_of} '
          f'· 交易日 {bars} · 距上次同步 {hours:.1f} 小时（{mins:.0f} 分钟）'
          f'· 重启指令 {restarted}{reason}')
    return 2 if stale else 0


if __name__ == '__main__':
    sys.exit(main())
