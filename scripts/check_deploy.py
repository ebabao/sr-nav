# -*- coding: utf-8 -*-
"""
部署自愈巡检：比对线上 Pages 的 data/meta.json 与仓库本地 meta.json，
若线上数据日期/交易日/指纹落后于仓库，自动下发 workflow_dispatch 重新部署。

背景：check_freshness.py 只监视「数据同步链」，不监视 GitHub Pages 部署状态。
Pages 部署偶发平台瞬态失败（artifact metadata 未就绪等）时，仓库数据已更新、
线上看板却滞后一天，且 watchdog 不会自动修复。本脚本补上这一环自愈。

沿用一行中文汇报习惯：线上截至 / 仓库截至 / 版本指纹 / 重新部署状态。
退出码：0=线上一致，2=检测到落后（供 Actions 判断），1=读取失败（无法比对）。

用法：
  python3.11 scripts/check_deploy.py                        # 仅比对汇报
  python3.11 scripts/check_deploy.py --restart-deploy       # 落后时下发重新部署
"""
import os
import sys
import json
import time
import argparse
import urllib.request
import subprocess

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META = os.path.join(BASE, 'data', 'meta.json')
PAGES_META = 'https://ebabao.github.io/sr-nav/data/meta.json'


def fetch_pages_meta(retry=3):
    """读取线上 Pages 的 meta.json；加时间戳 + no-store 绕过 CDN 缓存。"""
    last = None
    for k in range(retry):
        try:
            url = PAGES_META + '?t=' + str(int(time.time() * 1000))
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0', 'Cache-Control': 'no-store'})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:
            last = str(e)[:80]
        if k < retry - 1:
            time.sleep(3 * (k + 1))
    print(f'[check_deploy] 线上 meta 读取失败: {last}', file=sys.stderr)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--restart-deploy', action='store_true', help='线上落后时下发 workflow_dispatch')
    ap.add_argument('--workflow', default='deploy_pages.yml')
    a = ap.parse_args()

    if not os.path.exists(META):
        print('部署状态：仓库 meta.json 缺失 · 无法比对 · 重新部署：未下发')
        return 1
    with open(META, encoding='utf-8') as f:
        local = json.load(f)

    remote = fetch_pages_meta()
    if remote is None:
        print('部署状态：线上 meta.json 读取失败 · 未能比对 · 重新部署：未下发')
        return 1

    l_asof = str(local.get('as_of', '—'))
    r_asof = str(remote.get('as_of', '—'))
    l_fp = str(local.get('data_fingerprint', ''))
    r_fp = str(remote.get('data_fingerprint', ''))
    try:
        l_bars = int(local.get('bars', 0) or 0)
        r_bars = int(remote.get('bars', 0) or 0)
    except Exception:
        l_bars = r_bars = 0

    # 落后判据（任一成立）：线上日期更早 / 交易日更少 / 指纹不一致
    behind = (r_asof < l_asof) or (r_bars < l_bars) or (r_fp != l_fp)

    restarted = '未下发'
    if behind and a.restart_deploy:
        p = subprocess.run(['gh', 'workflow', 'run', a.workflow],
                           capture_output=True, text=True)
        restarted = '已下发' if p.returncode == 0 else f'下发失败({p.returncode})'

    status = '线上落后' if behind else '线上一致'
    print(f'部署状态：{status} · 线上截至 {r_asof}({r_bars}日/{r_fp[:8]}) '
          f'· 仓库截至 {l_asof}({l_bars}日/{l_fp[:8]}) · 重新部署：{restarted}')
    return 2 if behind else 0


if __name__ == '__main__':
    sys.exit(main())
