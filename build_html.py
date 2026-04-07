#!/usr/bin/env python3
"""
staffing_monitor/build_html.py
data/ フォルダの実データから、エリア切り替えプルダウン付きHTMLレポートを生成するスクリプト

使い方:
    python3 build_html.py                           # デフォルト3エリア（東京都・大阪府・神奈川県）
    python3 build_html.py 東京都                    # 1エリアのみ
    python3 build_html.py 東京都 大阪府 神奈川県   # 任意の複数エリア指定
"""

import json
import sys
from pathlib import Path
from datetime import datetime

# 実データ開始日（YYYY-MM-DD形式。デモデータ=週次ファイルは自動除外）
REAL_DATA_START = "2026-03-01"

# デフォルト対象エリア
DEFAULT_REGIONS = ["東京都", "大阪府", "神奈川県"]


def load_real_data(data_dir: Path, region: str) -> list[dict]:
    """指定エリアのJSONを読み込む（日次ファイル YYYY-MM-DD のみ）"""
    safe = region.replace("/", "_").replace("・", "_")
    rows = []
    for f in sorted(data_dir.glob(f"*_{safe}.json")):
        try:
            label = f.stem.split("_")[0]
            # YYYY-MM-DD 形式のみ対象（週次 YYYY-WXX はデモデータなのでスキップ）
            if not label.count("-") == 2:
                continue
            if label < REAL_DATA_START:
                continue
            obj = json.loads(f.read_text(encoding="utf-8"))
            scraped_at = obj.get("scraped_at", "")[:10]
            date_label = scraped_at or label  # YYYY-MM-DD
            row = {"date": date_label, "scraped_at": scraped_at}
            for r in obj.get("results", []):
                row[r["company_id"]] = {
                    "count": r.get("count"),
                    "wage":  r.get("avg_wage"),
                }
            rows.append(row)
        except Exception:
            pass
    return rows


def build_html(regions=None):
    # monitor.py から文字列で呼ばれた場合（例: build_html("大阪府")）は
    # 常にデフォルト3エリアで生成してプルダウンを維持する
    if regions is None or isinstance(regions, str):
        regions = DEFAULT_REGIONS

    data_dir = Path(__file__).parent / "data"
    out_path = Path(__file__).parent / "monitoring_report.html"

    # 全エリアのデータを読み込む
    all_data = {}
    for region in regions:
        records = load_real_data(data_dir, region)
        all_data[region] = records
        if records:
            print(f"📂 {region}: {len(records)} 日分のデータを読み込みました（{records[0]['date']} ～ {records[-1]['date']}）")
        else:
            print(f"⚠️  {region}: データが見つかりません")

    # データが1件もない場合は終了
    if all(len(v) == 0 for v in all_data.values()):
        print("⚠️  全エリアのデータが見つかりません")
        return

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    js_all_data = json.dumps(all_data, ensure_ascii=False)
    js_regions  = json.dumps(regions, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>事務派遣 競合モニタリング｜ManpowerGroup</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Hiragino Sans', 'Yu Gothic UI', 'Meiryo', sans-serif; background: #f0f2f6; color: #1a1a2e; }}

  /* ── ヘッダー ── */
  .header {{ background: linear-gradient(135deg, #0d1b5e 0%, #1a3a8f 100%); color: #fff; padding: 18px 24px; display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }}
  .header-left h1 {{ font-size: 1.1rem; font-weight: 700; letter-spacing: 0.02em; }}
  .header-left p  {{ font-size: 0.75rem; opacity: 0.7; margin-top: 3px; }}
  .header-right   {{ text-align: right; font-size: 0.75rem; opacity: 0.8; line-height: 1.7; flex-shrink: 0; }}
  .badge-live     {{ display: inline-block; background: #00c896; color: #fff; font-size: 0.65rem; font-weight: 700; padding: 2px 7px; border-radius: 10px; margin-bottom: 3px; }}

  /* ── エリア切り替え ── */
  .region-bar {{ background: #fff; border-bottom: 2px solid #e8eaf0; padding: 12px 24px; display: flex; align-items: center; gap: 12px; position: sticky; top: 0; z-index: 100; box-shadow: 0 2px 8px rgba(0,0,0,0.06); flex-wrap: wrap; }}
  .region-bar label {{ font-size: 0.78rem; font-weight: 700; color: #555; white-space: nowrap; }}
  .region-select {{ font-size: 0.92rem; font-weight: 700; color: #0d1b5e; background: #f0f4ff; border: 2px solid #1a3a8f; border-radius: 8px; padding: 6px 32px 6px 12px; cursor: pointer; appearance: none; -webkit-appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='%231a3a8f' stroke-width='2' fill='none' stroke-linecap='round'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 10px center; min-width: 160px; }}
  .region-select:focus {{ outline: none; border-color: #0d1b5e; box-shadow: 0 0 0 3px rgba(13,27,94,0.15); }}
  .region-data-note {{ font-size: 0.7rem; color: #aaa; margin-left: auto; }}

  /* ── 日付フィルタ ── */
  .date-bar {{ background: #f7f8fc; border-bottom: 1px solid #e8eaf0; padding: 8px 24px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
  .date-bar label {{ font-size: 0.75rem; font-weight: 700; color: #555; white-space: nowrap; }}
  .date-input {{ font-size: 0.82rem; color: #333; background: #fff; border: 1px solid #c8cfe0; border-radius: 6px; padding: 4px 8px; cursor: pointer; }}
  .date-input:focus {{ outline: none; border-color: #1a3a8f; box-shadow: 0 0 0 2px rgba(13,27,94,0.12); }}
  .date-sep {{ font-size: 0.8rem; color: #888; }}
  .preset-btns {{ display: flex; gap: 6px; margin-left: 8px; flex-wrap: wrap; }}
  .preset-btn {{ font-size: 0.72rem; font-weight: 600; padding: 3px 10px; border-radius: 12px; border: 1px solid #c8cfe0; background: #fff; color: #555; cursor: pointer; transition: all 0.15s; }}
  .preset-btn:hover {{ background: #e8eeff; border-color: #1a3a8f; color: #1a3a8f; }}
  .preset-btn.active {{ background: #1a3a8f; border-color: #1a3a8f; color: #fff; }}
  .filter-note {{ font-size: 0.7rem; color: #aaa; margin-left: auto; }}

  /* ── お知らせ ── */
  .notice {{ background: #e8f5e9; border-left: 4px solid #43a047; padding: 10px 24px; font-size: 0.78rem; color: #1b5e20; }}
  .notice-warn {{ background: #fff3e0; border-left: 4px solid #fb8c00; padding: 10px 24px; font-size: 0.78rem; color: #e65100; display: none; }}

  /* ── セクションラベル ── */
  .section-label {{ padding: 18px 24px 8px; font-size: 0.7rem; font-weight: 700; color: #8892a4; letter-spacing: 0.1em; text-transform: uppercase; }}

  /* ── KPIカード ── */
  .kpi-row {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; padding: 0 24px 4px; }}
  .kpi-card {{ background: #fff; border-radius: 10px; padding: 14px 16px; box-shadow: 0 1px 6px rgba(0,0,0,0.07); border-top: 4px solid #ccc; }}
  .kpi-card .co-name {{ font-size: 0.7rem; color: #777; font-weight: 600; margin-bottom: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .kpi-card .count   {{ font-size: 1.6rem; font-weight: 800; line-height: 1; }}
  .kpi-card .wage    {{ font-size: 0.82rem; font-weight: 600; margin-top: 6px; color: #444; }}
  .kpi-card .delta   {{ font-size: 0.7rem; margin-top: 4px; }}
  .delta.up   {{ color: #e53935; }} .delta.down {{ color: #1e88e5; }} .delta.flat {{ color: #aaa; }}
  .c-tempstaff   {{ border-top-color: #e84040; }} .c-recruit  {{ border-top-color: #2e75b6; }}
  .c-staffsvc    {{ border-top-color: #375623; }} .c-adecco   {{ border-top-color: #f4a100; }}
  .c-manpower    {{ border-top-color: #7030a0; }}

  /* ── グラフ ── */
  .charts-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 8px 24px 0; }}
  .chart-card {{ background: #fff; border-radius: 10px; padding: 18px; box-shadow: 0 1px 6px rgba(0,0,0,0.07); }}
  .chart-card h3 {{ font-size: 0.85rem; font-weight: 700; color: #333; margin-bottom: 2px; }}
  .chart-card .sub {{ font-size: 0.7rem; color: #aaa; margin-bottom: 12px; }}
  .chart-wrap {{ position: relative; height: 220px; }}

  /* ── テーブル ── */
  .table-section {{ margin: 12px 24px 28px; background: #fff; border-radius: 10px; box-shadow: 0 1px 6px rgba(0,0,0,0.07); overflow: hidden; }}
  .table-section .t-header {{ padding: 14px 18px 10px; display: flex; align-items: baseline; gap: 10px; border-bottom: 1px solid #eee; flex-wrap: wrap; }}
  .table-section .t-header h3 {{ font-size: 0.88rem; font-weight: 700; color: #333; }}
  .table-section .t-header span {{ font-size: 0.7rem; color: #aaa; }}
  .table-scroll {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
  th {{ background: #f7f8fc; padding: 9px 14px; text-align: left; color: #666; font-weight: 600; border-bottom: 2px solid #eee; white-space: nowrap; }}
  td {{ padding: 10px 14px; border-bottom: 1px solid #f0f0f0; vertical-align: middle; white-space: nowrap; }}
  tr:last-child td {{ border-bottom: none; }}
  .co-label {{ max-width: 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block; vertical-align: middle; }}
  .dot {{ display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 5px; vertical-align: middle; flex-shrink: 0; }}
  .num {{ font-weight: 700; font-size: 0.95rem; }}
  .rank {{ display: inline-block; width: 22px; height: 22px; border-radius: 50%; background: #eee; color: #777; font-size: 0.7rem; font-weight: 700; text-align: center; line-height: 22px; }}
  .rank-1 {{ background: #ffd700; color: #7a5000; }} .rank-2 {{ background: #c0c0c0; color: #444; }} .rank-3 {{ background: #cd7f32; color: #fff; }}

  footer {{ text-align: center; padding: 16px; font-size: 0.7rem; color: #bbb; }}

  @media (max-width: 600px) {{
    .header {{ flex-direction: column; align-items: flex-start; padding: 14px 16px; gap: 8px; }}
    .header-left h1 {{ font-size: 0.95rem; }}
    .header-right {{ text-align: left; }}
    .region-bar {{ padding: 10px 16px; }}
    .kpi-row {{ grid-template-columns: repeat(2, 1fr); padding: 0 16px 4px; gap: 8px; }}
    .kpi-card .count {{ font-size: 1.35rem; }}
    .charts-grid {{ grid-template-columns: 1fr; padding: 8px 16px 0; gap: 10px; }}
    .chart-wrap {{ height: 200px; }}
    .table-section {{ margin: 10px 16px 24px; }}
    table {{ font-size: 0.75rem; }}
    th, td {{ padding: 8px 10px; }}
    .section-label {{ padding: 14px 16px 6px; }}
    .notice, .notice-warn {{ padding: 10px 16px; font-size: 0.75rem; }}
  }}
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <h1>📊 事務派遣 競合モニタリング</h1>
    <p>事務系派遣求人：5社比較（案件数・平均時給）</p>
  </div>
  <div class="header-right">
    <div class="badge-live">● LIVE DATA</div><br>
    生成：{generated_at}
  </div>
</div>

<!-- エリア切り替えバー -->
<div class="region-bar">
  <label for="regionSelect">📍 エリア：</label>
  <select id="regionSelect" class="region-select" onchange="switchRegion(this.value)"></select>
  <span class="region-data-note" id="dataNote"></span>
</div>

<!-- 日付フィルタバー -->
<div class="date-bar">
  <label>📅 期間：</label>
  <input type="date" id="dateFrom" class="date-input" onchange="applyDateFilter()">
  <span class="date-sep">〜</span>
  <input type="date" id="dateTo" class="date-input" onchange="applyDateFilter()">
  <div class="preset-btns">
    <button class="preset-btn" onclick="setPreset(7)">直近7日</button>
    <button class="preset-btn" onclick="setPreset(30)">直近30日</button>
    <button class="preset-btn active" id="btnAll" onclick="setPreset(0)">全期間</button>
  </div>
  <span class="filter-note" id="filterNote"></span>
</div>

<div class="notice">
  ✅ <strong>実データのみ表示。</strong>毎日11時のクローリング後に自動更新されます。
</div>
<div class="notice-warn" id="noDataWarn">
  ⚠️ このエリアの本日分データはまだ収集されていません。
</div>

<div class="section-label" id="kpiLabel">最新日 KPI</div>
<div class="kpi-row" id="kpiRow"></div>

<div class="section-label" id="chartLabel">日次推移</div>
<div class="charts-grid">
  <div class="chart-card">
    <h3>案件数 推移</h3>
    <div class="sub" id="countSub">各社の派遣求人掲載件数</div>
    <div class="chart-wrap"><canvas id="chartCount"></canvas></div>
  </div>
  <div class="chart-card">
    <h3>平均時給 推移</h3>
    <div class="sub">掲載求人の平均時給（円）</div>
    <div class="chart-wrap"><canvas id="chartWage"></canvas></div>
  </div>
</div>

<div class="section-label">最新日 詳細ランキング</div>
<div class="table-section">
  <div class="t-header">
    <h3>案件数ランキング</h3>
    <span id="tableDate"></span>
  </div>
  <div class="table-scroll">
    <table>
      <thead>
        <tr>
          <th>順位</th><th>企業名</th>
          <th style="text-align:right">案件数</th><th style="text-align:right">シェア</th>
          <th style="text-align:right">平均時給</th><th style="text-align:right">前日比</th>
        </tr>
      </thead>
      <tbody id="tableBody"></tbody>
    </table>
  </div>
</div>

<footer>ManpowerGroup 事務派遣モニタリングツール ｜ 毎日11時 自動更新</footer>

<script>
// ── 全エリアデータ ──────────────────────────────────────────────
const ALL_DATA    = {js_all_data};
const REGIONS     = {js_regions};
const COMPANIES   = [
  {{ id: "tempstaff",        name: "テンプスタッフ",         color: "#e84040", cls: "c-tempstaff" }},
  {{ id: "recruit_staffing", name: "リクルートスタッフィング", color: "#2e75b6", cls: "c-recruit"   }},
  {{ id: "staff_service",    name: "スタッフサービス",        color: "#375623", cls: "c-staffsvc"  }},
  {{ id: "adecco",           name: "アデコ",                 color: "#f4a100", cls: "c-adecco"    }},
  {{ id: "manpower",         name: "マンパワーグループ",       color: "#7030a0", cls: "c-manpower"  }},
];

// ── チャートインスタンス ─────────────────────────────────────────
let chartCount = null;
let chartWage  = null;

// ── ユーティリティ ───────────────────────────────────────────────
const fmt   = n  => n != null ? n.toLocaleString() : "—";
const fmtY  = n  => n != null ? `¥${{n.toLocaleString()}}` : "—";
const pct   = (a, b) => b ? (((a - b) / b) * 100).toFixed(1) : null;

// ── セレクトボックスを初期化 ─────────────────────────────────────
const sel = document.getElementById("regionSelect");
REGIONS.forEach(r => {{
  const opt = document.createElement("option");
  opt.value = r; opt.textContent = r;
  sel.appendChild(opt);
}});

// ── 現在のエリア ─────────────────────────────────────────────────
let currentRegion = REGIONS[0];

// ── 日付フィルタ ─────────────────────────────────────────────────
function getFilteredRecords(region) {{
  const all = ALL_DATA[region] || [];
  const from = document.getElementById("dateFrom").value;
  const to   = document.getElementById("dateTo").value;
  if (!from && !to) return all;
  return all.filter(r => (!from || r.date >= from) && (!to || r.date <= to));
}}

function setPreset(days) {{
  const all = ALL_DATA[currentRegion] || [];
  const dates = all.map(r => r.date).sort();
  const latest = dates[dates.length - 1] || "";

  document.querySelectorAll(".preset-btn").forEach(b => b.classList.remove("active"));

  if (days === 0) {{
    // 全期間
    document.getElementById("dateFrom").value = "";
    document.getElementById("dateTo").value   = "";
    document.getElementById("btnAll").classList.add("active");
  }} else {{
    // 直近N日：最新日からN日前を計算
    const toDate   = latest ? new Date(latest) : new Date();
    const fromDate = new Date(toDate);
    fromDate.setDate(fromDate.getDate() - (days - 1));
    document.getElementById("dateFrom").value = fromDate.toISOString().slice(0, 10);
    document.getElementById("dateTo").value   = toDate.toISOString().slice(0, 10);
    event.target.classList.add("active");
  }}
  applyDateFilter(false);
}}

function applyDateFilter(resetPreset=true) {{
  if (resetPreset) {{
    document.querySelectorAll(".preset-btn").forEach(b => b.classList.remove("active"));
  }}
  const filtered = getFilteredRecords(currentRegion);
  renderAll(currentRegion, filtered);
}}

// ── エリア切り替えメイン ─────────────────────────────────────────
function switchRegion(region, updateHash=true) {{
  currentRegion = region;
  const all     = ALL_DATA[region] || [];

  // URLハッシュを更新
  if (updateHash) window.location.hash = encodeURIComponent(region);
  sel.value = region;

  // 日付入力のmin/maxをデータ範囲に合わせる
  if (all.length > 0) {{
    const dates = all.map(r => r.date).sort();
    document.getElementById("dateFrom").min = dates[0];
    document.getElementById("dateFrom").max = dates[dates.length - 1];
    document.getElementById("dateTo").min   = dates[0];
    document.getElementById("dateTo").max   = dates[dates.length - 1];
  }}

  // お知らせバナー
  document.getElementById("noDataWarn").style.display = all.length > 0 ? "none" : "block";

  // データ件数ノート（全期間ベース）
  document.getElementById("dataNote").textContent = all.length > 0
    ? `全${{all.length}}日分（${{all[0].date}} ～ ${{all[all.length-1].date}}）`
    : "データなし";

  const filtered = getFilteredRecords(region);
  renderAll(region, filtered);
}}

// ── 描画まとめ ───────────────────────────────────────────────────
function renderAll(region, records) {{
  const latestDate = records.length > 0 ? records[records.length - 1].date : "—";
  document.getElementById("kpiLabel").textContent   = `最新日 KPI（${{latestDate}}）`;
  document.getElementById("chartLabel").textContent = `日次推移（${{records.length}}日分）`;
  document.getElementById("countSub").textContent   = `各社の派遣求人掲載件数（${{region}}×事務職）`;
  document.getElementById("tableDate").textContent  = `収集日: ${{latestDate}}`;
  document.getElementById("filterNote").textContent = records.length > 0
    ? `${{records.length}}日分を表示中`
    : "該当データなし";
  renderKPI(records, region);
  renderCharts(records);
  renderTable(records);
}}

// ── KPIカード描画 ───────────────────────────────────────────────
function renderKPI(records, region) {{
  const latest = records.length > 0 ? records[records.length - 1] : {{}};
  const prev   = records.length >= 2 ? records[records.length - 2] : null;
  const kpiRow = document.getElementById("kpiRow");
  kpiRow.innerHTML = "";
  COMPANIES.forEach(co => {{
    const cur = latest[co.id] || {{}};
    const prv = prev ? (prev[co.id] || {{}}) : {{}};
    const d   = prv.count != null ? pct(cur.count, prv.count) : null;
    let deltaHtml = "";
    if (d !== null) {{
      const sign = d > 0 ? "▲" : d < 0 ? "▼" : "→";
      const cls  = d > 0 ? "up" : d < 0 ? "down" : "flat";
      deltaHtml  = `<div class="delta ${{cls}}">${{sign}} ${{Math.abs(d)}}% 前日比</div>`;
    }}
    kpiRow.innerHTML += `<div class="kpi-card ${{co.cls}}">
      <div class="co-name">${{co.name}}</div>
      <div class="count">${{fmt(cur.count)}}<span style="font-size:0.9rem;font-weight:400"> 件</span></div>
      <div class="wage">${{fmtY(cur.wage)}} / 時</div>
      ${{deltaHtml}}
    </div>`;
  }});
}}

// ── チャート描画 ─────────────────────────────────────────────────
function commonOpts(suffix) {{
  return {{
    responsive: true, maintainAspectRatio: false,
    animation: {{ duration: 300 }},
    interaction: {{ mode: "index", intersect: false }},
    plugins: {{
      legend: {{ position: "bottom", labels: {{ boxWidth: 12, font: {{ size: 11 }} }} }},
      tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.dataset.label}}: ${{ctx.parsed.y != null ? ctx.parsed.y.toLocaleString() + suffix : "—"}}` }} }}
    }},
    scales: {{
      x: {{ grid: {{ color: "#f0f0f0" }}, ticks: {{ font: {{ size: 10 }} }} }},
      y: {{ grid: {{ color: "#f0f0f0" }}, ticks: {{ font: {{ size: 10 }}, callback: v => v.toLocaleString() + suffix }} }}
    }}
  }};
}}

function renderCharts(records) {{
  const dates = records.map(r => r.date);
  const datasets_count = COMPANIES.map(co => ({{
    label: co.name,
    data: records.map(r => r[co.id]?.count ?? null),
    borderColor: co.color, backgroundColor: co.color + "22",
    borderWidth: 2, pointRadius: 3, pointHoverRadius: 5, tension: 0.25, spanGaps: true
  }}));
  const datasets_wage = COMPANIES.map(co => ({{
    label: co.name,
    data: records.map(r => r[co.id]?.wage ?? null),
    borderColor: co.color, backgroundColor: co.color + "22",
    borderWidth: 2, pointRadius: 3, pointHoverRadius: 5, tension: 0.25, spanGaps: true
  }}));

  if (chartCount) {{
    chartCount.data.labels   = dates;
    chartCount.data.datasets = datasets_count;
    chartCount.update();
  }} else {{
    chartCount = new Chart(document.getElementById("chartCount"), {{
      type: "line", data: {{ labels: dates, datasets: datasets_count }}, options: commonOpts("件")
    }});
  }}

  if (chartWage) {{
    chartWage.data.labels   = dates;
    chartWage.data.datasets = datasets_wage;
    chartWage.update();
  }} else {{
    chartWage = new Chart(document.getElementById("chartWage"), {{
      type: "line", data: {{ labels: dates, datasets: datasets_wage }}, options: commonOpts("円")
    }});
  }}
}}

// ── テーブル描画 ─────────────────────────────────────────────────
function renderTable(records) {{
  const latest = records.length > 0 ? records[records.length - 1] : {{}};
  const prev   = records.length >= 2 ? records[records.length - 2] : null;
  const tbody  = document.getElementById("tableBody");
  tbody.innerHTML = "";
  const total  = COMPANIES.reduce((s, co) => s + (latest[co.id]?.count ?? 0), 0);
  const ranked = COMPANIES
    .map(co => ({{ ...co, count: latest[co.id]?.count ?? 0, wage: latest[co.id]?.wage ?? null }}))
    .sort((a, b) => b.count - a.count);
  ranked.forEach((co, idx) => {{
    const rank  = idx + 1;
    const prv   = prev ? (prev[co.id]?.count ?? null) : null;
    const d     = prv != null ? pct(co.count, prv) : null;
    let deltaStr = records.length === 1 ? "初回" : "—";
    if (d !== null) {{
      const sign = d > 0 ? "▲" : d < 0 ? "▼" : "→";
      const cls  = d > 0 ? "color:#e53935" : d < 0 ? "color:#1e88e5" : "color:#aaa";
      deltaStr   = `<span style="${{cls}};font-weight:600">${{sign}} ${{Math.abs(d)}}%</span>`;
    }}
    const rankCls = rank <= 3 ? `rank rank-${{rank}}` : "rank";
    tbody.innerHTML += `<tr>
      <td><span class="${{rankCls}}">${{rank}}</span></td>
      <td><span class="dot" style="background:${{co.color}}"></span><span class="co-label">${{co.name}}</span></td>
      <td style="text-align:right"><span class="num">${{fmt(co.count)}}</span> 件</td>
      <td style="text-align:right">${{total ? (co.count / total * 100).toFixed(1) + "%" : "—"}}</td>
      <td style="text-align:right">${{fmtY(co.wage)}}</td>
      <td style="text-align:right">${{deltaStr}}</td>
    </tr>`;
  }});
}}

// ── 初期表示（URLハッシュがあればそのエリア、なければ最初のエリア）──
const hashRegion = decodeURIComponent(window.location.hash.slice(1));
const initRegion = REGIONS.includes(hashRegion) ? hashRegion : REGIONS[0];
switchRegion(initRegion, false);
</script>

</body>
</html>"""

    out_path.write_text(html, encoding="utf-8")
    print(f"✅ HTMLレポート更新完了: {out_path.name}（{len(regions)} エリア対応）")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        regions_arg = sys.argv[1:]
    else:
        regions_arg = DEFAULT_REGIONS
    build_html(regions_arg)
