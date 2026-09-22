"""
BIM Coordination AI — Report Generator.

Produces two formats from IFCCheckSummary + QTOResult:

  HTML  — self-contained dark-theme dashboard (no CDN dependencies)
  Excel — multi-sheet workbook: Summary | QTO | Naming Issues | Type Issues | Omniclass Issues

Usage:
    from bim_coordination_ai.report import ReportService
    svc = ReportService()
    html_bytes = svc.generate_html(check_summary, qto_result)
    xlsx_bytes = svc.generate_excel(check_summary, qto_result)
"""

from __future__ import annotations

import io
from datetime import datetime

import openpyxl
from jinja2 import Environment, select_autoescape
from openpyxl.styles import Alignment, Font, PatternFill

from .models import IFCCheckSummary, Priority, QTOResult

# ── HTML template ─────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BIM Report — {{ check.project_name }}</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f172a;color:#e2e8f0;font-size:14px}
a{color:#60a5fa}
.hdr{background:#1e293b;border-bottom:3px solid #3b82f6;padding:20px 32px;display:flex;align-items:center;justify-content:space-between}
.hdr h1{font-size:1.3rem;color:#f1f5f9;font-weight:700}
.hdr p{color:#64748b;font-size:0.78rem;margin-top:4px}
.badge-schema{background:#1e3a5f;color:#93c5fd;padding:3px 10px;border-radius:20px;font-size:0.75rem;font-weight:600}
main{max-width:1400px;margin:0 auto;padding:24px 32px}
/* Cards */
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(165px,1fr));gap:14px;margin-bottom:28px}
.card{background:#1e293b;border-radius:8px;padding:18px 20px;border-left:4px solid #3b82f6}
.card.green{border-color:#22c55e}.card.amber{border-color:#f59e0b}.card.red{border-color:#ef4444}
.card-val{font-size:2rem;font-weight:800;line-height:1}
.card-lbl{color:#64748b;font-size:0.7rem;text-transform:uppercase;letter-spacing:.06em;margin-top:6px}
/* Sections */
.sec{background:#1e293b;border-radius:8px;margin-bottom:20px;overflow:hidden}
.sec-hdr{background:#1e3a5f;padding:14px 20px;font-size:0.9rem;font-weight:600;display:flex;gap:10px;align-items:center}
.sec-hdr .ico{font-size:1rem}
/* Compliance bars */
.bar-row{display:flex;align-items:center;padding:12px 20px;border-bottom:1px solid #0f172a;gap:12px}
.bar-lbl{width:220px;flex-shrink:0;font-size:0.83rem}
.bar-track{flex:1;height:16px;background:#334155;border-radius:20px;overflow:hidden}
.bar-fill{height:100%;border-radius:20px;transition:width .4s}
.bar-fill.g{background:#22c55e}.bar-fill.a{background:#f59e0b}.bar-fill.r{background:#ef4444}
.bar-pct{width:48px;text-align:right;font-weight:700;font-size:0.85rem}
/* Tables */
.tbl-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:0.82rem}
th{background:#0f2744;padding:9px 14px;text-align:left;font-size:0.72rem;text-transform:uppercase;letter-spacing:.06em;color:#64748b;white-space:nowrap}
td{padding:9px 14px;border-bottom:1px solid #0f172a;white-space:nowrap}
tbody tr:hover td{background:#243044}
/* Severity badges */
.sev{display:inline-block;padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:700}
.sev.critical{background:#7f1d1d;color:#fca5a5}
.sev.high{background:#78350f;color:#fcd34d}
.sev.medium{background:#1e3a5f;color:#93c5fd}
.sev.low{background:#14532d;color:#86efac}
/* Discipline pills */
.disc{display:inline-block;padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:600;background:#1e293b;border:1px solid #334155}
/* Footer */
footer{text-align:center;padding:20px;color:#334155;font-size:0.75rem;border-top:1px solid #1e293b;margin-top:8px}
.mono{font-family:'Courier New',monospace;font-size:0.8rem;color:#94a3b8}
</style>
</head>
<body>
<div class="hdr">
  <div>
    <h1>BIM Coordination Report</h1>
    <p>{{ check.project_name }} &nbsp;·&nbsp; {{ check.file_path | basename }}
       &nbsp;·&nbsp; Generated {{ generated_at }}</p>
  </div>
  <span class="badge-schema">{{ check.ifc_schema }}</span>
</div>

<main>

<!-- Summary cards -->
<div class="cards">
  {% set cc = 'green' if check.overall_compliance_pct >= 80 else ('amber' if check.overall_compliance_pct >= 50 else 'red') %}
  <div class="card {{ cc }}">
    <div class="card-val">{{ check.overall_compliance_pct }}%</div>
    <div class="card-lbl">Overall Compliance</div>
  </div>
  <div class="card">
    <div class="card-val">{{ check.total_elements }}</div>
    <div class="card-lbl">Total Elements</div>
  </div>
  <div class="card {% if check.naming_fail == 0 %}green{% elif check.naming_fail < 5 %}amber{% else %}red{% endif %}">
    <div class="card-val">{{ check.naming_fail }}</div>
    <div class="card-lbl">Naming Issues</div>
  </div>
  <div class="card {% if check.type_fail == 0 %}green{% elif check.type_fail < 5 %}amber{% else %}red{% endif %}">
    <div class="card-val">{{ check.type_fail }}</div>
    <div class="card-lbl">Type Issues</div>
  </div>
  <div class="card {% if check.omniclass_fail == 0 %}green{% elif check.omniclass_fail < 5 %}amber{% else %}red{% endif %}">
    <div class="card-val">{{ check.omniclass_fail }}</div>
    <div class="card-lbl">Classification Issues</div>
  </div>
  {% if qto %}
  <div class="card green">
    <div class="card-val">{{ qto.summary | length }}</div>
    <div class="card-lbl">Element Types (QTO)</div>
  </div>
  {% if qto.grand_total_cost %}
  <div class="card amber">
    <div class="card-val">{{ qto.currency }} {{ "{:,.0f}".format(qto.grand_total_cost) }}</div>
    <div class="card-lbl">Est. 5D Total Cost</div>
  </div>
  {% endif %}
  {% endif %}
</div>

<!-- Compliance bars -->
<div class="sec">
  <div class="sec-hdr"><span class="ico">✓</span> Model Compliance</div>
  {% set np = (check.naming_pass / check.total_elements * 100) | round(1) if check.total_elements else 100 %}
  {% set nc = 'g' if np >= 80 else ('a' if np >= 50 else 'r') %}
  <div class="bar-row">
    <span class="bar-lbl">Naming Convention</span>
    <div class="bar-track"><div class="bar-fill {{ nc }}" style="width:{{ np }}%"></div></div>
    <span class="bar-pct">{{ np }}%</span>
  </div>
  {% if check.type_eligible %}
  {% set tp = (check.type_pass / check.type_eligible * 100) | round(1) %}
  {% set tc = 'g' if tp >= 80 else ('a' if tp >= 50 else 'r') %}
  <div class="bar-row">
    <span class="bar-lbl">IFC Type Assignment</span>
    <div class="bar-track"><div class="bar-fill {{ tc }}" style="width:{{ tp }}%"></div></div>
    <span class="bar-pct">{{ tp }}%</span>
  </div>
  {% endif %}
  {% set op = (check.omniclass_pass / check.total_elements * 100) | round(1) if check.total_elements else 100 %}
  {% set oc = 'g' if op >= 80 else ('a' if op >= 50 else 'r') %}
  <div class="bar-row">
    <span class="bar-lbl">Omniclass / Classification</span>
    <div class="bar-track"><div class="bar-fill {{ oc }}" style="width:{{ op }}%"></div></div>
    <span class="bar-pct">{{ op }}%</span>
  </div>
</div>

{% if qto %}
<!-- QTO Summary table -->
<div class="sec">
  <div class="sec-hdr"><span class="ico">📐</span> 5D Quantity Take-Off Summary</div>
  <div class="tbl-wrap">
  <table>
    <thead>
      <tr>
        <th>Element Class</th>
        <th>Discipline</th>
        <th>Count</th>
        <th>Total Qty</th>
        <th>Unit</th>
        {% if qto.grand_total_cost %}<th>Unit Rate ({{ qto.currency }})</th><th>Total Cost ({{ qto.currency }})</th>{% endif %}
      </tr>
    </thead>
    <tbody>
    {% for row in qto.summary %}
      <tr>
        <td class="mono">{{ row.element_class }}</td>
        <td><span class="disc">{{ row.discipline }}</span></td>
        <td>{{ row.count }}</td>
        <td>{{ "{:,.2f}".format(row.total_quantity) if row.quantity_type != "count" else row.count }}</td>
        <td>{{ row.unit }}</td>
        {% if qto.grand_total_cost %}
        <td>{{ "{:,.2f}".format(row.total_cost / row.total_quantity) if row.total_cost and row.total_quantity else "—" }}</td>
        <td>{{ "{:,.2f}".format(row.total_cost) if row.total_cost else "—" }}</td>
        {% endif %}
      </tr>
    {% endfor %}
    {% if qto.grand_total_cost %}
    <tr style="font-weight:700;background:#0f2744">
      <td colspan="5">Grand Total</td>
      <td></td>
      <td>{{ "{:,.2f}".format(qto.grand_total_cost) }}</td>
    </tr>
    {% endif %}
    </tbody>
  </table>
  </div>
</div>
{% endif %}

{% if check.naming_issues %}
<!-- Naming issues -->
<div class="sec">
  <div class="sec-hdr"><span class="ico">🏷</span> Naming Convention Issues ({{ check.naming_issues | length }})</div>
  <div class="tbl-wrap">
  <table>
    <thead><tr><th>ID</th><th>Class</th><th>Name</th><th>Issue</th><th>Severity</th></tr></thead>
    <tbody>
    {% for i in check.naming_issues %}
    <tr>
      <td class="mono">{{ i.element_id }}</td>
      <td class="mono">{{ i.element_class }}</td>
      <td>{{ i.name }}</td>
      <td>{{ i.issue }}</td>
      <td><span class="sev {{ i.severity }}">{{ i.severity | upper }}</span></td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  </div>
</div>
{% endif %}

{% if check.type_issues %}
<!-- Type issues -->
<div class="sec">
  <div class="sec-hdr"><span class="ico">🔗</span> IFC Type Assignment Issues ({{ check.type_issues | length }})</div>
  <div class="tbl-wrap">
  <table>
    <thead><tr><th>ID</th><th>Class</th><th>Name</th><th>Issue</th></tr></thead>
    <tbody>
    {% for i in check.type_issues %}
    <tr>
      <td class="mono">{{ i.element_id }}</td>
      <td class="mono">{{ i.element_class }}</td>
      <td>{{ i.name }}</td>
      <td>{{ i.issue }}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  </div>
</div>
{% endif %}

{% if check.omniclass_issues %}
<!-- Omniclass issues -->
<div class="sec">
  <div class="sec-hdr"><span class="ico">🏷</span> Omniclass / Classification Issues ({{ check.omniclass_issues | length }})</div>
  <div class="tbl-wrap">
  <table>
    <thead><tr><th>ID</th><th>Class</th><th>Name</th><th>Issue</th></tr></thead>
    <tbody>
    {% for i in check.omniclass_issues %}
    <tr>
      <td class="mono">{{ i.element_id }}</td>
      <td class="mono">{{ i.element_class }}</td>
      <td>{{ i.name }}</td>
      <td>{{ i.issue }}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  </div>
</div>
{% endif %}

</main>
<footer>BIM Coordination AI &nbsp;·&nbsp; Advisory output — verify all findings before coordination submission</footer>
</body>
</html>"""

# ── Excel colour palette (ARGB hex, no alpha prefix needed for openpyxl) ─────

_DARK_BLUE = "FF1e3a5f"
_MID_BLUE = "FF1e293b"
_HEADER_FONT = Font(name="Calibri", bold=True, color="FFFFFFFF", size=10)
_HEADER_FILL = PatternFill("solid", fgColor="FF1e3a5f")
_ALT_FILL = PatternFill("solid", fgColor="FF1e293b")
_RED_FILL = PatternFill("solid", fgColor="FF7f1d1d")
_AMBER_FILL = PatternFill("solid", fgColor="FF78350f")
_GREEN_FILL = PatternFill("solid", fgColor="FF14532d")

_SEV_FILL = {
    Priority.CRITICAL: _RED_FILL,
    Priority.HIGH: _AMBER_FILL,
    Priority.MEDIUM: PatternFill("solid", fgColor="FF1e3a5f"),
    Priority.LOW: _GREEN_FILL,
}


def _apply_header(ws, headers: list[str], widths: list[int]) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = width


def _alt_row_fill(ws, row_idx: int) -> None:
    if row_idx % 2 == 0:
        for cell in ws[row_idx]:
            cell.fill = _ALT_FILL


# ── Report service ────────────────────────────────────────────────────────────

class ReportService:
    def __init__(self) -> None:
        self._jinja_env = Environment(autoescape=select_autoescape(["html"]))
        self._jinja_env.filters["basename"] = lambda p: p.split("\\")[-1].split("/")[-1]
        self._tmpl = self._jinja_env.from_string(_HTML_TEMPLATE)

    def generate_html(
        self,
        check: IFCCheckSummary,
        qto: QTOResult | None = None,
    ) -> str:
        return self._tmpl.render(
            check=check,
            qto=qto,
            generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        )

    def generate_excel(
        self,
        check: IFCCheckSummary,
        qto: QTOResult | None = None,
    ) -> bytes:
        wb = openpyxl.Workbook()

        # ── Sheet 1: Summary ─────────────────────────────────────────────────
        ws_sum = wb.active
        ws_sum.title = "Summary"
        ws_sum.sheet_view.showGridLines = False

        summary_rows = [
            ("Project", check.project_name),
            ("IFC File", check.file_path),
            ("IFC Schema", check.ifc_schema),
            ("Generated", datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")),
            ("", ""),
            ("Total Elements", check.total_elements),
            ("Overall Compliance %", check.overall_compliance_pct),
            ("", ""),
            ("Naming Pass", check.naming_pass),
            ("Naming Fail", check.naming_fail),
            ("Type Eligible", check.type_eligible),
            ("Type Pass", check.type_pass),
            ("Type Fail", check.type_fail),
            ("Omniclass Pass", check.omniclass_pass),
            ("Omniclass Fail", check.omniclass_fail),
        ]
        if qto:
            summary_rows += [
                ("", ""),
                ("QTO Grand Total Cost", qto.grand_total_cost or "—"),
                ("Currency", qto.currency),
            ]

        ws_sum.column_dimensions["A"].width = 28
        ws_sum.column_dimensions["B"].width = 52
        for row in summary_rows:
            ws_sum.append(list(row))
        # Bold labels
        for row in ws_sum.iter_rows(min_row=1, max_row=ws_sum.max_row, min_col=1, max_col=1):
            for cell in row:
                cell.font = Font(bold=True, size=10)

        # ── Sheet 2: QTO ─────────────────────────────────────────────────────
        if qto:
            ws_qto = wb.create_sheet("QTO")
            ws_qto.sheet_view.showGridLines = False
            headers = ["Element Class", "Discipline", "Count",
                       "Total Quantity", "Unit", "Quantity Type"]
            widths = [28, 16, 10, 18, 8, 14]
            if qto.grand_total_cost:
                headers += ["Total Cost", qto.currency]
                widths += [16, 10]
            _apply_header(ws_qto, headers, widths)

            for idx, row in enumerate(qto.summary, start=2):
                data = [
                    row.element_class, row.discipline.value, row.count,
                    round(row.total_quantity, 4), row.unit, row.quantity_type,
                ]
                if qto.grand_total_cost:
                    data.append(row.total_cost)
                ws_qto.append(data)
                _alt_row_fill(ws_qto, idx)

            if qto.grand_total_cost:
                grand_row = ["", "", "", "", "", "", "GRAND TOTAL", qto.grand_total_cost]
                ws_qto.append(grand_row)
                for cell in ws_qto[ws_qto.max_row]:
                    cell.font = Font(bold=True)

        # ── Sheet 3: Naming Issues ────────────────────────────────────────────
        if check.naming_issues:
            ws_n = wb.create_sheet("Naming Issues")
            ws_n.sheet_view.showGridLines = False
            _apply_header(
                ws_n,
                ["Element ID", "Class", "Name", "Issue", "Severity"],
                [14, 26, 28, 60, 12],
            )
            for idx, issue in enumerate(check.naming_issues, start=2):
                ws_n.append([
                    issue.element_id, issue.element_class, issue.name,
                    issue.issue, issue.severity.value.upper(),
                ])
                sev_cell = ws_n.cell(idx, 5)
                sev_cell.fill = _SEV_FILL.get(issue.severity, _ALT_FILL)
                sev_cell.font = Font(bold=True, color="FFFFFFFF")
                _alt_row_fill(ws_n, idx)

        # ── Sheet 4: Type Issues ──────────────────────────────────────────────
        if check.type_issues:
            ws_t = wb.create_sheet("Type Issues")
            ws_t.sheet_view.showGridLines = False
            _apply_header(ws_t, ["Element ID", "Class", "Name", "Issue"], [14, 26, 28, 70])
            for idx, issue in enumerate(check.type_issues, start=2):
                ws_t.append([issue.element_id, issue.element_class, issue.name, issue.issue])
                _alt_row_fill(ws_t, idx)

        # ── Sheet 5: Omniclass Issues ─────────────────────────────────────────
        if check.omniclass_issues:
            ws_o = wb.create_sheet("Omniclass Issues")
            ws_o.sheet_view.showGridLines = False
            _apply_header(ws_o, ["Element ID", "Class", "Name", "Issue"], [14, 26, 28, 70])
            for idx, issue in enumerate(check.omniclass_issues, start=2):
                ws_o.append([issue.element_id, issue.element_class, issue.name, issue.issue])
                _alt_row_fill(ws_o, idx)

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()


report_service = ReportService()
