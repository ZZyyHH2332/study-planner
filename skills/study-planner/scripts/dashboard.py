#!/usr/bin/env python3
"""Dashboard generator for Study Planner.

Queries SQLite database and generates a self-contained HTML dashboard
with ECharts visualizations. No server required — just open in browser.

Charts:
  1. Learning calendar heatmap (GitHub-style daily review activity)
  2. Mastery trend lines (per-concept mastery over time)
  3. Knowledge graph (force-layout network with clickable node details)
  4. Review rating distribution (pie chart)
  5. Mastery distribution histogram (bar chart)
  6. Review forecast (upcoming reviews by date, next 30 days)
  7. Learning velocity (mastery improvement rate per concept)
  8. Learner profile summary (HTML cards)
  9. Metacognition alerts (diagnostic panel)
  10. BKT/FSRS parameters display

Usage:
  python dashboard.py                  # Generate and open
  python dashboard.py --no-open        # Generate without opening browser
  python dashboard.py --output path    # Custom output path
"""

import json
import sys
import webbrowser
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

ae_dir = Path(__file__).resolve().parent.parent.parent / "adaptive-engine" / "scripts"
sys.path.insert(0, str(ae_dir))

import db_manager
import profile_manager


def query_review_log(config=None):
    """Query all review log entries ordered by date."""
    conn = db_manager.get_connection(config)
    rows = conn.execute(
        """SELECT rl.*, kn.title, kn.difficulty
           FROM review_log rl
           LEFT JOIN knowledge_nodes kn ON rl.note_id = kn.note_id
           ORDER BY rl.review_date"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_calendar_data(reviews):
    """Aggregate reviews by date for calendar heatmap."""
    daily = defaultdict(int)
    for r in reviews:
        date_str = r.get("review_date", "")[:10]
        if date_str:
            daily[date_str] += 1

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    data = [[d, c] for d, c in sorted(daily.items())]
    return data, start_date, end_date


def query_mastery_trends(reviews):
    """Extract mastery trend data per concept."""
    by_concept = defaultdict(list)
    for r in reviews:
        title = r.get("title") or r.get("note_id", "unknown")
        date_str = r.get("review_date", "")[:10]
        mastery = r.get("new_mastery")
        if date_str and mastery is not None:
            by_concept[title].append([date_str, round(mastery, 4)])

    series = []
    for title, data in sorted(by_concept.items()):
        data.sort(key=lambda x: x[0])
        series.append({"name": title[:20], "type": "line", "data": data,
                        "smooth": True, "symbolSize": 6})
    return series


def query_graph_data(nodes, edges):
    """Build graph data for ECharts network visualization."""
    node_list = []
    for n in nodes:
        mastery = n.get("mastery", 0)
        if mastery >= 0.7:
            color = "#0a7b6f"
        elif mastery >= 0.3:
            color = "#f0a020"
        else:
            color = "#e74c3c"

        node_list.append({
            "id": n["note_id"],
            "name": (n.get("title") or n["note_id"])[:15],
            "symbolSize": 20 + mastery * 30,
            "itemStyle": {"color": color},
            "value": round(mastery, 2),
            "details": {
                "title": n.get("title", ""),
                "difficulty": n.get("difficulty", 1),
                "learning_state": n.get("learning_state", ""),
                "review_count": n.get("review_count", 0),
                "ease_factor": n.get("ease_factor", 2.5),
                "last_reviewed": n.get("last_reviewed", ""),
                "next_review": n.get("next_review", ""),
                "file_path": n.get("file_path", ""),
            },
        })

    link_list = []
    for e in edges:
        link_list.append({
            "source": e["source_id"],
            "target": e["target_id"],
            "lineStyle": {"color": "#aaa", "width": 1.5},
        })

    return {"nodes": node_list, "links": link_list}


def query_rating_distribution(reviews):
    """Count reviews by rating (1-4)."""
    names = {1: "Again", 2: "Hard", 3: "Good", 4: "Easy"}
    counts = defaultdict(int)
    for r in reviews:
        rating = r.get("rating")
        if rating in names:
            counts[rating] += 1
    return [{"name": names[k], "value": v} for k, v in sorted(counts.items())]


def query_mastery_distribution(nodes):
    """Bucket nodes by mastery level."""
    buckets = {"0-30% (Learning)": 0, "30-70% (Familiar)": 0, "70-100% (Mastered)": 0}
    for n in nodes:
        m = n.get("mastery", 0)
        if m < 0.3:
            buckets["0-30% (Learning)"] += 1
        elif m < 0.7:
            buckets["30-70% (Familiar)"] += 1
        else:
            buckets["70-100% (Mastered)"] += 1
    return [[k, v] for k, v in buckets.items()]


def query_review_forecast(config=None):
    """Get upcoming reviews grouped by date for next 30 days."""
    conn = db_manager.get_connection(config)
    today = datetime.now().strftime("%Y-%m-%d")
    future = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    rows = conn.execute(
        """SELECT next_review, COUNT(*) as cnt
           FROM knowledge_nodes
           WHERE next_review IS NOT NULL
             AND next_review >= ?
             AND next_review <= ?
             AND learning_state != 'mastered'
           GROUP BY next_review
           ORDER BY next_review""",
        (today, future)
    ).fetchall()
    conn.close()

    data = [[r["next_review"][:10], r["cnt"]] for r in rows]
    return data


def query_learning_velocity(reviews):
    """Calculate mastery improvement rate per concept.

    Returns: [{"name": title, "velocity": delta_per_review, "reviews": count}, ...]
    """
    by_concept = defaultdict(list)
    for r in reviews:
        title = r.get("title") or r.get("note_id", "unknown")
        mastery = r.get("new_mastery")
        if mastery is not None:
            by_concept[title].append(mastery)

    results = []
    for title, masteries in sorted(by_concept.items()):
        if len(masteries) < 2:
            continue
        first = masteries[0]
        last = masteries[-1]
        velocity = (last - first) / len(masteries)
        results.append({
            "name": title[:15],
            "velocity": round(velocity, 4),
            "reviews": len(masteries),
            "start_mastery": round(first, 2),
            "end_mastery": round(last, 2),
        })

    results.sort(key=lambda x: x["velocity"], reverse=True)
    return results


def build_profile_cards(profile, stats):
    """Build HTML for profile summary cards."""
    total_reviews = profile.get("total_reviews", stats.get("total_reviews", 0))
    total_minutes = profile.get("total_study_minutes", 0)
    weak_areas = profile.get("weak_areas", [])
    study_patterns = profile.get("study_patterns", {})
    retention = profile.get("retention_profile", {})

    weak_html = ""
    if weak_areas:
        for w in weak_areas[:3]:
            weak_html += f'<div class="weak-item"><span>{w.get("concept", "?")}</span><span class="fail-rate">{w.get("failure_rate", 0)*100:.0f}% fail</span></div>'
    else:
        weak_html = '<div class="empty-hint">暂无薄弱领域</div>'

    peak_hours = study_patterns.get("peak_hours", "—")
    avg_duration = study_patterns.get("avg_duration", 0)
    avg_ease = retention.get("avg_ease_factor", 2.5)

    cards = f"""
    <div class="stat-cards">
      <div class="card">
        <div class="card-value">{total_reviews}</div>
        <div class="card-label">累计复习</div>
      </div>
      <div class="card">
        <div class="card-value">{stats.get('total_nodes', 0)}</div>
        <div class="card-label">知识节点</div>
      </div>
      <div class="card">
        <div class="card-value">{stats.get('mastered_nodes', 0)}</div>
        <div class="card-label">已掌握</div>
      </div>
      <div class="card">
        <div class="card-value">{stats.get('avg_mastery', 0)*100:.0f}%</div>
        <div class="card-label">平均掌握度</div>
      </div>
      <div class="card">
        <div class="card-value">{total_minutes}</div>
        <div class="card-label">学习时长(分)</div>
      </div>
      <div class="card">
        <div class="card-value">{avg_ease:.2f}</div>
        <div class="card-label">平均 Ease</div>
      </div>
    </div>

    <div class="profile-section">
      <h3>薄弱领域</h3>
      {weak_html}
    </div>

    <div class="profile-section">
      <h3>学习习惯</h3>
      <div class="habit-row"><span>高峰时段</span><span>{peak_hours}</span></div>
      <div class="habit-row"><span>平均时长</span><span>{avg_duration:.0f} 分钟</span></div>
    </div>
    """
    return cards


def build_metacognition_section(config=None):
    """Build metacognition alerts section."""
    try:
        import metacognition
        result = metacognition.diagnose(config=config)
    except Exception:
        return '<div class="profile-section"><h3>元认知诊断</h3><div class="empty-hint">诊断模块不可用</div></div>'

    if not result.get("alerts"):
        return f"""
        <div class="profile-section">
          <h3>元认知诊断</h3>
          <div class="empty-hint">{result.get('summary', '未检测到异常')}</div>
        </div>"""

    alerts_html = ""
    for alert in result["alerts"]:
        sev = alert["severity"]
        sev_color = "#e74c3c" if sev == "high" else "#f0a020"
        alerts_html += f"""
        <div class="alert-item" style="border-left:3px solid {sev_color};padding:8px 12px;margin:8px 0;background:#fafafa;border-radius:4px;">
          <div style="font-weight:600;color:{sev_color};font-size:12px;">[{sev.upper()}]</div>
          <div style="font-weight:500;font-size:13px;margin:4px 0;">{alert['title']}</div>
          <div style="font-size:12px;color:#6e6e73;">{alert['diagnosis']}</div>
          <div style="font-size:12px;color:#0a7b6f;margin-top:2px;">→ {alert['action']}</div>
        </div>"""

    return f"""
    <div class="profile-section">
      <h3>元认知诊断</h3>
      <div style="font-size:13px;color:#6e6e73;margin-bottom:8px;">{result.get('summary', '')}</div>
      {alerts_html}
    </div>"""


def build_params_section(config=None):
    """Build BKT/FSRS parameters display."""
    try:
        bkt = profile_manager.get_bkt_params("default", config)
    except Exception:
        bkt = {"p_init": 0.1, "p_transit": 0.3, "p_slip": 0.1, "p_guess": 0.2}

    try:
        retention = profile_manager.get_profile("retention_profile", config) or {}
    except Exception:
        retention = {}

    avg_ease = retention.get("avg_ease_factor", 2.5)
    stability = retention.get("stability_trend", "—")

    return f"""
    <div class="profile-section">
      <h3>BKT / FSRS 参数</h3>
      <div class="habit-row"><span>P(L0) 初始掌握</span><span>{bkt.get('p_init', 0.1)}</span></div>
      <div class="habit-row"><span>P(T) 学习转移</span><span>{bkt.get('p_transit', 0.3)}</span></div>
      <div class="habit-row"><span>P(S) 滑动率</span><span>{bkt.get('p_slip', 0.1)}</span></div>
      <div class="habit-row"><span>P(G) 猜测率</span><span>{bkt.get('p_guess', 0.2)}</span></div>
      <div class="habit-row"><span>Ease Factor</span><span>{avg_ease}</span></div>
      <div class="habit-row"><span>稳定性趋势</span><span>{stability}</span></div>
    </div>"""


def render_html(stats, nodes, edges, reviews, profile, config=None):
    """Render the complete dashboard HTML."""
    cal_data, cal_start, cal_end = query_calendar_data(reviews)
    mastery_series = query_mastery_trends(reviews)
    graph_data = query_graph_data(nodes, edges)
    rating_data = query_rating_distribution(reviews)
    mastery_dist = query_mastery_distribution(nodes)
    profile_html = build_profile_cards(profile, stats)
    forecast_data = query_review_forecast(config)
    velocity_data = query_learning_velocity(reviews)
    meta_html = build_metacognition_section(config)
    params_html = build_params_section(config)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    velocity_names = [v["name"] for v in velocity_data]
    velocity_vals = [v["velocity"] for v in velocity_data]

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Study Planner Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
  :root {{
    --bg: #f5f5f7;
    --card-bg: #ffffff;
    --text: #1d1d1f;
    --text-secondary: #6e6e73;
    --accent: #0a7b6f;
    --accent-light: #e6f4f1;
    --border: #d2d2d7;
    --radius: 12px;
    --shadow: 0 1px 3px rgba(0,0,0,0.08);
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, system-ui, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 24px;
    max-width: 1400px;
    margin: 0 auto;
  }}
  .header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
  }}
  .header h1 {{
    font-size: 24px;
    font-weight: 600;
  }}
  .header .updated {{
    font-size: 13px;
    color: var(--text-secondary);
  }}
  .grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 20px;
  }}
  .grid-full {{
    grid-column: 1 / -1;
  }}
  .chart-card {{
    background: var(--card-bg);
    border-radius: var(--radius);
    padding: 20px;
    box-shadow: var(--shadow);
  }}
  .chart-card h2 {{
    font-size: 15px;
    font-weight: 600;
    margin-bottom: 12px;
    color: var(--text);
  }}
  .chart-container {{
    width: 100%;
    height: 300px;
  }}
  .chart-container-tall {{
    height: 400px;
  }}
  .stat-cards {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    margin-bottom: 20px;
  }}
  .card {{
    background: var(--card-bg);
    border-radius: var(--radius);
    padding: 16px;
    text-align: center;
    box-shadow: var(--shadow);
  }}
  .card-value {{
    font-size: 28px;
    font-weight: 700;
    color: var(--accent);
  }}
  .card-label {{
    font-size: 12px;
    color: var(--text-secondary);
    margin-top: 4px;
  }}
  .profile-section {{
    background: var(--card-bg);
    border-radius: var(--radius);
    padding: 16px;
    margin-bottom: 12px;
    box-shadow: var(--shadow);
  }}
  .profile-section h3 {{
    font-size: 14px;
    font-weight: 600;
    margin-bottom: 8px;
  }}
  .weak-item, .habit-row {{
    display: flex;
    justify-content: space-between;
    padding: 4px 0;
    font-size: 13px;
  }}
  .fail-rate {{
    color: #e74c3c;
    font-weight: 500;
  }}
  .empty-hint {{
    font-size: 13px;
    color: var(--text-secondary);
  }}
  .no-data {{
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--text-secondary);
    font-size: 14px;
  }}
  .two-col {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 20px;
  }}
  .sidebar {{
    display: flex;
    flex-direction: column;
    gap: 12px;
  }}
  .node-detail {{
    background: var(--card-bg);
    border-radius: var(--radius);
    padding: 16px;
    box-shadow: var(--shadow);
    display: none;
  }}
  .node-detail.active {{
    display: block;
  }}
  .node-detail h3 {{
    font-size: 14px;
    font-weight: 600;
    margin-bottom: 8px;
  }}
  .node-detail-row {{
    display: flex;
    justify-content: space-between;
    padding: 3px 0;
    font-size: 12px;
  }}
</style>
</head>
<body>

<div class="header">
  <h1>Study Planner</h1>
  <span class="updated">更新于 {now_str}</span>
</div>

{profile_html}

<div class="grid">
  <div class="chart-card grid-full">
    <h2>学习日历热力图</h2>
    <div id="calendar-chart" class="chart-container" style="height:200px"></div>
  </div>

  <div class="chart-card">
    <h2>掌握度趋势</h2>
    <div id="mastery-chart" class="chart-container"></div>
  </div>

  <div class="chart-card">
    <h2>复习评级分布</h2>
    <div id="rating-chart" class="chart-container"></div>
  </div>

  <div class="chart-card">
    <h2>知识图谱 <span style="font-size:11px;color:#6e6e73;font-weight:400;">（点击节点查看详情）</span></h2>
    <div id="graph-chart" class="chart-container chart-container-tall"></div>
  </div>

  <div class="chart-card">
    <h2>掌握度分布</h2>
    <div id="distribution-chart" class="chart-container"></div>
  </div>

  <div class="chart-card">
    <h2>复习预测（未来 30 天）</h2>
    <div id="forecast-chart" class="chart-container"></div>
  </div>

  <div class="chart-card">
    <h2>学习速度（每次复习掌握度变化）</h2>
    <div id="velocity-chart" class="chart-container"></div>
  </div>
</div>

<div class="two-col">
  <div class="sidebar">
    {meta_html}
  </div>
  <div class="sidebar">
    {params_html}
    <div class="node-detail" id="node-detail">
      <h3>节点详情</h3>
      <div id="node-detail-content"></div>
    </div>
  </div>
</div>

<script>
var calData = {json.dumps(cal_data, ensure_ascii=False)};
var calStart = "{cal_start}";
var calEnd = "{cal_end}";
var masterySeries = {json.dumps(mastery_series, ensure_ascii=False)};
var graphData = {json.dumps(graph_data, ensure_ascii=False)};
var ratingData = {json.dumps(rating_data, ensure_ascii=False)};
var masteryDist = {json.dumps(mastery_dist, ensure_ascii=False)};
var forecastData = {json.dumps(forecast_data, ensure_ascii=False)};
var velocityNames = {json.dumps(velocity_names, ensure_ascii=False)};
var velocityVals = {json.dumps(velocity_vals, ensure_ascii=False)};

// Calendar heatmap
var calChart = echarts.init(document.getElementById('calendar-chart'));
calChart.setOption({{
  tooltip: {{ formatter: function(p) {{ return p.data[0] + ': ' + p.data[1] + ' 次复习'; }} }},
  visualMap: {{
    min: 0, max: 10,
    orient: 'horizontal', left: 'center', top: 0,
    inRange: {{ color: ['#e6f4f1', '#0a7b6f'] }},
    textStyle: {{ fontSize: 11 }}
  }},
  calendar: {{
    top: 40, left: 40, right: 40,
    range: [calStart, calEnd],
    cellSize: ['auto', 13],
    itemStyle: {{ borderWidth: 1, borderColor: '#fff' }},
    yearLabel: {{ show: false }},
    dayLabel: {{ fontSize: 10 }},
    monthLabel: {{ fontSize: 10 }},
    splitLine: {{ show: false }}
  }},
  series: [{{ type: 'heatmap', coordinateSystem: 'calendar', data: calData }}]
}});

// Mastery trends
var masteryChart = echarts.init(document.getElementById('mastery-chart'));
masteryChart.setOption({{
  tooltip: {{ trigger: 'axis' }},
  legend: {{ bottom: 0, textStyle: {{ fontSize: 11 }} }},
  grid: {{ left: 40, right: 20, top: 20, bottom: 60 }},
  xAxis: {{ type: 'category', axisLabel: {{ fontSize: 10 }} }},
  yAxis: {{ type: 'value', min: 0, max: 1, axisLabel: {{ fontSize: 10, formatter: function(v) {{ return (v*100).toFixed(0) + '%'; }} }} }},
  series: masterySeries.length > 0 ? masterySeries : [{{ type: 'line', data: [] }}]
}});

// Rating distribution
var ratingChart = echarts.init(document.getElementById('rating-chart'));
ratingChart.setOption({{
  tooltip: {{ trigger: 'item' }},
  legend: {{ bottom: 0, textStyle: {{ fontSize: 11 }} }},
  series: [{{
    type: 'pie',
    radius: ['40%', '70%'],
    center: ['50%', '45%'],
    data: ratingData.length > 0 ? ratingData : [{{name: '暂无数据', value: 1}}],
    itemStyle: {{ borderRadius: 6, borderColor: '#fff', borderWidth: 2 }},
    label: {{ fontSize: 11 }}
  }}],
  color: ['#e74c3c', '#f0a020', '#0a7b6f', '#3498db']
}});

// Knowledge graph with click interaction
var graphChart = echarts.init(document.getElementById('graph-chart'));
graphChart.setOption({{
  tooltip: {{ formatter: function(p) {{ return p.data.name + ' (mastery: ' + (p.data.value || 0) + ')'; }} }},
  series: [{{
    type: 'graph',
    layout: 'force',
    roam: true,
    data: graphData.nodes,
    links: graphData.links,
    force: {{ repulsion: 200, edgeLength: 80, gravity: 0.1 }},
    label: {{ show: true, fontSize: 10, position: 'right' }},
    lineStyle: {{ color: '#aaa', width: 1.5, curveness: 0.1 }},
    emphasis: {{ focus: 'adjacency', lineStyle: {{ width: 3 }} }}
  }}]
}});

// Node click → show details
graphChart.on('click', function(params) {{
  if (params.dataType === 'node') {{
    var d = params.data.details || {{}};
    var html = '<div class="node-detail-row"><span>标题</span><span>' + (d.title || '') + '</span></div>' +
               '<div class="node-detail-row"><span>难度</span><span>' + (d.difficulty || 1) + '</span></div>' +
               '<div class="node-detail-row"><span>状态</span><span>' + (d.learning_state || '') + '</span></div>' +
               '<div class="node-detail-row"><span>复习次数</span><span>' + (d.review_count || 0) + '</span></div>' +
               '<div class="node-detail-row"><span>Ease</span><span>' + (d.ease_factor || 2.5) + '</span></div>' +
               '<div class="node-detail-row"><span>上次复习</span><span>' + (d.last_reviewed || '—') + '</span></div>' +
               '<div class="node-detail-row"><span>下次复习</span><span>' + (d.next_review || '—') + '</span></div>' +
               '<div class="node-detail-row"><span>文件</span><span style="font-size:10px;word-break:break-all;">' + (d.file_path || '—') + '</span></div>';
    document.getElementById('node-detail-content').innerHTML = html;
    document.getElementById('node-detail').classList.add('active');
  }}
}});

// Mastery distribution
var distChart = echarts.init(document.getElementById('distribution-chart'));
distChart.setOption({{
  tooltip: {{ trigger: 'axis' }},
  grid: {{ left: 60, right: 20, top: 20, bottom: 40 }},
  xAxis: {{ type: 'category', data: masteryDist.map(function(d) {{ return d[0]; }}), axisLabel: {{ fontSize: 10 }} }},
  yAxis: {{ type: 'value', axisLabel: {{ fontSize: 10 }} }},
  series: [{{
    type: 'bar',
    data: masteryDist.map(function(d) {{ return d[1]; }}),
    itemStyle: {{ color: '#0a7b6f', borderRadius: [6, 6, 0, 0] }},
    barWidth: '40%'
  }}]
}});

// Review forecast
var forecastChart = echarts.init(document.getElementById('forecast-chart'));
forecastChart.setOption({{
  tooltip: {{ trigger: 'axis' }},
  grid: {{ left: 50, right: 20, top: 20, bottom: 40 }},
  xAxis: {{ type: 'category', data: forecastData.map(function(d) {{ return d[0]; }}), axisLabel: {{ fontSize: 9, rotate: 45 }} }},
  yAxis: {{ type: 'value', axisLabel: {{ fontSize: 10 }} }},
  series: [{{
    type: 'bar',
    data: forecastData.map(function(d) {{ return d[1]; }}),
    itemStyle: {{ color: '#3498db', borderRadius: [4, 4, 0, 0] }},
    barWidth: '60%'
  }}]
}});

// Learning velocity
var velocityChart = echarts.init(document.getElementById('velocity-chart'));
velocityChart.setOption({{
  tooltip: {{ trigger: 'axis', formatter: function(params) {{
    var p = params[0];
    var v = p.value;
    var sign = v >= 0 ? '+' : '';
    return p.name + '<br/>速度: ' + sign + (v*100).toFixed(2) + '%/次';
  }} }},
  grid: {{ left: 50, right: 20, top: 20, bottom: 40 }},
  xAxis: {{ type: 'category', data: velocityNames, axisLabel: {{ fontSize: 9, rotate: 30 }} }},
  yAxis: {{ type: 'value', axisLabel: {{ fontSize: 10, formatter: function(v) {{ return (v*100).toFixed(1) + '%'; }} }} }},
  series: [{{
    type: 'bar',
    data: velocityVals.map(function(v) {{ return {{
      value: v,
      itemStyle: {{ color: v >= 0 ? '#0a7b6f' : '#e74c3c' }}
    }}; }}),
    barWidth: '50%'
  }}]
}});

// Resize handler
window.addEventListener('resize', function() {{
  calChart.resize();
  masteryChart.resize();
  ratingChart.resize();
  graphChart.resize();
  distChart.resize();
  forecastChart.resize();
  velocityChart.resize();
}});
</script>
</body>
</html>"""
    return html


def generate_dashboard(config=None, output_path=None, open_browser=True):
    """Generate the dashboard HTML file.

    Args:
        config: Plugin config dict (loads from config.json if None)
        output_path: Custom output path (defaults to study-planner dir)
        open_browser: Whether to open the file in browser

    Returns:
        Path to the generated HTML file
    """
    if config is None:
        config = db_manager.load_config()

    stats = db_manager.get_stats(config)
    nodes = db_manager.get_all_nodes(config)
    edges = db_manager.get_edges(config=config)
    reviews = query_review_log(config)
    profile = profile_manager.get_full_profile(config)

    html = render_html(stats, nodes, edges, reviews, profile, config)

    if output_path is None:
        db_path = db_manager.get_db_path(config)
        output_path = str(Path(db_path).parent / "dashboard.html")
    else:
        output_path = str(output_path)

    Path(output_path).write_text(html, encoding="utf-8")

    if open_browser:
        webbrowser.open(f"file:///{output_path.replace(chr(92), '/')}")

    return output_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate Study Planner dashboard")
    parser.add_argument("--output", type=Path, help="Custom output path")
    parser.add_argument("--no-open", action="store_true", help="Don't open browser")
    args = parser.parse_args()

    path = generate_dashboard(
        output_path=args.output,
        open_browser=not args.no_open
    )
    print(f"Dashboard generated: {path}")
