#!/usr/bin/env python3
"""Render `stats.json` (from `build_stats.py`) into `stats.md` and `stats.html`.

Mirrors the split between `build_report.py` and `render_report.py`: this
script only formats data that already exists, it never computes a new
metric. `stats.json` stays the stable, machine-readable artifact; `stats.md`
and `stats.html` are a presentation layer built directly from it.

**Why inline SVG instead of a charting library.** This skill is stdlib-only
everywhere and has to work, unmodified, inside arbitrary audited
repositories — some with no Python data-science stack, some offline. A
single self-contained `stats.html` with inline `<svg>` and inline `<style>`
needs nothing installed and renders the same with no network access.

**Why the tool × outcome table is captioned as a contingency table, not a
confusion matrix.** Only two of the four classic cells have any evidence
behind them: confirmed findings (true-positive-like) and dismissed findings
(false-positive-like). Nothing in this pipeline observes issues a tool never
flagged, so there is no true-negative or false-negative count to report —
inventing one would fabricate data the audit never collected.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any

CHART_PALETTE = ["#4f7cff", "#e0665e", "#3fae6b", "#c98a2c", "#8a5fd6", "#2ea0a0"]


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _rate_cell(rate: float | None, ci: list[float] | None) -> str:
    if rate is None:
        return "insufficient sample"
    if ci:
        return f"{rate:.1%} ({ci[0]:.1%}–{ci[1]:.1%})"
    return f"{rate:.1%}"


# ---------------------------------------------------------------------------
# Gráficos SVG — funciones puras, deterministas (claves ordenadas, sin ids
# aleatorios), para permitir comparación byte-exacta contra un golden.
# ---------------------------------------------------------------------------


def _bar_chart_svg(values: dict[str, float], *, title: str, unit: str = "", width: int = 640, height: int = 320) -> str:
    margin = 44
    plot_w = width - 2 * margin
    plot_h = height - margin - 60
    items = sorted(values.items())
    parts = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{_esc(title)}">']
    parts.append(f'<text x="{width / 2:.1f}" y="20" text-anchor="middle" class="chart-title">{_esc(title)}</text>')
    if not items:
        parts.append(f'<text x="{width / 2:.1f}" y="{height / 2:.1f}" text-anchor="middle" class="empty">no data</text>')
        parts.append("</svg>")
        return "".join(parts)
    max_value = max(v for _, v in items) or 1.0
    bar_gap = 10.0
    bar_width = max(6.0, (plot_w - bar_gap * (len(items) - 1)) / len(items))
    for index, (label, value) in enumerate(items):
        x = margin + index * (bar_width + bar_gap)
        bar_h = (value / max_value) * plot_h if max_value else 0.0
        y = margin + 20 + (plot_h - bar_h)
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_h:.1f}" class="bar">'
            f'<title>{_esc(label)}: {value:g}{_esc(unit)}</title></rect>'
        )
        parts.append(f'<text x="{x + bar_width / 2:.1f}" y="{y - 6:.1f}" text-anchor="middle" class="value-label">{value:g}</text>')
        parts.append(
            f'<text x="{x + bar_width / 2:.1f}" y="{height - margin + 16:.1f}" text-anchor="middle" '
            f'class="axis-label">{_esc(label)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _line_chart_svg(series: dict[str, list[tuple[str, float]]], *, title: str, width: int = 640, height: int = 320) -> str:
    margin = 44
    plot_w = width - 2 * margin
    plot_h = height - margin - 40
    named = sorted(series.items())
    all_values = [value for _, points in named for _, value in points]
    parts = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{_esc(title)}">']
    parts.append(f'<text x="{width / 2:.1f}" y="20" text-anchor="middle" class="chart-title">{_esc(title)}</text>')
    if not all_values:
        parts.append(f'<text x="{width / 2:.1f}" y="{height / 2:.1f}" text-anchor="middle" class="empty">no data</text>')
        parts.append("</svg>")
        return "".join(parts)
    max_value = max(all_values)
    min_value = min(all_values)
    span = (max_value - min_value) or 1.0
    max_n = max((len(points) for _, points in named), default=1) or 1
    for index, (name, points) in enumerate(named):
        color = CHART_PALETTE[index % len(CHART_PALETTE)]
        coords = []
        for i, (_, value) in enumerate(points):
            x = margin + (i / max(1, max_n - 1)) * plot_w
            y = margin + 20 + plot_h - ((value - min_value) / span) * plot_h
            coords.append((x, y))
        path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(coords))
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2"/>')
        for x, y in coords:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>')
        parts.append(f'<text x="{margin:.1f}" y="{margin - 6 + index * 14:.1f}" class="legend" fill="{color}">{_esc(name)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _contingency_table_html(rows: dict[str, dict[str, int]], *, row_label: str, col_labels: list[str], caption: str = "") -> str:
    head = "".join(f"<th>{_esc(col)}</th>" for col in col_labels)
    body_rows = []
    for row_name in sorted(rows):
        cells = rows[row_name]
        max_v = max(cells.values()) if cells else 0
        cell_html = []
        for col in col_labels:
            v = cells.get(col, 0)
            intensity = 0.0 if max_v == 0 else v / max_v
            lightness = 96 - int(intensity * 40)
            cell_html.append(f'<td style="background:hsl(220,70%,{lightness}%)">{v}</td>')
        body_rows.append(f"<tr><th>{_esc(row_name)}</th>{''.join(cell_html)}</tr>")
    caption_html = f"<caption>{_esc(caption)}</caption>" if caption else ""
    return (
        f'<table class="contingency">{caption_html}'
        f'<thead><tr><th>{_esc(row_label)}</th>{head}</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody></table>'
    )


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _markdown(stats: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Statistics: {stats['repository']}")
    lines.append("")
    lines.append(f"- Root: `{stats['root']}`")
    lines.append(f"- Generated: {stats['generated_at']}")
    lines.append(f"- Source runs considered: {stats['source_runs_considered']}")
    lines.append("")

    current = stats["current_run"]
    lines.append("## Current run")
    lines.append("")
    lines.append(f"- Run: `{current['run_dir']}`")
    lines.append(f"- Generated: {current['generated_at']}")
    lines.append(f"- Profile: {current['profile']} · Scope: {current['scope']} · Outcome: **{current['outcome']}**")
    lines.append("")
    lines.append("| Severity | Count |")
    lines.append("|---|---|")
    for severity in ("blocker", "high", "medium", "low"):
        lines.append(f"| {severity} | {current['finding_counts'].get(severity, 0)} |")
    lines.append("")

    review = stats["review"]
    lines.append("## Review — confirm/dismiss ratios")
    lines.append("")
    lines.append(review["note"])
    lines.append("")
    lines.append("| Group | Reviewed | Confirmed | Dismissed | Confirmation rate (95% CI) | False-positive / hallucination rate (95% CI) |")
    lines.append("|---|---|---|---|---|---|")
    tool_findings = review["tool_findings"]
    llm_only = review["agent_llm_only_findings"]
    lines.append(
        f"| Tool-sourced findings | {tool_findings['reviewed']} | {tool_findings['confirmed']} | {tool_findings['dismissed']} | "
        f"{_rate_cell(tool_findings['confirmation_rate'], tool_findings['confirmation_rate_ci95'])} | "
        f"{_rate_cell(tool_findings['false_positive_rate'], tool_findings['false_positive_rate_ci95'])} |"
    )
    lines.append(
        f"| Agent LLM-only findings | {llm_only['reviewed']} | {llm_only['confirmed']} | {llm_only['dismissed']} | "
        f"{_rate_cell(llm_only['confirmation_rate'], llm_only['confirmation_rate_ci95'])} | "
        f"{_rate_cell(llm_only['false_positive_rate'], llm_only['false_positive_rate_ci95'])} |"
    )
    lines.append("")
    total_runs = review["runs_with_ledger"] + review["runs_without_ledger"]
    lines.append(
        f"Runs with a review ledger: {review['runs_with_ledger']} / {total_runs}. "
        f"Unreviewed findings in the considered scope: {review['unreviewed_findings']['count']}."
    )
    lines.append("")

    lines.append("## By tool")
    lines.append("")
    lines.append("| Tool | Runs seen | Findings | Reviewed | Confirmation rate | Avg duration (ms) | Measures |")
    lines.append("|---|---|---|---|---|---|---|")
    for name, entry in sorted(stats["by_tool"].items()):
        tool_review = entry["review"]
        rate = _rate_cell(tool_review["confirmation_rate"], tool_review["confirmation_rate_ci95"])
        domain = entry["measurement_domain"] or "*not registered*"
        lines.append(
            f"| {name} | {entry['runs_seen']} | {entry['findings_total']} | {tool_review['reviewed']} | {rate} | "
            f"{_fmt(entry['avg_duration_ms'])} | {domain} |"
        )
    lines.append("")

    lines.append("## Trends")
    lines.append("")
    lines.append("| Metric | n | Mean | Stdev | Slope/day | Direction |")
    lines.append("|---|---|---|---|---|---|")
    for group_name in ("finding_counts", "dimensions"):
        for metric, series in sorted(stats["trends"][group_name].items()):
            lines.append(
                f"| {group_name}.{metric} | {series['n']} | {_fmt(series['mean'])} | {_fmt(series['stdev'])} | "
                f"{_fmt(series['slope_per_day'])} | {series['direction']} |"
            )
    lines.append("")

    anomalies = stats["anomalies"]
    lines.append("## Anomalies")
    lines.append("")
    if not any(anomalies.get(key) for key in anomalies):
        lines.append("None detected.")
    else:
        for key in ("location_conflicts", "stale_baselines", "decision_reversals", "findings_on_removed_code"):
            items = anomalies.get(key) or []
            if items:
                lines.append(f"- **{key}**: {len(items)}")
    lines.append("")

    lines.append("## Limitations")
    lines.append("")
    if stats["limitations"]:
        for item in stats["limitations"]:
            lines.append(f"- {item}")
    else:
        lines.append("None recorded.")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_STYLE = """
:root { color-scheme: light dark; --bg:#ffffff; --fg:#1b1f24; --muted:#6b7280; --border:#e2e5e9; --accent:#4f7cff; }
@media (prefers-color-scheme: dark) { :root { --bg:#0f1115; --fg:#e6e8eb; --muted:#9aa3af; --border:#2a2e35; } }
body { background:var(--bg); color:var(--fg); font-family:-apple-system,Segoe UI,Roboto,sans-serif; margin:0; padding:24px; }
h1,h2 { border-bottom:1px solid var(--border); padding-bottom:6px; }
table { border-collapse:collapse; width:100%; margin:12px 0 24px; font-size:14px; }
th,td { border:1px solid var(--border); padding:6px 10px; text-align:left; }
th { background:transparent; color:var(--muted); font-weight:600; }
caption { text-align:left; color:var(--muted); font-size:12px; margin-bottom:6px; caption-side:top; }
.chart-title { font-size:14px; fill:currentColor; }
.axis-label { font-size:11px; fill:var(--muted); }
.value-label { font-size:11px; fill:currentColor; }
.legend { font-size:12px; }
.bar { fill:var(--accent); }
.empty { fill:var(--muted); font-size:13px; }
.note { color:var(--muted); font-size:13px; }
svg { max-width:100%; height:auto; display:block; margin:12px 0 24px; }
"""


def _html(stats: dict[str, Any]) -> str:
    current = stats["current_run"]
    severity_values = {sev: float(current["finding_counts"].get(sev, 0)) for sev in ("blocker", "high", "medium", "low")}

    findings_by_tool: dict[str, int] = {}
    contingency: dict[str, dict[str, int]] = {}
    for entry in stats["findings_timeline"]:
        tool = entry.get("tool") or "unknown"
        findings_by_tool[tool] = findings_by_tool.get(tool, 0) + 1
        row = contingency.setdefault(tool, {"confirmed": 0, "dismissed": 0, "unreviewed": 0})
        status = entry.get("review_status", "unreviewed")
        row[status] = row.get(status, 0) + 1

    trend_series = {
        metric: [(point["generated_at"], point["value"]) for point in series["series"]]
        for metric, series in sorted(stats["trends"]["finding_counts"].items())
    }

    severity_chart = _bar_chart_svg(severity_values, title="Current findings by severity")
    tool_chart = _bar_chart_svg({k: float(v) for k, v in findings_by_tool.items()}, title="Findings by tool (considered scope)")
    trend_chart = _line_chart_svg(trend_series, title="Finding counts over time")
    contingency_html = (
        _contingency_table_html(
            contingency, row_label="Tool", col_labels=["confirmed", "dismissed", "unreviewed"],
            caption=(
                "Tool × review outcome. Not a full confusion matrix: there is no evidence for issues a "
                "tool never flagged, so true/false negatives are not shown."
            ),
        )
        if contingency else "<p class=\"note\">No findings in the considered scope.</p>"
    )

    by_tool_rows = []
    for name, entry in sorted(stats["by_tool"].items()):
        tool_review = entry["review"]
        rate = _rate_cell(tool_review["confirmation_rate"], tool_review["confirmation_rate_ci95"])
        domain = entry["measurement_domain"] or "<em>not registered</em>"
        by_tool_rows.append(
            f"<tr><td>{_esc(name)}</td><td>{entry['runs_seen']}</td><td>{entry['findings_total']}</td>"
            f"<td>{tool_review['reviewed']}</td><td>{_esc(rate)}</td><td>{_esc(_fmt(entry['avg_duration_ms']))}</td>"
            f"<td>{domain if entry['measurement_domain'] is None else _esc(domain)}</td></tr>"
        )

    trend_rows = []
    for group_name in ("finding_counts", "dimensions"):
        for metric, series in sorted(stats["trends"][group_name].items()):
            trend_rows.append(
                f"<tr><td>{_esc(group_name + '.' + metric)}</td><td>{series['n']}</td>"
                f"<td>{_esc(_fmt(series['mean']))}</td><td>{_esc(_fmt(series['stdev']))}</td>"
                f"<td>{_esc(_fmt(series['slope_per_day']))}</td><td>{_esc(series['direction'])}</td></tr>"
            )

    limitations_html = (
        "".join(f"<li>{_esc(item)}</li>" for item in stats["limitations"])
        if stats["limitations"] else "<li>None recorded.</li>"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Statistics: {_esc(stats['repository'])}</title>
<style>{_STYLE}</style>
</head>
<body>
<h1>Statistics: {_esc(stats['repository'])}</h1>
<p class="note">Root: <code>{_esc(stats['root'])}</code> · Generated: {_esc(stats['generated_at'])} ·
Source runs considered: {stats['source_runs_considered']}</p>

<h2>Current run</h2>
<p>Run <code>{_esc(current['run_dir'])}</code> · {_esc(current['generated_at'])} ·
profile {_esc(current['profile'])} · scope {_esc(current['scope'])} · outcome <strong>{_esc(current['outcome'])}</strong></p>
{severity_chart}

<h2>Review — confirm/dismiss ratios</h2>
<p class="note">{_esc(stats['review']['note'])}</p>
<table>
<thead><tr><th>Group</th><th>Reviewed</th><th>Confirmed</th><th>Dismissed</th>
<th>Confirmation rate (95% CI)</th><th>False-positive / hallucination rate (95% CI)</th></tr></thead>
<tbody>
<tr><td>Tool-sourced findings</td><td>{stats['review']['tool_findings']['reviewed']}</td>
<td>{stats['review']['tool_findings']['confirmed']}</td><td>{stats['review']['tool_findings']['dismissed']}</td>
<td>{_esc(_rate_cell(stats['review']['tool_findings']['confirmation_rate'], stats['review']['tool_findings']['confirmation_rate_ci95']))}</td>
<td>{_esc(_rate_cell(stats['review']['tool_findings']['false_positive_rate'], stats['review']['tool_findings']['false_positive_rate_ci95']))}</td></tr>
<tr><td>Agent LLM-only findings</td><td>{stats['review']['agent_llm_only_findings']['reviewed']}</td>
<td>{stats['review']['agent_llm_only_findings']['confirmed']}</td><td>{stats['review']['agent_llm_only_findings']['dismissed']}</td>
<td>{_esc(_rate_cell(stats['review']['agent_llm_only_findings']['confirmation_rate'], stats['review']['agent_llm_only_findings']['confirmation_rate_ci95']))}</td>
<td>{_esc(_rate_cell(stats['review']['agent_llm_only_findings']['false_positive_rate'], stats['review']['agent_llm_only_findings']['false_positive_rate_ci95']))}</td></tr>
</tbody>
</table>

<h2>Findings by tool</h2>
{tool_chart}
{contingency_html}

<h2>By tool</h2>
<table>
<thead><tr><th>Tool</th><th>Runs seen</th><th>Findings</th><th>Reviewed</th><th>Confirmation rate</th>
<th>Avg duration (ms)</th><th>Measures</th></tr></thead>
<tbody>{''.join(by_tool_rows) or '<tr><td colspan="7">No tools recorded.</td></tr>'}</tbody>
</table>

<h2>Trends</h2>
{trend_chart}
<table>
<thead><tr><th>Metric</th><th>n</th><th>Mean</th><th>Stdev</th><th>Slope/day</th><th>Direction</th></tr></thead>
<tbody>{''.join(trend_rows) or '<tr><td colspan="6">No trend data.</td></tr>'}</tbody>
</table>

<h2>Limitations</h2>
<ul>{limitations_html}</ul>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------


def render(stats: dict[str, Any], output_dir: Path, *, emit_svg: bool = False) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "stats.md"
    html_path = output_dir / "stats.html"
    for path in (md_path, html_path):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite existing artifact: {path}")
    md_path.write_text(_markdown(stats), encoding="utf-8")
    html_path.write_text(_html(stats), encoding="utf-8")
    if emit_svg:
        charts_dir = output_dir / "charts"
        charts_dir.mkdir(exist_ok=True)
        current = stats["current_run"]
        severity_values = {sev: float(current["finding_counts"].get(sev, 0)) for sev in ("blocker", "high", "medium", "low")}
        (charts_dir / "severity_counts.svg").write_text(
            _bar_chart_svg(severity_values, title="Current findings by severity"), encoding="utf-8",
        )
        findings_by_tool: dict[str, int] = {}
        for entry in stats["findings_timeline"]:
            tool = entry.get("tool") or "unknown"
            findings_by_tool[tool] = findings_by_tool.get(tool, 0) + 1
        (charts_dir / "findings_by_tool.svg").write_text(
            _bar_chart_svg({k: float(v) for k, v in findings_by_tool.items()}, title="Findings by tool"), encoding="utf-8",
        )
        trend_series = {
            metric: [(point["generated_at"], point["value"]) for point in series["series"]]
            for metric, series in sorted(stats["trends"]["finding_counts"].items())
        }
        (charts_dir / "finding_count_trends.svg").write_text(
            _line_chart_svg(trend_series, title="Finding counts over time"), encoding="utf-8",
        )
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stats", type=Path, help="stats.json produced by build_stats.py")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--emit-svg", action="store_true")
    args = parser.parse_args()
    try:
        stats = json.loads(args.stats.read_text(encoding="utf-8"))
        destination = render(stats, args.output_dir, emit_svg=args.emit_svg)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
