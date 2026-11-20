# -*- coding: utf-8 -*-
"""生成 index.html：内联 ECharts + fetch 同源 JSON 接口的静态看板。

页面零外部 CDN 依赖；所有数字来自 data/*.json（fetch no-store），
数据每日同步后刷新页面即生效，页面本身无需重建。
复用既有 v1 看板的样式与渲染逻辑，仅把数据源从内联改为 fetch。
"""
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = '/root/.codebuddy/artifact/2f8a7d30-9c21-4f0b-1d76-f4162760e000/ref'

CSS = open(os.path.join(REF, 'board_style.css'), encoding='utf-8').read()
ECHARTS = open(os.path.join(REF, 'echarts.min.js'), encoding='utf-8').read()

# 兼容新增 DOM 的补充样式（同步条/按钮/表格/说明/区间按钮）
CSS += '''
header{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;
  background:linear-gradient(160deg,#101b30 0%,#1c3455 58%,#2a4d7d 100%);
  border-radius:12px;padding:16px 20px;margin:16px 0}
header .brand h1{font-size:24px;letter-spacing:1px;line-height:1.2}
header .brand .sub{font-size:12px;color:rgba(255,255,255,.72);margin-top:4px}
header .logo{width:38px;height:38px;display:flex;align-items:center;justify-content:center;
  border-radius:10px;background:linear-gradient(150deg,#f3e3bd,#dfc07d);color:#1c3455;
  font-weight:800;font-size:15px;letter-spacing:.5px}
header .navlinks a{color:rgba(255,255,255,.8)}
header .navlinks a.on{color:#f6dda0}
.syncbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;background:#f7f9fc;
  border:1px solid #e3e9f1;border-radius:10px;padding:10px 14px;margin:14px 0;font-size:13px;color:#40526b}
.syncbar .dot{width:9px;height:9px;border-radius:50%;display:inline-block;background:#95a5b6}
.syncbar .dot.ok{background:#0f9d58}.syncbar .dot.idle{background:#b8860b}.syncbar .dot.bad{background:#d93025}
.syncbar button{margin-left:auto;background:#132a4a;color:#fff;border:0;border-radius:6px;
  padding:5px 12px;cursor:pointer;font-size:12px}
.range{display:flex;gap:4px;flex-wrap:wrap}
.range button{border:1px solid #dde4ec;background:#fff;color:#6b7a8c;border-radius:6px;
  padding:4px 9px;font-size:12px;cursor:pointer}
.range button.on{background:#132a4a;color:#fff;border-color:#132a4a}
.chart-meta{font-size:12px;color:#6b7a8c;margin:6px 2px}
.chart{width:100%;height:380px}
.eqstats{display:flex;gap:18px;flex-wrap:wrap;margin-top:10px;padding-top:10px;border-top:1px solid #eef1f5}
.eqstats>div{display:flex;flex-direction:column;font-size:12px;color:#6b7a8c}
.eqstats b{font-size:15px;color:#132a4a;margin-top:2px}
.tbl-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{padding:7px 8px;text-align:right;border-bottom:1px solid #eef1f5;white-space:nowrap}
th{color:#6b7a8c;font-weight:600;background:#f7f9fc}
td:first-child,th:first-child{text-align:left}
.about{font-size:13px;line-height:1.75;color:#33455f}
.about h3{margin:14px 0 6px;font-size:14px;color:#132a4a}
.about ul{padding-left:20px}.about li{margin:4px 0}
footer{text-align:center;color:#95a5b6;font-size:11px;padding:22px 0 8px}
'''

# 渲染 JS：复用原逻辑，但把 D 的组装改为 fetch 后注入；末尾初始化改为 async
RENDER = open(os.path.join(REF, 'board_render.js'), encoding='utf-8').read()
# 移除原末尾的直接渲染调用，改为由 fetch 流程驱动
RENDER = RENDER.replace(
    'renderKpis();renderEquity();renderHeat();renderYear();renderAttrib();renderHold();',
    'window.__renderAll=function(){renderKpis();renderEquity();renderHeat();renderYear();renderAttrib();renderHold();};')

HTML = '''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>行业轮动增强 · 策略净值看板</title>
<style>__CSS__</style>
<script>__ECHARTS__</script>
</head><body>
<div class="wrap">
  <header>
    <div class="brand"><span class="logo">SR</span>
      <div><h1>行业轮动增强</h1><p class="sub">风格自适应动量轮动 · 回撤断路器 v1.0 · 每日自动同步</p></div>
    </div>
    <nav class="navlinks">
      <a href="#overview" class="on">总览</a><a href="#monthly">月度收益</a>
      <a href="#yearly">年度表现</a><a href="#attrib">收益归因</a><a href="#holdings">当前持仓</a><a href="#about">策略说明</a>
    </nav>
  </header>

  <section id="overview">
    <div class="syncbar"><span id="syncDot" class="dot"></span>
      <span id="syncText">数据加载中…</span>
      <button id="refreshBtn" title="刷新数据">↻ 刷新</button>
    </div>
    <div id="kpis" class="kpis"></div>
    <div class="card">
      <div class="card-hd"><h2>净值走势</h2>
        <div id="range" class="range">
          <button data-r="1m">近1月</button><button data-r="3m">近3月</button>
          <button data-r="6m">近6月</button><button data-r="ytd">今年以来</button>
          <button data-r="1y">近1年</button><button data-r="3y">近3年</button>
          <button data-r="all" class="on">全部</button>
        </div>
      </div>
      <div class="chart-meta" id="rangeMeta"></div>
      <div id="eqChart" class="chart"></div>
      <div id="eqStats" class="eqstats"></div>
    </div>
    <div class="note" id="basisNote"></div>
  </section>

  <section id="monthly"><div class="card"><div class="card-hd"><h2>月度收益热力图</h2></div>
    <div id="heat" class="heat"></div></div></section>

  <section id="yearly"><div class="card"><div class="card-hd"><h2>年度表现</h2></div>
    <div class="tbl-wrap"><table id="yearTable">
      <thead><tr><th>年份</th><th>策略收益</th><th>中证800</th><th>超额</th><th>最大回撤</th><th>波动</th><th>夏普</th><th>卡玛</th></tr></thead>
      <tbody id="yearBody"></tbody></table></div></div></section>

  <section id="attrib"><div class="card"><div class="card-hd"><h2>年度收益归因</h2></div>
    <div id="attrNote" class="note"></div>
    <div id="attrChart" class="chart"></div>
    <div class="tbl-wrap"><table><thead id="attrThead"></thead><tbody id="attrBody"></tbody></table></div>
    </div></section>

  <section id="holdings"><div class="card"><div class="card-hd"><h2 id="holdTitle">目标仓位</h2></div>
    <div id="holdBars"></div></div></section>

  <section id="about"><div class="card"><div class="card-hd"><h2>策略说明与因子规则</h2></div>
    <div class="about" id="aboutBody"></div></div></section>

  <footer>数据来自 v1.0 真实回测 · 中证800 仅作业绩比较基准 · 历史表现不代表未来，不构成投资建议</footer>
</div>
<script>
__RENDER__
// ===== fetch 同源接口并组装 D =====
async function loadData(){
  const base='data/';
  const opt={cache:'no-store'};
  const [meta,nav,sig,hold,attr]=await Promise.all([
    fetch(base+'meta.json',opt).then(r=>r.json()),
    fetch(base+'nav.json',opt).then(r=>r.json()),
    fetch(base+'signal.json',opt).then(r=>r.json()),
    fetch(base+'holdings.json',opt).then(r=>r.json()),
    fetch(base+'attribution.json',opt).then(r=>r.json())
  ]);
  // 组装渲染层期望的 D 结构
  const hy=nav.year_full||nav.yearly.map(y=>({year:y.year,ret:y.strategy,z800:y.benchmark,
    excess:y.strategy-y.benchmark,mdd:0,vol:0,sharpe:0,calmar:0}));
  D={
    meta:{version:meta.version,name:meta.name,start:meta.start,end:meta.end,
          n_days:meta.bars,winrate:nav.monthly_winrate,last_signal:hold.as_of},
    dates:nav.dates,nav:nav.strategy,z800:nav.benchmark,dd:nav.drawdown,
    heat:nav.monthly,years:hy,attribution:attr,
    holdings:Object.fromEntries(hold.positions.map(p=>[p.asset,p.weight]))
  };
  // 同步状态条
  const s=meta.sync||{};
  const stale=(()=>{if(!s.last_sync)return true;
    return (Date.now()-new Date(s.last_sync).getTime())/3600000>26;})();
  const dot=document.getElementById('syncDot');
  dot.className='dot '+(s.status==='fallback'||stale?'bad':(s.status==='skipped'?'idle':'ok'));
  document.getElementById('syncText').textContent=
    '同步 '+(s.status||'—')+' · 数据截至 '+meta.as_of+' · '+meta.bars+' 交易日 · 上次同步 '+(s.last_sync||'—');
  // 策略说明
  document.getElementById('aboutBody').innerHTML=
    '<p><strong>'+meta.name+'</strong>：'+meta.price_convention+'。</p>'+
    '<p>每 10 个交易日按综合动量得分选择最强的 1 个宽基类资产，T 日收盘出信号、T+1 收盘执行，含 8bps 单边成本，严格零前视。</p>'+
    '<h3>因子与风控规则</h3><ul>'+(sig.rules||[]).map(r=>'<li><b>'+r.name+'</b>：'+r.rule+'</li>').join('')+'</ul>'+
    '<p class="note">当前生效信号（'+sig.as_of+'）：触发='+sig.current.trigger+' · 门控='+sig.current.gate+
    ' · 市场回撤='+((sig.current.mkt_dd||0)*100).toFixed(1)+'%。</p>';
  window.__renderAll();
}
document.getElementById('refreshBtn').addEventListener('click',loadData);
loadData().catch(e=>{
  document.getElementById('syncText').textContent='数据加载失败：'+e.message;
  document.getElementById('syncDot').className='dot bad';
});
</script>
</body></html>'''

HTML = (HTML.replace('__CSS__', CSS).replace('__ECHARTS__', ECHARTS)
        .replace('__RENDER__', RENDER))
out = os.path.join(BASE, 'index.html')
with open(out, 'w', encoding='utf-8') as f:
    f.write(HTML)
print(f'[完成] index.html 生成: {len(HTML)} 字节 (内联ECharts+fetch同源接口)')
