# -*- coding: utf-8 -*-
"""生成 index.html：内联 ECharts + fetch 同源 JSON 接口的静态看板。

页面零外部 CDN 依赖；所有数字来自 data/*.json（fetch no-store），
数据每日同步后刷新页面即生效，页面本身无需重建。
版式参考 mafc-nav：sticky 顶栏 + 深蓝 hero + 分区卡片设计。
"""
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = '/root/.codebuddy/artifact/2f8a7d30-9c21-4f0b-1d76-f4162760e000/ref'

CSS = '''
:root{--navy:#132a4a;--navy2:#1f3a5f;--brand:#2c5282;--gold:#b8860b;--ink:#22303f;
 --mut:#6b7a8c;--line:#dde4ec;--bg:#f4f6f9;--up:#d93025;--down:#0f9d58;--blue:#2563eb;
 --card:#fff;--shadow:0 2px 12px rgba(20,40,70,.06)}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:78px}
body{margin:0;background:var(--bg);color:var(--ink);font-size:14px;line-height:1.6;
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
 -webkit-font-smoothing:antialiased}
a{color:var(--brand);text-decoration:none}a:hover{text-decoration:underline}
code{background:#eef2f5;padding:1px 6px;border-radius:4px;font-size:12px}

/* ===== 顶栏 ===== */
.topnav{position:sticky;top:0;z-index:20;background:#101b30;
 border-bottom:1px solid rgba(255,255,255,.08);box-shadow:0 1px 0 rgba(0,0,0,.18)}
.topnav .wrap{display:flex;align-items:center;gap:20px;height:68px;max-width:1220px;padding:0 22px;margin:0 auto}
.brand{display:flex;align-items:center;gap:12px;color:#fff;font-weight:600;white-space:nowrap;font-size:17px;letter-spacing:.6px}
.brand .mark{width:38px;height:38px;border-radius:11px;background:linear-gradient(150deg,#f3e3bd,#dfc07d);
 display:grid;place-items:center;color:#2b2416;font-weight:800;font-size:15px;letter-spacing:.5px;
 box-shadow:inset 0 1px 0 rgba(255,255,255,.55)}
.navlinks{display:flex;gap:2px;overflow-x:auto;scrollbar-width:none;white-space:nowrap;flex:1;
 margin-left:12px;justify-content:space-between}
.navlinks::-webkit-scrollbar{display:none}
.navlinks a{color:rgba(255,255,255,.88);font-size:14px;padding:10px 11px;border-radius:8px;
 font-weight:500;letter-spacing:.4px;transition:color .15s,background .15s}
.navlinks a:hover{color:#fff;background:rgba(255,255,255,.08);text-decoration:none}
.navlinks a.on{color:#f3e3bd;background:rgba(232,182,76,.12)}
.live{display:flex;align-items:center;gap:7px;color:rgba(219,228,255,.78);font-size:12px;white-space:nowrap}
.live span{display:none}
@media(min-width:1181px){.live span{display:inline}}
.live i{width:7px;height:7px;border-radius:50%;background:#55d39a;box-shadow:0 0 0 4px rgba(85,211,154,.14)}
.live.warn i{background:#f0b429;box-shadow:0 0 0 4px rgba(240,180,41,.14)}
.live.bad i{background:#e5484d;box-shadow:0 0 0 4px rgba(229,72,77,.14)}

/* ===== 布局与 hero ===== */
.wrap{max-width:1220px;margin:0 auto;padding:0 22px 60px}
.hero{background:linear-gradient(160deg,#101b30 0%,#1c3455 58%,#2a4d7d 100%);color:#fff;
 padding:42px 0 40px;position:relative;overflow:hidden}
.hero::after{content:"";position:absolute;right:-60px;top:-110px;width:300px;height:300px;border-radius:50%;
 background:radial-gradient(circle,rgba(232,182,76,.13),transparent 68%);pointer-events:none}
.hero-eyebrow{display:flex;align-items:center;gap:15px;color:#e8c886;
 font-size:15px;letter-spacing:6px;font-weight:600;white-space:nowrap}
.hero-eyebrow::before{content:"";width:44px;height:3px;background:#e8b64c;border-radius:2px;flex:0 0 auto}
.hero h1{margin:12px 0 13px;font-size:37px;letter-spacing:2px;font-weight:800;line-height:1.25}
.hero h1 .dot{color:#e8b64c;margin:0 6px}
.hero-sub{font-size:14.5px;color:rgba(255,255,255,.75);letter-spacing:.5px;line-height:1.7}
.hero-sub b{color:#f6dda0;font-weight:700;font-variant-numeric:tabular-nums}
@media(max-width:980px){.hero{padding:30px 0 28px}.hero h1{font-size:27px}.hero-eyebrow{font-size:12px;letter-spacing:4px}}
@media(max-width:640px){.hero h1{font-size:21px;letter-spacing:1px}.hero-sub{font-size:13px}
 .hero-eyebrow{font-size:11px;letter-spacing:3px;gap:10px}.hero-eyebrow::before{width:28px}}

/* ===== 分区与卡片 ===== */
.sec{margin-top:28px}
.sec h2{font-size:18px;margin:0 0 12px;padding-left:11px;border-left:4px solid var(--brand);color:var(--navy)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;box-shadow:var(--shadow);overflow:hidden}
.card h3{font-size:15px;margin:0;padding:14px 18px;border-bottom:1px solid var(--line);color:var(--navy)}
.body{padding:16px 18px}
.note{font-size:12px;color:var(--mut);line-height:1.8;margin-top:10px}
.note strong{color:var(--ink)}

/* ===== 同步状态条（胶囊） ===== */
.syncbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:11px 16px;background:#fff;
 border:1px solid var(--line);border-radius:9px;margin-bottom:12px;box-shadow:var(--shadow)}
.pills{display:flex;flex-wrap:wrap;gap:8px;flex:1}
.pill{font-size:11.5px;color:#475569;background:#f7f9fc;border:1px solid var(--line);
 border-radius:999px;padding:4px 10px;white-space:nowrap}
.pill b{color:var(--ink);font-weight:700}
.pill.ok{border-color:#bfe6cf;background:#f1fbf5;color:#0b6b39}
.pill.warn{border-color:#f0dcae;background:#fffaef;color:#7a5a14}
.pill.err{border-color:#f0c9c4;background:#fff5f4;color:#a52a1e}
.syncbar button{background:#132a4a;color:#fff;border:0;border-radius:7px;padding:5px 12px;cursor:pointer;font-size:12px;white-space:nowrap}

/* ===== KPI ===== */
.kpis{display:grid;grid-template-columns:repeat(6,1fr)}
.kpi{padding:15px 16px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);position:relative}
.kpi:nth-child(6n){border-right:0}
.kpi:nth-last-child(-n+6){border-bottom:0}
.kpi:before{content:"";position:absolute;left:16px;top:0;width:26px;height:3px;border-radius:0 0 3px 3px;background:var(--brand)}
.kpi.hl:before{background:var(--up);width:38px}
.kpi.hl{background:#fffbe8}
.kpi .k{font-size:11.5px;color:var(--mut);margin-bottom:5px;white-space:nowrap}
.kpi .v{font-size:21px;font-weight:800;letter-spacing:-.5px;line-height:1.25;font-variant-numeric:tabular-nums}
.kpi .s{font-size:10.5px;color:var(--mut);margin-top:3px}
.up{color:var(--up)}.down{color:var(--down)}.flat{color:var(--ink)}

/* ===== 控制条 / 图表 ===== */
.ctrl{display:flex;flex-wrap:wrap;gap:14px;align-items:center;padding:12px 18px;border-bottom:1px solid var(--line)}
.seg{display:flex;gap:3px;background:#f2f4f9;padding:3px;border-radius:9px;flex-wrap:wrap}
.seg button{border:0;background:transparent;color:var(--mut);border-radius:7px;padding:5px 11px;font-size:12px;cursor:pointer;white-space:nowrap}
.seg button.on{background:#fff;color:var(--brand);font-weight:700;box-shadow:0 1px 4px rgba(20,30,60,.10)}
.lab{font-size:12px;color:var(--mut)}
.chartbox{padding:10px 12px 6px}
.chart{width:100%;height:380px}
.chart.sm{height:300px}
.stats{display:grid;grid-template-columns:repeat(5,1fr);border-top:1px solid var(--line);background:#fbfcff}
.stats div{padding:11px 15px;border-right:1px solid var(--line)}
.stats div:last-child{border-right:0}
.stats span{display:block;font-size:11px;color:var(--mut)}
.stats b{font-size:15.5px;font-weight:750;font-variant-numeric:tabular-nums}

/* ===== 热力图 / 表格 ===== */
.heat{display:grid;gap:3px;overflow-x:auto;padding:4px 0}
.heat .row{display:grid;grid-template-columns:52px repeat(12,minmax(34px,1fr));gap:3px}
.heat .cell{height:30px;border-radius:4px;display:grid;place-items:center;font-size:10.5px;
 font-variant-numeric:tabular-nums;color:#334}
.heat .yl{font-size:11.5px;color:var(--mut);display:grid;align-items:center;font-weight:600}
.heat .hd{font-size:11px;color:var(--mut);text-align:center;padding-bottom:2px}
.tw{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:12.5px;min-width:640px}
th,td{padding:9px 12px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
th:first-child,td:first-child{text-align:left}
thead th{background:#f7f9fd;color:var(--mut);font-weight:650;font-size:11.5px;position:sticky;top:0}
tbody tr:hover{background:#fafbff}
.leader{background:#fffbe8;font-weight:700;color:var(--gold)}
/* 调仓记录表 */
.rb-count{font-size:11px;font-weight:600;color:var(--mut);margin-left:6px}
.csv-dl{float:right;font-size:11.5px;font-weight:700;color:var(--navy);text-decoration:none;border:1px solid var(--line);border-radius:6px;padding:4px 10px}
.csv-dl:hover{background:#eef2f7;border-color:var(--gold)}
.rbtable{min-width:820px}
.rbtable.wide{min-width:1080px}
.rbtable td.eff{color:var(--mut);font-size:11.5px}
.rbtable td.desc{white-space:normal;min-width:150px;font-weight:600}
.rbtable td.hl-shelter{background:#fffbe8;color:#7a5a14;font-weight:700}
.rbtable tr.hl-shelter td.desc{color:#7a5a14}
.rbtable .tg{display:inline-block;font-size:10.5px;font-weight:700;border-radius:999px;padding:2px 8px;background:#eef2f7;color:var(--navy)}
.rbtable .tg.crash{background:#fdecea;color:#b3261e}
.rbtable .tg.both{background:#f6dda0;color:#7a5a14}
.rbtable .tg.early{background:#fff3d6;color:#8a6300}
.rbtable .tg.trend{background:#eaf1fb;color:#2c5282}
.rb-empty{padding:24px;text-align:center;color:var(--mut);font-size:13px}

/* ===== 调仓信号卡 / 目标仓位 ===== */
.rb{margin:0;border:1px solid var(--line);border-radius:10px;background:#fbfcff;overflow:hidden}
.rb.is-shelter{border-color:#e8b64c;background:#fffbe8}
.rb-hd{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:11px 14px;border-bottom:1px solid var(--line)}
.rb-hd .d{font-size:14px;font-weight:750;color:var(--navy)}
.rb-hd .flag{font-size:11px;font-weight:700;border-radius:999px;padding:3px 10px;background:#eef2f7;color:var(--navy)}
.rb.is-shelter .rb-hd .flag{background:#f6dda0;color:#7a5a14}
.rb-grid{display:grid;grid-template-columns:repeat(4,1fr)}
.rb-i{padding:10px 12px;border-right:1px solid var(--line)}
.rb-i:last-child{border-right:0}
.rb-i .k{font-size:10.5px;color:var(--mut);white-space:nowrap}
.rb-i .v{font-size:15px;font-weight:750;color:var(--navy);margin-top:3px;font-variant-numeric:tabular-nums;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rb-note{padding:9px 14px;font-size:11.5px;color:var(--mut);line-height:1.7;border-top:1px solid var(--line)}
.rb-note b{color:var(--gold)}
.wrow{display:grid;grid-template-columns:150px 1fr 64px;gap:10px;align-items:center;padding:8px 0;font-size:12.5px;border-bottom:1px solid var(--line)}
.wrow:last-child{border-bottom:0}
.wbar{height:16px;background:#eef2f7;border-radius:4px;overflow:hidden}
.wbar i{display:block;height:100%;border-radius:4px;background:linear-gradient(90deg,#2c5282,#4f7fb8)}
.wbar.bond i{background:linear-gradient(90deg,#b8860b,#e0b855)}
.wval{text-align:right;font-weight:700;font-variant-numeric:tabular-nums}

/* ===== 影子账户（旁路监管） ===== */
.sh-pills{display:flex;flex-wrap:wrap;gap:8px;padding:15px 16px}
.sh-pill{font-size:11.5px;background:#f7f9fc;border:1px solid var(--line);border-radius:999px;
 padding:4px 10px;color:#475569;white-space:nowrap}
.sh-pill b{font-variant-numeric:tabular-nums;color:var(--ink)}
.sh-pill.ok{background:#f1fbf5;border-color:#bfe6cf;color:#0b6b39}
.sh-pill.warn{background:#fffaef;border-color:#f0dcae;color:#7a5a14}
.sh-pill.err{background:#fff5f4;border-color:#f0c9c4;color:#a52a1e}
.sh-grid{display:grid;grid-template-columns:repeat(3,1fr)}
.sh-i{padding:11px 15px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}
.sh-i:nth-child(3n){border-right:0}
.sh-i .k{font-size:11px;color:var(--mut)}
.sh-i .v{font-size:17px;font-weight:800;color:var(--navy);font-variant-numeric:tabular-nums;margin-top:3px}
.sh-events{margin:0;padding:0;list-style:none;font-size:12px;line-height:1.9}
.sh-events li{padding:5px 0;border-bottom:1px solid var(--line)}
.sh-events li:last-child{border-bottom:0}
.sh-events .dt{color:var(--mut);font-variant-numeric:tabular-nums;margin-right:8px}
.sh-events .tp{font-weight:700;color:var(--navy);margin-right:6px}
.sh-legend{display:flex;gap:16px;flex-wrap:wrap;font-size:11.5px;color:var(--mut);padding:2px 12px 8px}
.sh-legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}

/* ===== 策略说明 ===== */
.about{font-size:13px;line-height:1.75;color:#33455f}
.about h3{margin:14px 0 6px;font-size:14px;color:var(--navy)}
.about ul{padding-left:20px}.about li{margin:4px 0}

footer{color:#8a99ab;font-size:12px;text-align:center;padding:26px 0 8px;margin-top:32px;border-top:1px solid var(--line)}

@media(max-width:640px){
 .sh-grid{grid-template-columns:repeat(2,1fr)}
 .sh-i:nth-child(3n){border-right:1px solid var(--line)}
 .sh-i:nth-child(2n){border-right:0}
}

/* ===== 响应式 ===== */
@media(max-width:980px){
 .kpis{grid-template-columns:repeat(3,1fr)}
 .kpi:nth-child(3n){border-right:0}.kpi:nth-child(6n){border-right:1px solid var(--line)}
 .kpi:nth-last-child(-n+3){border-bottom:0}
 .stats{grid-template-columns:repeat(3,1fr)}
}
@media(max-width:1180px){.topnav .wrap{gap:18px}.navlinks{margin-left:0}}
@media(max-width:980px){.topnav .wrap{gap:14px}.navlinks a{padding:10px 12px}
 .navlinks{mask-image:linear-gradient(90deg,#000 92%,transparent);-webkit-mask-image:linear-gradient(90deg,#000 92%,transparent)}}
@media(max-width:640px){
 .wrap{padding:0 12px 40px}
 .topnav .wrap{gap:10px;height:58px}
 .brand .mark{width:34px;height:34px;border-radius:10px;font-size:13px}
 .live{display:none}
 .kpis{grid-template-columns:repeat(2,1fr)}
 .kpi:nth-child(2n){border-right:0}.kpi:nth-child(3n){border-right:1px solid var(--line)}
 .kpi:nth-last-child(-n+2){border-bottom:0}.kpi .v{font-size:18px}
 .stats{grid-template-columns:repeat(2,1fr)}
 .navlinks{gap:0;margin-left:8px;mask-image:linear-gradient(90deg,#000 88%,transparent);
  -webkit-mask-image:linear-gradient(90deg,#000 88%,transparent)}
 .navlinks a{padding:9px 11px;font-size:13.5px}
 .chart{height:300px}.chart.sm{height:260px}
 .rb-grid{grid-template-columns:repeat(2,1fr)}
 .rb-i:nth-child(2){border-right:0}
 .rb-i:nth-child(-n+2){border-bottom:1px solid var(--line)}
 .wrow{grid-template-columns:110px 1fr 54px}
}
@media(max-width:380px){.brand .mark{width:32px;height:32px;font-size:12px}}
'''

ECHARTS = open(os.path.join(REF, 'echarts.min.js'), encoding='utf-8').read()

# 渲染 JS：复用原逻辑，但把 D 的组装改为 fetch 后注入；末尾初始化改为 async
RENDER = open(os.path.join(REF, 'board_render.js'), encoding='utf-8').read()
# 移除原末尾的直接渲染调用，改为由 fetch 流程驱动；并加入调仓信号卡
RENDER = RENDER.replace(
    'renderKpis();renderEquity();renderHeat();renderYear();renderAttrib();renderHold();',
    'window.__renderAll=function(){renderKpis();renderEquity();renderPit();renderHeat();renderYear();renderAttrib();renderRebalance();renderRebalanceLog();renderShadow();renderHold();};')

HTML = '''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>行业轮动增强 · 策略净值看板</title>
<style>__CSS__</style>
<script>__ECHARTS__</script>
</head><body>
<nav class="topnav"><div class="wrap">
  <div class="brand"><span class="mark">SR</span></div>
  <div class="navlinks" id="navlinks">
    <a href="#overview" class="on">绩效概览</a><a href="#equity">净值走势</a>
    <a href="#pit">爬坑体验</a><a href="#monthly">月度收益</a>
    <a href="#yearly">年度表现</a><a href="#attrib">收益归因</a>
    <a href="#holdings">目标仓位</a><a href="#shadow">影子账户</a><a href="#about">策略说明</a>
  </div>
  <div class="live" id="live"><i></i><span id="liveText">接口加载中</span></div>
</div></nav>

<div class="hero">
  <div class="wrap" style="padding-bottom:0">
    <div class="hero-eyebrow" id="hb_eyebrow">MOMENTUM STYLE ROTATION</div>
    <h1 id="hb_title">行业轮动增强<span class="dot">·</span>净值看板</h1>
    <div class="hero-sub" id="hb_sub">风格自适应动量轮动 × 回撤断路器 v1.0 —— 每日自动同步</div>
  </div>
</div>

<div class="wrap">
  <section class="sec" id="overview">
    <h2>绩效概览</h2>
    <div class="syncbar" id="syncbar">
      <div class="pills" id="syncPills"><span class="pill">数据加载中…</span></div>
      <button id="refreshBtn" title="刷新数据">↻ 刷新</button>
    </div>
    <div class="card"><div class="kpis" id="kpis"></div></div>
    <div class="note" id="basisNote"></div>
  </section>

  <section class="sec" id="equity">
    <h2>净值走势与基准对比</h2>
    <div class="card">
      <div class="ctrl"><span class="lab">区间</span>
        <div class="seg" id="range">
          <button data-r="1m">近1月</button><button data-r="3m">近3月</button>
          <button data-r="6m">近6月</button><button data-r="ytd">今年以来</button>
          <button data-r="1y">近1年</button><button data-r="3y">近3年</button>
          <button data-r="all" class="on">全部</button>
        </div>
        <span class="lab" id="rangeMeta"></span>
      </div>
      <div class="chartbox"><div id="eqChart" class="chart"></div></div>
      <div class="stats" id="eqStats"></div>
      <div class="body"><div class="note">两条净值均按区间首点归一化；红线为本策略、灰线为中证800业绩比较基准。红涨绿跌遵循 A 股习惯。</div></div>
    </div>
  </section>

  <section class="sec" id="pit">
    <h2>净值爬坑体验</h2>
    <div class="card">
      <div class="chartbox"><div id="ddChart" class="chart sm"></div></div>
      <div class="stats" id="ddStats"></div>
      <div class="body"><div class="note">水下面积为本策略净值距前高的回撤；最深回撤与修复等待按日频净值逐点计算，用于衡量「爬坑」体验。红涨绿跌遵循 A 股习惯。</div></div>
    </div>
  </section>

  <section class="sec" id="monthly">
    <h2>月度收益热力图</h2>
    <div class="card"><div class="body">
      <div class="heat" id="heat"></div>
      <div class="note">红涨绿跌（A 股习惯）；色深按当月幅度相对全样本最大月收益线性映射。数据由真实净值序列现场计算。</div>
    </div></div>
  </section>

  <section class="sec" id="yearly">
    <h2>年度表现</h2>
    <div class="card"><h3>分年统计</h3><div class="tw"><table>
      <thead><tr><th>年份</th><th>策略收益</th><th>中证800</th><th>超额</th><th>最大回撤</th><th>波动</th><th>夏普</th><th>卡玛</th></tr></thead>
      <tbody id="yearBody"></tbody></table></div>
      <div class="body"><div class="note">按自然年统计；2020 与 2026 为不足整年区间，年化类指标不做跨年外推。</div></div>
    </div></section>

  <section class="sec" id="attrib">
    <h2>年度收益归因</h2>
    <div class="card"><h3>各资产年度累计贡献</h3>
      <div class="body"><div class="note" id="attrNote" style="margin:0"></div></div>
      <div class="chartbox"><div id="attrChart" class="chart sm"></div></div>
      <div class="tw"><table><thead id="attrThead"></thead><tbody id="attrBody"></tbody></table></div>
    </div></section>

  <section class="sec" id="holdings">
    <h2>目标仓位与调仓信号</h2>
    <div class="card"><h3>最近调仓信号</h3><div class="body"><div id="rebalanceSignal"></div></div></div>
    <div class="card" style="margin-top:14px"><h3 id="holdTitle">目标仓位</h3><div class="body"><div id="holdBars"></div></div></div>
    <div class="card" style="margin-top:14px">
      <h3>最近调仓记录 <span class="rb-count" id="rbCount"></span>
        <a class="csv-dl" href="data/rebalances.CSV" download="rebalances.CSV" title="下载完整调仓记录">↓ 完整CSV</a></h3>
      <div class="ctrl" style="padding:10px 14px 0">
        <span class="lab">类型</span>
        <div class="seg" id="rbFilter">
          <button data-f="all" class="on">全部</button><button data-f="crash">Crash</button>
          <button data-f="both">双重</button><button data-f="early">提前</button><button data-f="trend">趋势</button>
          <button data-f="shelter">避险</button>
        </div>
      </div>
      <div class="tw"><table class="rbtable wide"><thead><tr>
        <th>信号日T</th><th>生效日T+1</th><th>触发</th><th>风险</th>
        <th>目标描述</th><th>生效日实际持仓</th><th>门控</th>
        <th>市场回撤</th><th>ER</th><th>避险仓</th>
      </tr></thead><tbody id="rbBody"></tbody></table></div>
      <div class="body"><div class="note">表格默认显示<b>最近 20 条</b>（按信号日倒序），<b>全部记录请下载「完整CSV」</b>；筛选按全部记录匹配后再取最近 20 条。数据来自 v1.0 真实信号日志。<b>T 日收盘产生信号、T+1 成交</b>：「生效日」为数据轴上信号日的下一个交易日；「目标描述」区分纯风格 / 风格+国债按比例 / 100%国债；「实际持仓」为生效日从权重表读取的真实仓位，用于核对目标是否落地。Early（动能减速）在此版只记录不触发避险；「避险」筛选为避险仓位&gt;0 的记录。</div></div>
    </div>
  </section>

  <section class="sec" id="shadow">
    <h2>影子账户进化学习（旁路监控）</h2>
    <div id="shadowBody"><div class="note">影子账户数据加载中…</div></div>
  </section>

  <section class="sec" id="about">
    <h2>策略说明与因子规则</h2>
    <div class="card"><div class="body about" id="aboutBody"></div></div>
  </section>

  <footer>数据来自 v1.0 真实回测 · 中证800 仅作业绩比较基准 · 历史表现不代表未来，不构成投资建议</footer>
</div>
<script>
__RENDER__
// ===== 调仓信号卡：展示最近一次调仓的触发/风控/目标风格 =====
function renderRebalance(){
  var box=document.getElementById('rebalanceSignal');
  if(!box||!D.rebalances||!D.rebalances.length){if(box)box.innerHTML='';return;}
  var r=D.rebalances[D.rebalances.length-1];
  var flagMap={crash:'Momentum Crash',both:'双重触发',early:'提前避险',trend:'趋势切换',nan:'常规轮动',hedge:'对冲'};
  var flag=flagMap[r.trigger]||r.trigger||'—';
  var shelter=Number(r.shelter_w||0)>0;
  var riskOff=(r.risk==='OFF');
  var cb=Number(r.cb_sh||0)>0;
  box.innerHTML=
    '<div class="rb'+(shelter?' is-shelter':'')+'">'+
      '<div class="rb-hd"><span class="d">最近调仓 · '+r.date+'</span>'+
        '<span class="flag">'+(shelter?'退守避险 · 国债ETF':'目标 '+r.holdings)+'</span></div>'+
      '<div class="rb-grid">'+
        '<div class="rb-i"><div class="k">触发类型</div><div class="v">'+flag+'</div></div>'+
        '<div class="rb-i"><div class="k">风格信号</div><div class="v">'+r.holdings+'</div></div>'+
        '<div class="rb-i"><div class="k">门控 gate</div><div class="v">'+Number(r.gate||0).toFixed(2)+'</div></div>'+
        '<div class="rb-i"><div class="k">市场回撤</div><div class="v '+cls(r.mkt_dd)+'">'+pct(r.mkt_dd||0,1)+'</div></div>'+
      '</div>'+
      '<div class="rb-note">'+风险解读(r,shelter,riskOff,cb,flag)+'</div>'+
    '</div>';
}
function 风险解读(r,shelter,riskOff,cb,flag){
  if(shelter){
    return '当前目标 <b>100% 国债ETF 511010</b>（绝对避险）：'+flag+' 触发'+(cb?' + 回撤断路器满仓国债':'')+
      '，门控降至 '+Number(r.gate||0).toFixed(2)+'，不押风格；市场回撤 '+pct(r.mkt_dd||0,1)+'。';
  }
  return '当前目标 <b>'+r.holdings+'</b>（风格信号生效），风险状态 '+(riskOff?'OFF':'ON')+
    '，门控 '+Number(r.gate||0).toFixed(2)+'，T+1 收盘执行。';
}
// ===== 调仓记录表：全部信号日，倒序，可按类型筛选 =====
var RB_FILTER='all';
var TRIG_ZH={crash:'Crash',both:'双重',early:'提前',trend:'趋势',nan:'常规',hedge:'对冲'};
function renderRebalanceLog(){
  var body=document.getElementById('rbBody');if(!body)return;
  var all=(D.rebalances||[]).slice().reverse();  // 倒序：最近在前
  var rows=all.filter(function(r){
    if(RB_FILTER==='all')return true;
    if(RB_FILTER==='shelter')return Number(r.shelter_w||0)>0;
    return String(r.trigger)===RB_FILTER;
  });
  var LIMIT=20, shown=rows.slice(0,LIMIT);  // 仅显示最近20条，完整记录见CSV
  document.getElementById('rbCount').textContent = rows.length>LIMIT
    ? '共 '+all.length+' 次 · 仅显示最近 '+LIMIT+' 条'
    : '共 '+all.length+' 次 · 显示 '+rows.length+' 条';
  if(!shown.length){body.innerHTML='<tr><td colspan="10" class="rb-empty">该类型暂无调仓记录</td></tr>';return;}
  var fnum=function(v,n){return (v===null||v===undefined)?'—':Number(v).toFixed(n);};
  body.innerHTML=shown.map(function(r){
    var tg=String(r.trigger), tgCls=['crash','both','early','trend'].indexOf(tg)>=0?tg:'';
    var shelter=Number(r.shelter_w||0)>0;
    var desc=r.target_desc||((r.holdings||'—')+' 100%');
    var actual=r.actual||'—';
    return '<tr'+(!shelter?'':' class="hl-shelter"')+'>'+
      '<td>'+r.date+'</td>'+
      '<td class="eff">'+r.eff_date+'</td>'+
      '<td><span class="tg '+tgCls+'">'+(TRIG_ZH[tg]||tg||'—')+'</span></td>'+
      '<td>'+(r.risk||'—')+'</td>'+
      '<td class="desc">'+desc+'</td>'+
      '<td class="desc">'+actual+'</td>'+
      '<td>'+fnum(r.gate,2)+'</td>'+
      '<td class="'+cls(r.mkt_dd)+'">'+((r.mkt_dd===null||r.mkt_dd===undefined)?'—':pct(r.mkt_dd,1))+'</td>'+
      '<td>'+fnum(r.er,3)+'</td>'+
      '<td>'+fnum(r.shelter_w,2)+'</td>'+
    '</tr>';
  }).join('');
}
// ===== 净值爬坑体验：水下回撤面积 + 修复统计 =====
const ddChart=echarts.init(document.getElementById("ddChart"));
function renderPit(){
  const dates=D.dates, dd=D.dd;
  // 最深回撤及其区间、修复等待
  let mddIdx=0,mdd=0;for(let i=0;i<dd.length;i++){if(dd[i]<mdd){mdd=dd[i];mddIdx=i;}}
  // 高点索引：最深回撤点之前最近一次 dd≈0 的交易日
  let peakIdx=mddIdx;while(peakIdx>0&&dd[peakIdx]<-0.0005)peakIdx--;
  const fallDays=mddIdx-peakIdx;
  // 修复：最深点之后首次回撤回到 0 的交易日
  let recIdx=-1;for(let j=mddIdx+1;j<dd.length;j++){if(dd[j]>=-0.0005){recIdx=j;break;}}
  const recoverDays=recIdx>=0?recIdx-mddIdx:null;
  const pctD=x=>pct(x,1);
  document.getElementById("ddStats").innerHTML=[
    ["区间最深回撤",pctD(mdd),"down"],
    ["发生日期",dates[mddIdx],"flat"],
    ["下跌历时",fallDays+" 交易日","flat"],
    ["修复等待",recIdx>=0?(recoverDays+" 交易日"):"尚未修复",recIdx>=0?"flat":"down"],
    ["当前回撤",pctD(dd[dd.length-1]),dd[dd.length-1]<0?"down":"flat"]
  ].map(k=>`<div><span>${k[0]}</span><b class="${k[2]}">${k[1]}</b></div>`).join("");
  ddChart.setOption({
    backgroundColor:"transparent",
    tooltip:{trigger:"axis",backgroundColor:"#101b30",borderColor:"#2a4d7d",textStyle:{color:"#fff"},
      formatter:ps=>ps[0].axisValue+"<br>回撤：<b>"+pct(ps[0].value,2)+"</b>"},
    grid:{left:56,right:18,top:16,bottom:24},
    xAxis:{type:"category",data:dates,axisLine:{lineStyle:{color:"#dde4ec"}},axisLabel:{color:MUT}},
    yAxis:{type:"value",max:0,axisLine:{lineStyle:{color:"#dde4ec"}},axisLabel:{color:MUT,formatter:v=>(v*100).toFixed(0)+"%"},
      splitLine:{lineStyle:{color:"#eef1f5"}}},
    series:[{name:"回撤",type:"line",data:dd,symbol:"none",lineStyle:{width:1.2,color:DOWN},
      areaStyle:{color:"rgba(15,157,88,.22)"},
      markPoint:{symbol:"pin",symbolSize:38,data:[{coord:[mddIdx,mdd],value:pctD(mdd)}],
        itemStyle:{color:DOWN},label:{color:"#fff",fontSize:10,formatter:p=>p.value}}}]
  },true);
}
// ===== 影子账户（旁路监管）：状态/净值/绩效/事件，字段来自 evolution.json =====
let shadowChart=null;
const SH_COLORS=["#8a99ab","#c0392b","#2c5282","#7fa0c4","#27ae60","#b8860b"];
function renderShadow(){
  const E=D.evolution;
  const box=document.getElementById("shadowBody");
  if(!E||!E.available){box.innerHTML='<div class="note">影子账户数据暂不可用。</div>';return;}
  const champion="冠军v1.0";
  const cand=E.better_than_champion&&E.better_than_champion[0]||E.final_leader;
  const leader=E.final_leader;
  // 状态 pills
  let pills='<div class="card"><div class="sh-pills">'+E.pills.map(p=>
    '<span class="sh-pill '+(p.cls||'')+'">'+p.k+' <b>'+p.v+'</b></span>').join("")+'</div></div>';
  // 净值对比图（冠军 / 当期领先 / 全区间跑赢者）
  const showNames=[champion,leader,cand].filter((v,i,a)=>a.indexOf(v)===i);
  pills+='<div class="card" style="margin-top:14px"><h3>历史回灌演练净值：有效 / 固定 / 候选参数</h3>'+
    '<div class="chartbox"><div id="shadowChart" class="chart sm"></div></div>'+
    '<div class="sh-legend">'+showNames.map((n,i)=>'<span><i style="background:'+SH_COLORS[E.names.indexOf(n)]+'"></i>'+n+'</span>').join("")+'</div>'+
    '</div>';
  // 绩效指标
  const m=E.metrics||{};
  const pick=(n,k)=>m[n]&&m[n][k]!=null?pct(m[n][k],2):"—";
  pills+='<div class="card" style="margin-top:14px"><div class="sh-grid">'+
    '<div class="sh-i"><div class="k">冠军样本外 CAGR</div><div class="v">'+pick(champion,"cagr")+'</div></div>'+
    '<div class="sh-i"><div class="k">候选样本外 CAGR</div><div class="v">'+pick(cand,"cagr")+'</div></div>'+
    '<div class="sh-i"><div class="k">当期领先 CAGR</div><div class="v">'+pick(leader,"cagr")+'</div></div>'+
    '<div class="sh-i"><div class="k">冠军 Sharpe</div><div class="v">'+(m[champion]?nf(m[champion].sharpe,3):"—")+'</div></div>'+
    '<div class="sh-i"><div class="k">候选 Sharpe</div><div class="v">'+(m[cand]?nf(m[cand].sharpe,3):"—")+'</div></div>'+
    '<div class="sh-i"><div class="k">解除降级门槛</div><div class="v" style="font-size:13px">'+E.degrade_gate+'</div></div>'+
    '<div class="sh-i"><div class="k">演练月数</div><div class="v">'+E.months+'</div></div>'+
    '<div class="sh-i"><div class="k">评估期 / 晋升</div><div class="v">'+E.n_eval+' / '+E.n_promote+'</div></div>'+
    '<div class="sh-i"><div class="k">IC反转 / 退化预警</div><div class="v">'+E.n_icrev+' / '+E.n_decay+'</div></div>'+
    '</div></div>';
  // Q 演化 + 事件时间线
  const evs=(E.events||[]).slice(-6).reverse().map(e=>
    '<li><span class="dt">'+e.date+'</span><span class="tp">'+e.type+'</span>'+e.detail+'</li>').join("");
  pills+='<div class="grid2" style="margin-top:14px">'+
    '<div class="card"><h3>近期监管事件</h3><div class="body"><ul class="sh-events">'+(evs||'<li>暂无事件</li>')+'</ul></div></div>'+
    '<div class="card"><h3>挑战者终值信誉 Q</h3><div class="body"><ul class="sh-events">'+
      Object.entries(E.final_Q||{}).map(([k,v])=>'<li><span class="tp">'+k+'</span><b class="'+(v>=0?"up":"down")+'">'+nf(v,3)+'</b></li>').join("")+
    '</ul><div class="note">Q 为 EWMA 在线信誉，正值为净领先；排名仅作提名，不自动切换。</div></div></div>'+
    '</div>';
  // 诚实边界
  pills+='<div class="card" style="margin-top:14px"><div class="body"><div class="note" style="margin:0">'+E.honest+'</div></div></div>';
  box.innerHTML=pills;
  // 画净值图（DOM 注入后初始化）
  const scEl=document.getElementById("shadowChart");
  const sc=echarts.getInstanceByDom(scEl)||echarts.init(scEl);
  shadowChart=sc;
  sc.setOption({
    backgroundColor:"transparent",
    tooltip:{trigger:"axis",backgroundColor:"#101b30",borderColor:"#2a4d7d",textStyle:{color:"#fff"},
      formatter:ps=>{let s=ps[0].axisValue+"<br>";ps.forEach(p=>s+=p.marker+p.seriesName+"："+nf(p.value,3)+"<br>");return s;}},
    legend:{data:showNames,top:0,textStyle:{color:MUT},type:"scroll"},
    grid:{left:56,right:18,top:34,bottom:24},
    xAxis:{type:"category",data:E.dates,axisLine:{lineStyle:{color:"#dde4ec"}},axisLabel:{color:MUT}},
    yAxis:{type:"value",scale:true,axisLine:{lineStyle:{color:"#dde4ec"}},axisLabel:{color:MUT,formatter:v=>nf(v,2)},
      splitLine:{lineStyle:{color:"#eef1f5"}}},
    series:showNames.map(n=>({name:n,type:"line",data:(E.nav[n]||[]),symbol:"none",
      lineStyle:{width:n===champion?2.2:1.5,color:SH_COLORS[E.names.indexOf(n)]},
      itemStyle:{color:SH_COLORS[E.names.indexOf(n)]}}))
  },true);
}
// ===== fetch 同源接口并组装 D =====
async function loadData(){
  const base='data/';
  const opt={cache:'no-store'};
  const [meta,nav,sig,hold,attr,evo]=await Promise.all([
    fetch(base+'meta.json',opt).then(r=>r.json()),
    fetch(base+'nav.json',opt).then(r=>r.json()),
    fetch(base+'signal.json',opt).then(r=>r.json()),
    fetch(base+'holdings.json',opt).then(r=>r.json()),
    fetch(base+'attribution.json',opt).then(r=>r.json()),
    fetch(base+'evolution.json',opt).then(r=>r.json()).catch(()=>({available:false}))
  ]);
  const hy=nav.year_full||nav.yearly.map(y=>({year:y.year,ret:y.strategy,z800:y.benchmark,
    excess:y.strategy-y.benchmark,mdd:0,vol:0,sharpe:0,calmar:0}));
  D={
    meta:{version:meta.version,name:meta.name,start:meta.start,end:meta.end,
          n_days:meta.bars,winrate:nav.monthly_winrate,last_signal:hold.as_of},
    dates:nav.dates,nav:nav.strategy,z800:nav.benchmark,dd:nav.drawdown,
    heat:nav.monthly,years:hy,attribution:attr,
    holdings:Object.fromEntries(hold.positions.map(p=>[p.asset,p.weight])),
    rebalances:hold.rebalances||[],
    evolution:evo
  };
  // 同步状态
  const s=meta.sync||{};
  const stale=(()=>{if(!s.last_sync)return true;
    return (Date.now()-new Date(s.last_sync).getTime())/3600000>26;})();
  const stateCls=(s.status==='fallback'||stale)?'err':(s.status==='skipped'?'warn':'ok');
  const conv=String(meta.price_convention||'').slice(0,18);
  document.getElementById('syncPills').innerHTML=
    '<span class="pill ok">净值截至 <b>'+meta.as_of+'</b></span>'+
    '<span class="pill">交易日 <b>'+meta.bars+'</b></span>'+
    '<span class="pill">口径 <b>全收益/价格指数</b></span>'+
    '<span class="pill '+stateCls+'">同步 '+(s.status||'—')+(stateCls==='ok'?' OK':'')+'</span>';
  const live=document.getElementById('live');
  live.className='live '+(stateCls==='err'?'bad':(stateCls==='warn'?'warn':''));
  document.getElementById('liveText').textContent='每日同步 · '+meta.as_of;
  // hero 动态数字
  try{
    const full=statsOf(D.nav,D.dd);
    document.getElementById('hb_sub').innerHTML='风格自适应动量轮动 × 回撤断路器 v1.0 —— 累计 <b>'+pct(full.total)+
      '</b> · 年化 <b>'+pct(full.ann)+'</b> · 最大回撤 <b>'+pct(full.mdd)+'</b>';
  }catch(e){}
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
// 调仓记录类型筛选
document.getElementById('rbFilter').addEventListener('click',function(e){
  var b=e.target.closest('button');if(!b)return;
  RB_FILTER=b.dataset.f;
  this.querySelectorAll('button').forEach(function(x){x.classList.toggle('on',x===b);});
  renderRebalanceLog();
});
window.addEventListener('resize',()=>{try{ddChart.resize();}catch(e){}try{if(shadowChart)shadowChart.resize();}catch(e){}});
loadData().catch(e=>{
  document.getElementById('syncPills').innerHTML='<span class="pill err">数据加载失败：'+e.message+'</span>';
  document.getElementById('live').className='live bad';
});
</script>
</body></html>'''

HTML = (HTML.replace('__CSS__', CSS).replace('__ECHARTS__', ECHARTS)
        .replace('__RENDER__', RENDER))
out = os.path.join(BASE, 'index.html')
with open(out, 'w', encoding='utf-8') as f:
    f.write(HTML)
print(f'[完成] index.html 生成: {len(HTML)} 字节 (内联ECharts+fetch同源接口)')
