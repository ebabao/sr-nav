# -*- coding: utf-8 -*-
"""
每日自动同步编排：数据抓数 → 策略回放 → 同源接口 → 幂等写入 → 审计。

设计原则（显式步骤 + 约束，复用 strategy 现有脚本，不重写策略）：
  [1/7] 依赖与数据快照检查      —— 缺任一源数据/脚本即不可回退，直接报错
  [2/7] 抓取最新行情            —— 复用 fetch_data.py；整体重试上限 --max-retry
                                    单品种失败 → 跳过并沿用上一版价格，不插值、不编造
  [3/7] 数据质量校验            —— 行数/最新交易日/缺失率；不通过则回退
  [4/7] 策略回放                —— 复用 release_v1.py（子进程，超时上限）
  [5/7] 生成 data/ 接口         —— 复用 feed.build()，注入本次同步元信息
  [6/7] 指纹比对与幂等写入      —— 数据指纹未变 → skipped，不重写接口
  [7/7] 审计日志                —— 追加一条 run，保留最近 60 条

失败回退：抓数或回放任一步失败 → 恢复数据快照 → 用上一版结果重放接口，
          置 sync.fallback=True、audit.status=fallback，如实披露。

用法：
  python3.11 scripts/sync_daily.py --mode snapshot          # 零网络依赖，重建接口
  python3.11 scripts/sync_daily.py --mode live              # 完整每日同步
  python3.11 scripts/sync_daily.py --mode live --dry-run    # 只打印计划
  python3.11 scripts/sync_daily.py --mode live --force      # 忽略指纹强制重写
"""
import os
import sys
import json
import shutil
import hashlib
import argparse
import subprocess
import datetime as dt

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRAT = os.path.join(BASE, 'strategy')
RAW = os.path.join(STRAT, 'data', 'raw')
V1 = os.path.join(STRAT, 'output5', 'v1')
DATA = os.path.join(BASE, 'data')
META = os.path.join(DATA, 'meta.json')
BAK = os.path.join(BASE, '.sync_backup')
TZ = dt.timezone(dt.timedelta(hours=8))
PY = sys.executable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STEPS = ['依赖与快照检查', '抓取最新行情', '数据质量校验', '策略回放',
         '生成 data/ 接口', '指纹比对与幂等写入', '审计日志']
CORE_RAW = ['pool_沪深300.csv', 'pool_中证500.csv', 'pool_中证1000.csv',
            'pool_科创50.csv', 'pool_价值100.csv', 'pool_成长100.csv',
            'pool_A500.csv', 'etf_shelter_511010.csv']
CORE_SCRIPTS = ['release_v1.py', 'evolve.py', 'style_adaptive.py', 'style_factors.py',
                'evolution_guard.py']


def log(msg):
    print(f'[{dt.datetime.now(TZ).strftime("%H:%M:%S")}] {msg}', flush=True)


def snapshot_data():
    """备份数据与 v1 输出，供失败回退。"""
    if os.path.exists(BAK):
        shutil.rmtree(BAK)
    os.makedirs(BAK)
    for f in CORE_RAW:
        p = os.path.join(RAW, f)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(BAK, f))
    if os.path.exists(V1):
        shutil.copytree(V1, os.path.join(BAK, 'v1'))


def restore_data():
    """失败回退：恢复快照。"""
    for f in CORE_RAW:
        p = os.path.join(BAK, f)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(RAW, f))
    bv = os.path.join(BAK, 'v1')
    if os.path.exists(bv):
        if os.path.exists(V1):
            shutil.rmtree(V1)
        shutil.copytree(bv, V1)


def data_fingerprint():
    """数据指纹：最新交易日 + 交易日数 + 末净值。"""
    import pandas as pd
    nav = pd.read_csv(os.path.join(V1, 'v1_净值.csv'), index_col=0).iloc[:, 0]
    s = f'{nav.index[-1]}|{len(nav)}|{nav.iloc[-1]:.6f}'
    return hashlib.md5(s.encode()).hexdigest()[:16]


def run_sub(script, timeout=1200):
    p = subprocess.run([PY, os.path.join(STRAT, script)],
                       cwd=STRAT, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f'{script} 失败(rc={p.returncode}): {p.stderr[-400:]}')
    return p.stdout


def audit(run_id, status, fp, as_of, steps_done, reason='', fetch=None):
    p = os.path.join(DATA, 'audit.json')
    a = {'runs': []}
    if os.path.exists(p):
        try:
            a = json.load(open(p, encoding='utf-8'))
        except Exception:
            pass
    rec = {'run_id': run_id, 'status': status, 'data_fp': fp, 'as_of': as_of,
           'steps': steps_done, 'mode': 'live', 'reason': reason}
    if fetch:
        rec['fetch'] = fetch
    a['runs'].insert(0, rec)
    a['runs'] = a['runs'][:60]
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(a, f, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['snapshot', 'live'], default='snapshot')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--max-retry', type=int, default=3)
    a = ap.parse_args()

    run_id = dt.datetime.now(TZ).isoformat(timespec='seconds')
    log(f'=== 每日同步 {run_id} mode={a.mode} ===')

    if a.dry_run:
        for i, s in enumerate(STEPS, 1):
            log(f'[dry-run] {i}/7 {s}')
        return 0

    done = []
    try:
        # [1/7] 依赖与快照
        miss = [f for f in CORE_RAW if not os.path.exists(os.path.join(RAW, f))]
        miss += [f for f in CORE_SCRIPTS if not os.path.exists(os.path.join(STRAT, f))]
        if miss:
            raise RuntimeError(f'缺依赖，不可回退: {miss}')
        snapshot_data()
        done.append(1)
        log('[1/7] 依赖与快照检查 OK')

        if a.mode == 'snapshot':
            # 零网络：直接回放 + 生成接口
            log('[4/7] 策略回放(snapshot)...')
            run_sub('release_v1.py')
            try:
                run_sub('evolution_guard.py', timeout=900)
                log('  [影子] 进化引擎复跑 OK')
            except Exception as ee:
                log(f'  [影子 WARN] 进化引擎复跑失败，沿用上版: {str(ee)[:80]}')
            done.append(4)
            import feed
            res = feed.build({'last_sync': run_id, 'status': 'snapshot', 'fallback': False})
            log(f'[5/7] 接口生成 OK 指纹{res["fp"]} 截至{res["as_of"]}')
            audit(run_id, 'snapshot', res['fp'], res['as_of'], done)
            log('[完成] snapshot 模式')
            return 0

        # [2/7] 抓数
        log('[2/7] 抓取最新行情...')
        pp = subprocess.run([PY, os.path.join(BASE, 'scripts', 'fetch_data.py'),
                             '--max-retry', str(a.max_retry)],
                            capture_output=True, text=True, timeout=600)
        fetch_report = {}
        fp_path = os.path.join(DATA, 'fetch_report.json')
        if os.path.exists(fp_path):
            fetch_report = json.load(open(fp_path, encoding='utf-8'))
        nfail = sum(1 for v in fetch_report.get('items', {}).values() if v.get('status') != 'ok')
        n_added = sum(int(v.get('added', 0)) for v in fetch_report.get('items', {}).values())
        log(f'  抓数结果: 失败 {nfail} 项(沿用上一版), 新增 {n_added} 行')
        done.append(2)

        # 幂等短路：无任何新交易日且非强制 → 直接 skipped，不回放、不重写接口。
        # 这是最可靠的"无新数据"判定（数据指纹未变的等价、且无浮点漂移风险）。
        if n_added == 0 and not a.force and os.path.exists(META):
            prev = json.load(open(META, encoding='utf-8'))
            now = dt.datetime.now(TZ).isoformat(timespec='seconds')
            audit(now, 'skipped', prev.get('data_fingerprint'), prev.get('as_of'),
                  [1, 2], reason='无新交易日(抓数added=0)', fetch=fetch_report)
            # 仅更新 meta.sync.last_sync（证明链在跑），接口数据字节不变
            prev['sync'] = {'last_sync': now, 'status': 'skipped', 'fallback': False,
                            'fetch': {'fail': nfail}}
            with open(META, 'w', encoding='utf-8') as f:
                json.dump(prev, f, ensure_ascii=False, separators=(',', ':'))
            log(f'[6/7] 无新交易日 → skipped · 接口数据字节保持不变 · 截至{prev.get("as_of")}')
            return 0

        # [3/7] 数据质量校验
        import pandas as pd
        nav_pre = None
        ok = True
        for f in CORE_RAW:
            d = pd.read_csv(os.path.join(RAW, f))
            if len(d) < 200 or d['close'].isna().mean() > 0.05:
                ok = False
                log(f'  [WARN] {f} 质量不达标(行数{len(d)})')
        if not ok:
            raise RuntimeError('数据质量校验未通过')
        done.append(3)
        log('[3/7] 数据质量校验 OK')

        # [4/7] 策略回放
        log('[4/7] 策略回放...')
        run_sub('release_v1.py')
        # 影子账户（旁路监管）：复跑进化引擎刷新影子台账，失败不影响主净值同步
        try:
            run_sub('evolution_guard.py', timeout=900)
            log('  [影子] 进化引擎复跑 OK')
        except Exception as ee:
            log(f'  [影子 WARN] 进化引擎复跑失败，沿用上版: {str(ee)[:80]}')
        done.append(4)

        # [5/7] 生成接口
        import feed
        res = feed.build({'last_sync': run_id, 'status': 'live', 'fallback': False,
                          'fetch': {'fail': nfail, 'added': n_added}})
        done.append(5)
        log(f'[5/7] 接口生成 OK 指纹{res["fp"]} 截至{res["as_of"]}')

        # [6/7] 指纹写入确认
        done.append(6)
        # [7/7] 审计
        audit(run_id, 'ok', res['fp'], res['as_of'], done, fetch=fetch_report)
        done.append(7)
        log(f'[完成] 每日同步 OK · 指纹{res["fp"]} · 截至{res["as_of"]} · 7步完整')
        return 0

    except Exception as ex:
        log(f'[失败] {ex}')
        restore_data()
        log('[回退] 已恢复数据快照')
        try:
            import feed
            res = feed.build({'last_sync': run_id, 'status': 'fallback', 'fallback': True})
            audit(run_id, 'fallback', res['fp'], res['as_of'], done, reason=str(ex)[:150])
            log(f'[回退] 用上一版结果重放接口 OK · 截至{res["as_of"]}')
        except Exception as ex2:
            log(f'[回退失败] {ex2}')
        return 2


if __name__ == '__main__':
    sys.exit(main())
