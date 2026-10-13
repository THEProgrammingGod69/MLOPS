"""Dashboard-as-code for the Grafana "MLOps Command Center".

Run from the project root to regenerate the provisioned JSON:

    python monitoring/grafana/build_dashboard.py

``tests/test_grafana_dashboard.py`` fails if the committed JSON and this generator
drift apart, and checks that every PromQL query references a metric the service
actually exports. Colours follow the validated reference palette used by the web UI:
status colours for risk tiers and drift states, categorical slots for models, and a
single-hue ramp for ordered latency quantiles.
"""
import json
import os

OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboards", "prediction_dashboard.json")
DS = {"type": "prometheus", "uid": "${datasource}"}
SEL = 'job=~"$job", instance=~"$instance"'

GOOD, WARN, SERIOUS, CRIT = "#0ca30c", "#fab219", "#ec835a", "#d03b3b"
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
BLUE_RAMP = ["#86b6ef", "#3987e5", "#256abf", "#104281"]
TIER_COLORS = {"LOW": GOOD, "MODERATE": WARN, "HIGH": SERIOUS, "CRITICAL": CRIT}
MODEL_COLORS = {"lr": SERIES[0], "rf": SERIES[1], "xgb": SERIES[2]}
MODEL_NAMES = {"lr": "Logistic Regression", "rf": "Random Forest", "xgb": "XGBoost (deployed)"}
TIERS = ["LOW", "MODERATE", "HIGH", "CRITICAL"]

_next_id = [0]


def _id():
    _next_id[0] += 1
    return _next_id[0]


# ----------------------------------------------------------------------------- helpers
def target(expr, legend="", ref="A", instant=False, fmt="time_series", interval=None):
    t = {"datasource": DS, "editorMode": "code", "expr": expr, "legendFormat": legend, "refId": ref,
         "range": not instant, "instant": instant, "format": fmt}
    if interval:
        t["interval"] = interval
    return t


def thresholds(*steps):
    """steps: (color, value) pairs; the first value is the base (None)."""
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in steps]}


def by_name(name, color):
    return {"matcher": {"id": "byName", "options": name},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}]}


def row(title, y, collapsed=False):
    return {"type": "row", "title": title, "id": _id(), "collapsed": collapsed, "panels": [],
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}}


def text(content, x, y, w, h, title=""):
    return {"type": "text", "title": title, "id": _id(), "gridPos": {"h": h, "w": w, "x": x, "y": y},
            "options": {"mode": "markdown", "content": content}, "transparent": True}


def stat(title, targets, x, y, w=3, h=4, unit="short", th=None, decimals=None, mappings=None,
         color_mode="value", graph="area", description="", no_value=None, text_size=None, text_mode="auto"):
    defaults = {"unit": unit, "color": {"mode": "thresholds"},
                "thresholds": th or thresholds(("#3987e5", None)), "mappings": mappings or []}
    if decimals is not None:
        defaults["decimals"] = decimals
    if no_value:
        defaults["noValue"] = no_value
    options = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
               "colorMode": color_mode, "graphMode": graph, "justifyMode": "auto", "textMode": text_mode,
               "orientation": "auto", "wideLayout": True, "showPercentChange": False}
    if text_size:
        options["text"] = {"valueSize": text_size}
    return {"type": "stat", "title": title, "id": _id(), "datasource": DS, "description": description,
            "gridPos": {"h": h, "w": w, "x": x, "y": y}, "targets": targets,
            "fieldConfig": {"defaults": defaults, "overrides": []}, "options": options}


def gauge(title, targets, x, y, w, h, unit, th, minimum=0, maximum=1, description=""):
    return {"type": "gauge", "title": title, "id": _id(), "datasource": DS, "description": description,
            "gridPos": {"h": h, "w": w, "x": x, "y": y}, "targets": targets,
            "fieldConfig": {"defaults": {"unit": unit, "min": minimum, "max": maximum, "thresholds": th,
                                         "color": {"mode": "thresholds"}}, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "showThresholdLabels": False, "showThresholdMarkers": True, "orientation": "auto"}}


def timeseries(title, targets, x, y, w, h, unit="short", overrides=None, stack=False, bars=False,
               fill=12, th=None, th_style="off", soft_max=None, minimum=0, description="",
               legend_calcs=("mean", "max", "lastNotNull"), legend_mode="table", color_mode="palette-classic",
               decimals=None):
    custom = {"drawStyle": "bars" if bars else "line", "lineWidth": 2, "fillOpacity": 70 if bars else fill,
              "gradientMode": "none" if bars else "opacity", "showPoints": "never", "pointSize": 4,
              "spanNulls": True, "lineInterpolation": "smooth", "barAlignment": 0, "axisBorderShow": False,
              "axisCenteredZero": False, "axisPlacement": "auto", "axisSoftMin": minimum,
              "stacking": {"mode": "normal" if stack else "none", "group": "A"},
              "thresholdsStyle": {"mode": th_style}, "hideFrom": {"legend": False, "tooltip": False, "viz": False},
              "scaleDistribution": {"type": "linear"}}
    if soft_max is not None:
        custom["axisSoftMax"] = soft_max
    defaults = {"unit": unit, "custom": custom, "color": {"mode": color_mode},
                "thresholds": th or thresholds(("green", None))}
    if decimals is not None:
        defaults["decimals"] = decimals
    return {"type": "timeseries", "title": title, "id": _id(), "datasource": DS, "description": description,
            "gridPos": {"h": h, "w": w, "x": x, "y": y}, "targets": targets,
            "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
            "options": {"legend": {"showLegend": True, "displayMode": legend_mode, "placement": "bottom",
                                   "calcs": list(legend_calcs)},
                        "tooltip": {"mode": "multi", "sort": "desc"}}}


def bargauge(title, targets, x, y, w, h, unit="short", th=None, overrides=None, minimum=0, maximum=None,
             display="gradient", description="", values=False, decimals=None, color_mode="thresholds",
             transformations=None, orientation="horizontal", text_size=None, no_value=None):
    defaults = {"unit": unit, "min": minimum, "thresholds": th or thresholds(("#3987e5", None)),
                "color": {"mode": color_mode, "fixedColor": "#3987e5"} if color_mode == "fixed" else {"mode": color_mode}}
    if maximum is not None:
        defaults["max"] = maximum
    if decimals is not None:
        defaults["decimals"] = decimals
    if no_value:
        defaults["noValue"] = no_value
    panel = {"type": "bargauge", "title": title, "id": _id(), "datasource": DS, "description": description,
             "gridPos": {"h": h, "w": w, "x": x, "y": y}, "targets": targets,
             "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
             "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": values},
                         "orientation": orientation, "displayMode": display, "valueMode": "color",
                         "namePlacement": "auto", "showUnfilled": True, "sizing": "auto",
                         "minVizHeight": 16, "minVizWidth": 8, "maxVizHeight": 300}}
    if text_size:
        panel["options"]["text"] = {"titleSize": text_size[0], "valueSize": text_size[1]}
    if transformations:
        panel["transformations"] = transformations
    return panel


def piechart(title, targets, x, y, w, h, overrides=None, unit="short", description="", values=("percent",)):
    return {"type": "piechart", "title": title, "id": _id(), "datasource": DS, "description": description,
            "gridPos": {"h": h, "w": w, "x": x, "y": y}, "targets": targets,
            "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "palette-classic"},
                                         "custom": {"hideFrom": {"legend": False, "tooltip": False, "viz": False}}},
                            "overrides": overrides or []},
            "options": {"pieType": "donut", "displayLabels": [],
                        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "legend": {"showLegend": True, "displayMode": "table", "placement": "right",
                                   "values": list(values)},
                        "tooltip": {"mode": "single", "sort": "none"}}}


def heatmap(title, targets, x, y, w, h, scheme="Blues", y_unit="short", description="", y_decimals=None):
    y_axis = {"axisPlacement": "left", "unit": y_unit, "reverse": False}
    if y_decimals is not None:
        y_axis["decimals"] = y_decimals
    return {"type": "heatmap", "title": title, "id": _id(), "datasource": DS, "description": description,
            "gridPos": {"h": h, "w": w, "x": x, "y": y}, "targets": targets, "maxDataPoints": 60,
            "fieldConfig": {"defaults": {"custom": {"hideFrom": {"legend": False, "tooltip": False, "viz": False},
                                                    "scaleDistribution": {"type": "linear"}}}, "overrides": []},
            "options": {"calculate": False, "cellGap": 1, "cellValues": {"unit": "short"},
                        "color": {"mode": "scheme", "scheme": scheme, "steps": 64, "exponent": 0.5,
                                  "fill": "dark-orange", "reverse": False, "scale": "exponential"},
                        "exemplars": {"color": "rgba(255,0,255,0.7)"}, "filterValues": {"le": 1e-9},
                        "legend": {"show": True}, "rowsFrame": {"layout": "auto"},
                        "tooltip": {"mode": "single", "showColorScale": False, "yHistogram": True},
                        "yAxis": y_axis}}


def state_timeline(title, targets, x, y, w, h, mappings, th, description=""):
    return {"type": "state-timeline", "title": title, "id": _id(), "datasource": DS, "description": description,
            "gridPos": {"h": h, "w": w, "x": x, "y": y}, "targets": targets,
            "fieldConfig": {"defaults": {"color": {"mode": "fixed", "fixedColor": "#898781"}, "thresholds": th,
                                         "mappings": mappings,
                                         "custom": {"fillOpacity": 85, "lineWidth": 0,
                                                    "hideFrom": {"legend": False, "tooltip": False, "viz": False}}},
                            "overrides": []},
            "options": {"showValue": "never", "rowHeight": 0.85, "mergeValues": True, "alignValue": "left",
                        "legend": {"showLegend": True, "displayMode": "list", "placement": "bottom"},
                        "tooltip": {"mode": "single", "sort": "none"}}}


def table(title, targets, x, y, w, h, transformations=None, overrides=None, unit="short", description="",
          decimals=None, sort_by=None):
    defaults = {"unit": unit, "custom": {"align": "auto", "cellOptions": {"type": "auto"}, "inspect": False},
                "thresholds": thresholds(("text", None)), "color": {"mode": "thresholds"}}
    if decimals is not None:
        defaults["decimals"] = decimals
    options = {"showHeader": True, "cellHeight": "sm", "footer": {"show": False, "reducer": ["sum"], "fields": ""}}
    if sort_by:
        options["sortBy"] = sort_by
    return {"type": "table", "title": title, "id": _id(), "datasource": DS, "description": description,
            "gridPos": {"h": h, "w": w, "x": x, "y": y}, "targets": targets,
            "transformations": transformations or [],
            "fieldConfig": {"defaults": defaults, "overrides": overrides or []}, "options": options}


def barchart(title, targets, x, y, w, h, x_field, transformations, overrides=None, unit="short",
             soft_max=None, description="", show_value="never"):
    custom = {"lineWidth": 0, "fillOpacity": 85, "gradientMode": "none", "axisPlacement": "auto",
              "axisSoftMin": 0, "hideFrom": {"legend": False, "tooltip": False, "viz": False},
              "scaleDistribution": {"type": "linear"}, "axisBorderShow": False}
    if soft_max is not None:
        custom["axisSoftMax"] = soft_max
    return {"type": "barchart", "title": title, "id": _id(), "datasource": DS, "description": description,
            "gridPos": {"h": h, "w": w, "x": x, "y": y}, "targets": targets, "transformations": transformations,
            "fieldConfig": {"defaults": {"unit": unit, "custom": custom, "color": {"mode": "palette-classic"},
                                         "thresholds": thresholds(("green", None))},
                            "overrides": overrides or []},
            "options": {"xField": x_field, "orientation": "vertical", "barWidth": 0.85, "groupWidth": 0.75,
                        "barRadius": 0.08, "showValue": show_value, "stacking": "none", "fullHighlight": False,
                        "xTickLabelRotation": 0, "xTickLabelSpacing": 0,
                        "legend": {"showLegend": True, "displayMode": "list", "placement": "bottom", "calcs": []},
                        "tooltip": {"mode": "multi", "sort": "none"}}}


def matrix(row_field, column_field):
    return {"id": "groupingToMatrix", "options": {"rowField": row_field, "columnField": column_field,
                                                    "valueField": "Value", "emptyValue": "null"}}


TIER_STATUS_TH = thresholds((GOOD, None), (WARN, 0.2), (SERIOUS, 0.3), (CRIT, 0.5))
PCT_TH_ERRORS = thresholds((GOOD, None), (WARN, 0.01), (CRIT, 0.1))
TIER_OVERRIDES = [by_name(t, c) for t, c in TIER_COLORS.items()]
QUANTILE_OVERRIDES = [by_name(n, c) for n, c in zip(["p50", "p90", "p95", "p99"], BLUE_RAMP)]
DRIFT_PSI_TH = thresholds((GOOD, None), (WARN, 0.1), (CRIT, 0.25))
DRIFT_TVD_TH = thresholds((GOOD, None), (WARN, 0.05), (CRIT, 0.15))
FAIRNESS_TH = thresholds((GOOD, None), (WARN, 0.05), (CRIT, 0.1))


def rate(metric, extra="", by=None, window="$__rate_interval"):
    selector = f"{{{SEL}{', ' + extra if extra else ''}}}"
    inner = f"rate({metric}{selector}[{window}])"
    return f"sum by ({by}) ({inner})" if by else f"sum({inner})"


def quantile(q, metric, extra="", by="le"):
    selector = f"{{{SEL}{', ' + extra if extra else ''}}}"
    return f"histogram_quantile({q}, sum by ({by}) (rate({metric}_bucket{selector}[$__rate_interval])))"


# Shared PromQL fragments, built outside f-strings (backslashes in f-string expressions need Python 3.12).
PREDICT_ROUTES = 'route=~".*predict.*"'
APPLIED = 'status="applied"'
APPLIED_FLAGGED = 'status="applied", decision="1"'
REJECTED = 'status=~"4..", route=~".*predict.*"'


# ----------------------------------------------------------------------------- dashboard
def build():
    _next_id[0] = 0
    panels = []
    y = 0

    panels.append(text(
        "### 🎓 Student Dropout Early Warning — MLOps Command Center\n"
        "Live **service health**, **prediction behaviour**, **data drift** and **operational alerts** from the "
        "FastAPI `/metrics` endpoint, side by side with the **offline model quality, fairness and explainability** "
        "results the batch pipeline publishes. Risk tiers use status colours "
        "(<span style=\"color:#0ca30c\">LOW</span> · <span style=\"color:#fab219\">MODERATE</span> · "
        "<span style=\"color:#ec835a\">HIGH</span> · <span style=\"color:#d03b3b\">CRITICAL</span>). "
        "Use the **model / split / attribute** selectors for the offline rows.",
        0, y, 24, 3))
    y += 3

    # ------------------------------------------------------------------ KPI strip
    panels.append(row("Service health at a glance", y)); y += 1
    up_map = [{"type": "value", "options": {"0": {"text": "DOWN", "color": CRIT}, "1": {"text": "UP", "color": GOOD}}}]
    loaded_map = [{"type": "value", "options": {"0": {"text": "Not loaded", "color": CRIT},
                                                "1": {"text": "Loaded", "color": GOOD}}}]
    panels += [
        stat("API status", [target(f"max(up{{{SEL}}})")], 0, y, mappings=up_map, color_mode="background",
             graph="none", th=thresholds((CRIT, None), (GOOD, 1)), no_value="DOWN",
             description="Prometheus scrape health of the inference API."),
        stat("Risk model", [target(f"max(student_dropout_model_loaded{{{SEL}}})")], 3, y, mappings=loaded_map,
             color_mode="background", graph="none", th=thresholds((CRIT, None), (GOOD, 1)), no_value="Unknown",
             description="1 when the XGBoost pipeline and intervention rules are loaded."),
        stat("Uptime", [target(f"time() - max(student_dropout_app_start_time_seconds{{{SEL}}})")], 6, y,
             unit="dtdurations", graph="none", th=thresholds(("#3987e5", None)), description="Since the API process started."),
        stat("Scored / s", [target(rate("student_dropout_predictions_total"))], 9, y, unit="short",
             decimals=2, th=thresholds(("#3987e5", None)), description="Single + batch predictions per second."),
        stat("Error ratio", [target(f"({rate('student_dropout_prediction_errors_total')}) / clamp_min({rate('student_dropout_prediction_requests_total')}, 1e-9)")],
             12, y, unit="percentunit", decimals=2, th=PCT_TH_ERRORS,
             description="Failed prediction requests / all prediction requests. Alert at 10 %."),
        stat("Latency p95", [target(quantile(0.95, "student_dropout_prediction_latency_seconds"))], 15, y, unit="s",
             th=thresholds((GOOD, None), (WARN, 0.5), (CRIT, 1)), description="95th percentile prediction latency. Alert at 1 s."),
        stat("Review rate", [target(f"max(student_dropout_window_review_rate{{{SEL}}})")], 18, y,
             unit="percentunit", decimals=1, th=thresholds((GOOD, None), (WARN, 0.25), (CRIT, 0.35)),
             no_value="No data", description="Share of the live window routed to a human advisor (HIGH + CRITICAL)."),
        stat("Drifting features", [target(f"sum(student_dropout_drifted_features{{{SEL}}})")], 21, y,
             th=thresholds((GOOD, None), (WARN, 1), (CRIT, 3)), graph="none", no_value="Warming up",
             description="Features at moderate or substantial drift vs the training reference profile."),
    ]
    y += 4
    panels += [
        stat("Students scored (total)", [target(f"sum(student_dropout_predictions_total{{{SEL}}})")], 0, y, w=4,
             th=thresholds(("#3987e5", None)), description="Cumulative since process start."),
        gauge("Mean predicted risk", [target(f"max(student_dropout_window_mean_risk{{{SEL}}})")], 4, y, 4, 4,
              "percentunit", TIER_STATUS_TH, description="Mean dropout probability in the live window, banded by tier cut-offs."),
        stat("Critical tier share", [target(f"max(student_dropout_window_tier_share{{{SEL}, risk_tier=\"CRITICAL\"}})")],
             8, y, w=4, unit="percentunit", decimals=1, th=thresholds((GOOD, None), (WARN, 0.1), (CRIT, 0.2)),
             description="Share of the live window in the CRITICAL tier (validation baseline ≈ 3.5 %)."),
        stat("SHAP explanation share", [target(f"({rate('student_dropout_explanations_total')}) / clamp_min({rate('student_dropout_predictions_total')}, 1e-9)")],
             12, y, w=4, unit="percentunit", decimals=1, th=thresholds(("#9085e9", None)),
             description="Share of scored students that received a SHAP explanation."),
        stat("Fairness applied", [target(f"({rate('student_dropout_fairness_decisions_total', APPLIED)}) / clamp_min({rate('student_dropout_fairness_decisions_total')}, 1e-9)")],
             16, y, w=4, unit="percentunit", decimals=1, th=thresholds(("#199e70", None)),
             description="Share of predictions where the ThresholdOptimizer decision was applied (gender supplied)."),
        stat("Firing alerts", [target('count(ALERTS{alertstate="firing"}) or vector(0)')], 20, y, w=4,
             th=thresholds((GOOD, None), (CRIT, 1)), color_mode="background", graph="none",
             description="Prometheus alert rules currently firing (see Alerts row)."),
    ]
    y += 4

    # ------------------------------------------------------------------ RED
    panels.append(row("Traffic & reliability (RED)", y)); y += 1
    panels += [
        timeseries("Prediction Request Rate",
                   [target(rate("student_dropout_http_requests_total", PREDICT_ROUTES, by="route"), "{{route}}")],
                   0, y, 8, 8, unit="reqps", stack=True, description="Prediction requests per second by endpoint."),
        timeseries("Students scored by source",
                   [target(rate("student_dropout_predictions_total", by="source"), "{{source}}")],
                   8, y, 8, 8, unit="short", stack=True,
                   overrides=[by_name("single", SERIES[0]), by_name("batch", SERIES[6])],
                   description="Students per second, single requests vs batch jobs."),
        timeseries("HTTP responses by status",
                   [target(rate("student_dropout_http_requests_total", f'status=~"{c}.."'), f"{c}xx", ref=chr(65 + i))
                    for i, c in enumerate("2345")],
                   16, y, 8, 8, unit="reqps", stack=True,
                   overrides=[by_name("2xx", GOOD), by_name("3xx", SERIES[0]), by_name("4xx", WARN), by_name("5xx", CRIT)],
                   description="All API traffic (excluding Prometheus scrapes) grouped by status class."),
    ]
    y += 8
    panels += [
        timeseries("Prediction Error Rate",
                   [target(f"({rate('student_dropout_prediction_errors_total')}) / clamp_min({rate('student_dropout_prediction_requests_total')}, 1e-9)", "server errors"),
                    target(f"({rate('student_dropout_http_requests_total', REJECTED)}) / clamp_min({rate('student_dropout_http_requests_total', PREDICT_ROUTES)}, 1e-9)", "rejected inputs (4xx)", ref="B")],
                   0, y, 8, 8, unit="percentunit", th=thresholds(("transparent", None), (CRIT, 0.1)), th_style="dashed",
                   overrides=[by_name("server errors", CRIT), by_name("rejected inputs (4xx)", WARN)],
                   description="Share of prediction requests failing server-side, and share rejected by input validation. Dashed line: 10 % alert threshold."),
        timeseries("Prediction Latency",
                   [target(quantile(q, "student_dropout_prediction_latency_seconds"), f"p{int(q * 100)}", ref=r)
                    for q, r in ((0.5, "A"), (0.9, "B"), (0.95, "C"), (0.99, "D"))],
                   8, y, 8, 8, unit="s", overrides=QUANTILE_OVERRIDES, th=thresholds(("transparent", None), (CRIT, 1)),
                   th_style="dashed", fill=0, description="Single-prediction latency quantiles. Dashed line: 1 s p95 alert."),
        heatmap("Latency distribution", [target(f"sum by (le) (increase(student_dropout_prediction_latency_seconds_bucket{{{SEL}}}[$__interval]))", "{{le}}", fmt="heatmap", interval="15s")],
                16, y, 8, 8, scheme="Blues", y_unit="s", description="Every prediction request bucketed by latency over time."),
    ]
    y += 8
    panels += [
        timeseries("Apdex (T = 100 ms)",
                   [target(f'(sum(rate(student_dropout_prediction_latency_seconds_bucket{{{SEL}, le="0.1"}}[$__rate_interval])) + sum(rate(student_dropout_prediction_latency_seconds_bucket{{{SEL}, le="0.5"}}[$__rate_interval]))) / 2 / clamp_min(sum(rate(student_dropout_prediction_latency_seconds_count{{{SEL}}}[$__rate_interval])), 1e-9)', "Apdex")],
                   0, y, 8, 7, unit="percentunit", minimum=0, soft_max=1, overrides=[by_name("Apdex", SERIES[2])],
                   th=thresholds((CRIT, None), (WARN, 0.85), (GOOD, 0.94)), th_style="area",
                   legend_calcs=("mean", "min", "lastNotNull"),
                   description="Satisfied ≤ 100 ms, tolerating ≤ 500 ms. Bands: green ≥ 0.94, amber ≥ 0.85."),
        timeseries("p95 latency by endpoint",
                   [target(quantile(0.95, "student_dropout_http_request_duration_seconds", by="le, route"), "{{route}}")],
                   8, y, 8, 7, unit="s", fill=0, description="Server-side request duration per route (includes batch and insights endpoints)."),
        timeseries("Batch scoring",
                   [target(quantile(0.5, "student_dropout_batch_size"), "p50 students / batch"),
                    target(quantile(0.95, "student_dropout_batch_size"), "p95 students / batch", ref="B")],
                   16, y, 8, 7, unit="short", fill=0,
                   overrides=[by_name("p50 students / batch", BLUE_RAMP[0]), by_name("p95 students / batch", BLUE_RAMP[2])],
                   description="Distribution of batch sizes (students per /predict/batch call)."),
    ]
    y += 7

    # ------------------------------------------------------------------ Predictions
    panels.append(row("Prediction analytics", y)); y += 1
    panels += [
        piechart("Risk tier mix (live window)",
                 [target(f'max by (risk_tier) (student_dropout_window_tier_share{{{SEL}, risk_tier="{t}"}})', t, ref=chr(65 + i))
                  for i, t in enumerate(TIERS)],
                 0, y, 7, 9, overrides=TIER_OVERRIDES, unit="percentunit", values=("percent",),
                 description="Share of each risk tier among the most recent students scored."),
        timeseries("Students scored by risk tier",
                   [target(f'sum by (risk_tier) (increase(student_dropout_predictions_total{{{SEL}, risk_tier="{t}"}}[$__interval]))', t, ref=chr(65 + i), interval="30s")
                    for i, t in enumerate(TIERS)],
                   7, y, 9, 9, unit="short", stack=True, bars=True, overrides=TIER_OVERRIDES,
                   legend_calcs=(), legend_mode="list", description="Students per interval, stacked by tier."),
        heatmap("Risk score distribution over time",
                [target(f"sum by (le) (increase(student_dropout_risk_probability_bucket{{{SEL}}}[$__interval]))", "{{le}}", fmt="heatmap", interval="30s")],
                16, y, 8, 9, scheme="Oranges", y_unit="percentunit",
                description="Predicted dropout probability histogram (5 % buckets) per interval."),
    ]
    y += 9
    panels += [
        timeseries("Risk score quantiles",
                   [target(quantile(0.5, "student_dropout_risk_probability"), "p50"),
                    target(quantile(0.9, "student_dropout_risk_probability"), "p90", ref="B"),
                    target(f"max(student_dropout_window_mean_risk{{{SEL}}})", "window mean", ref="C")],
                   0, y, 8, 8, unit="percentunit", fill=0, soft_max=1,
                   overrides=[by_name("p50", BLUE_RAMP[0]), by_name("p90", BLUE_RAMP[2]), by_name("window mean", SERIES[1])],
                   th=thresholds(("transparent", None), (WARN, 0.2), (SERIOUS, 0.3), (CRIT, 0.5)), th_style="dashed",
                   description="Dashed lines mark the MODERATE / HIGH / CRITICAL cut-offs (0.2 / 0.3 / 0.5)."),
        bargauge("Recommended interventions",
                 [target(f"sum by (intervention_level) (increase(student_dropout_interventions_total{{{SEL}}}[$__range]))", "{{intervention_level}}", instant=True)],
                 8, y, 8, 8, th=thresholds(("#3987e5", None)), display="gradient", decimals=0,
                 overrides=[by_name("monitoring", GOOD), by_name("academic check-in", WARN),
                            by_name("advisor/tutor outreach", SERIOUS), by_name("priority human review", CRIT)],
                 color_mode="fixed", description="Interventions recommended in the selected time range."),
        timeseries("Human review inflow",
                   [target(f"{rate('student_dropout_human_review_required_total')} * 60", "students / min to advisors")],
                   16, y, 8, 8, unit="short", overrides=[by_name("students / min to advisors", CRIT)],
                   description="Students per minute flagged for human review (HIGH and CRITICAL tiers)."),
    ]
    y += 8
    panels += [
        piechart("Fairness post-processing outcomes",
                 [target(f"sum by (status) (increase(student_dropout_fairness_decisions_total{{{SEL}}}[$__range]))", "{{status}}", instant=True)],
                 0, y, 8, 8, overrides=[by_name("applied", SERIES[2]), by_name("not_requested_or_unavailable", "#898781"),
                                        by_name("unsupported_gender", WARN), by_name("error", CRIT)],
                 values=("value", "percent"), description="Whether the ThresholdOptimizer decision could be applied."),
        timeseries("Fairness-adjusted flag rate",
                   [target(f"({rate('student_dropout_fairness_decisions_total', APPLIED_FLAGGED)}) / clamp_min({rate('student_dropout_fairness_decisions_total', APPLIED)}, 1e-9)", "flagged by post-processor"),
                    target(f"max(student_dropout_window_review_rate{{{SEL}}})", "human review rate (tiers)", ref="B")],
                   8, y, 8, 8, unit="percentunit", fill=0,
                   overrides=[by_name("flagged by post-processor", SERIES[2]), by_name("human review rate (tiers)", SERIES[1])],
                   description="Share flagged by the fairness-adjusted decision vs share routed to review by risk tier."),
        bargauge("Null inputs by feature",
                 [target(f"sum by (feature) (increase(student_dropout_missing_feature_values_total{{{SEL}}}[$__range])) / scalar(clamp_min(sum(increase(student_dropout_predictions_total{{{SEL}}}[$__range])), 1)) > 0", "{{feature}}", instant=True)],
                 16, y, 8, 8, unit="percentunit", decimals=1, maximum=1,
                 th=thresholds(("#3987e5", None)), description="Share of scored students with a null value per nullable feature."),
    ]
    y += 8

    # ------------------------------------------------------------------ Drift
    panels.append(row("Data drift — live window vs training reference", y)); y += 1
    drift_map = [{"type": "value", "options": {"0": {"text": "Stable", "color": GOOD}, "1": {"text": "Moderate", "color": WARN},
                                                "2": {"text": "Substantial", "color": CRIT}}}]
    panels += [
        state_timeline("Drift status by feature",
                       [target(f"max by (feature) (student_dropout_feature_drift_status{{{SEL}}})", "{{feature}}")],
                       0, y, 24, 10, drift_map, thresholds((GOOD, None), (WARN, 1), (CRIT, 2)),
                       description="PSI (numeric) / TVD (categorical) status per feature over time. Starts once the window holds enough samples."),
    ]
    y += 10
    panels += [
        bargauge("PSI by feature (numeric)",
                 [target(f'max by (feature) (student_dropout_feature_drift_score{{{SEL}, metric="PSI"}})', "{{feature}}", instant=True)],
                 0, y, 10, 10, th=DRIFT_PSI_TH, decimals=3, display="lcd", maximum=0.5, text_size=(12, 18),
                 description="Population Stability Index. < 0.10 stable, 0.10–0.25 moderate, ≥ 0.25 substantial."),
        bargauge("TVD by feature (categorical)",
                 [target(f'max by (feature) (student_dropout_feature_drift_score{{{SEL}, metric="TVD"}})', "{{feature}}", instant=True)],
                 10, y, 7, 5, th=DRIFT_TVD_TH, decimals=3, display="lcd", maximum=0.3, text_size=(12, 16),
                 no_value="Needs exact profile + 1,500 samples",
                 description="Total variation distance. < 0.05 stable, 0.05–0.15 moderate, ≥ 0.15 substantial."),
        stat("Window size", [target(f"max(student_dropout_window_predictions{{{SEL}}})")], 17, y, w=4, h=5,
             th=thresholds((WARN, None), (GOOD, 500)), decimals=0,
             description="Predictions in the rolling window (max 2,000). Numeric drift needs 500, categorical 1,500."),
        stat("Reference profile", [target(f"max by (source) (student_dropout_reference_profile_info{{{SEL}}})", "{{source}}")],
             21, y, w=3, h=5, graph="none", th=thresholds(("#3987e5", None)), text_mode="name", text_size=16,
             description="Source of the drift reference (development_train = exact deciles; eda_numeric_summary = approximation)."),
    ]
    panels += [
        timeseries("Drifted features over time",
                   [target(f'max by (severity) (student_dropout_drifted_features{{{SEL}}})', "{{severity}}")],
                   10, y + 5, 14, 5, unit="short", stack=True, overrides=[by_name("moderate", WARN), by_name("substantial", CRIT)],
                   legend_calcs=(), legend_mode="list", decimals=0, soft_max=3,
                   description="Number of features in moderate / substantial drift."),
    ]
    y += 10
    panels += [
        timeseries("Feature mean relative to reference (1.0 = unchanged)",
                   [target(f"max by (feature) (student_dropout_feature_window_mean{{{SEL}}}) / on (feature) max by (feature) (student_dropout_feature_reference_mean{{{SEL}}})", "{{feature}}")],
                   0, y, 14, 9, unit="short", fill=0, minimum=None, decimals=2,
                   th=thresholds(("transparent", None)), legend_calcs=("lastNotNull", "min", "max"),
                   description="Window mean ÷ training mean per numeric feature, indexed so every feature shares one axis."),
        timeseries("PSI trend by feature",
                   [target(f'max by (feature) (student_dropout_feature_drift_score{{{SEL}, metric="PSI"}})', "{{feature}}")],
                   14, y, 10, 9, unit="short", fill=0, decimals=3, soft_max=0.3,
                   th=thresholds(("transparent", None), (WARN, 0.1), (CRIT, 0.25)), th_style="dashed",
                   legend_calcs=("lastNotNull", "max"),
                   description="How quickly each feature drifts as the window rolls. Dashed lines: 0.10 / 0.25."),
    ]
    y += 9

    # ------------------------------------------------------------------ Offline model quality
    panels.append(row("Model quality — offline evaluation ($model, $split split)", y)); y += 1
    metric_stats = [("ROC AUC", "roc_auc"), ("PR AUC", "pr_auc"), ("Recall", "recall"), ("Precision", "precision"),
                    ("F1", "f1"), ("Specificity", "specificity")]
    for i, (label, metric) in enumerate(metric_stats):
        panels.append(stat(label, [target(f'max(student_dropout_offline_model_metric{{model="$model", split="$split", metric="{metric}"}})', instant=True)],
                           i * 4, y, w=4, h=4, decimals=3, graph="none", th=thresholds(("#3987e5", None)),
                           description=f"{label} of the selected model on the selected split (reports/models/baseline_comparison.csv)."))
    y += 4
    panels += [
        barchart("Baseline comparison",
                 [target('student_dropout_offline_model_metric{split="$split", metric=~"roc_auc|pr_auc|f1|recall|precision|accuracy"}', instant=True, fmt="table")],
                 0, y, 12, 9, "metric\\model",
                 [matrix("metric", "model"),
                  {"id": "organize", "options": {"renameByName": dict(MODEL_NAMES)}}],
                 overrides=[by_name(MODEL_NAMES[m], c) for m, c in MODEL_COLORS.items()], soft_max=1,
                 description="lr = Logistic Regression, rf = Random Forest, xgb = XGBoost (deployed)."),
        bargauge("Observed withdrawal rate by risk tier",
                 [target(f'max(student_dropout_offline_risk_tier_metric{{risk_tier="{t}", metric="withdrawal_rate"}})', t, ref=chr(65 + i), instant=True)
                  for i, t in enumerate(TIERS)],
                 12, y, 6, 9, unit="percentunit", maximum=1, decimals=1, overrides=TIER_OVERRIDES, color_mode="fixed",
                 display="basic", orientation="vertical",
                 description="Validation split: share of students in each tier who actually withdrew. Rising bars = tiers separate risk."),
        bargauge("Tier population share",
                 [target(f'max(student_dropout_offline_risk_tier_metric{{risk_tier="{t}", metric="percentage"}}) / 100', t, ref=chr(65 + i), instant=True)
                  for i, t in enumerate(TIERS)],
                 18, y, 6, 9, unit="percentunit", maximum=1, decimals=1, overrides=TIER_OVERRIDES, color_mode="fixed",
                 display="basic", orientation="vertical", description="Validation split: share of students per tier."),
    ]
    y += 9
    panels += [
        barchart("Threshold trade-off (validation)",
                 [target('student_dropout_offline_threshold_sweep{metric=~"precision|recall|f1"}', instant=True, fmt="table")],
                 0, y, 12, 9, "threshold\\metric", [matrix("threshold", "metric")],
                 overrides=[by_name("precision", SERIES[0]), by_name("recall", SERIES[1]), by_name("f1", SERIES[2])],
                 soft_max=1, description="Precision / recall / F1 if a single probability threshold raised the alert."),
        bargauge("Global SHAP importance (top 15)",
                 [target("topk(15, student_dropout_offline_shap_importance)", "{{feature}}", instant=True, fmt="table")],
                 12, y, 12, 9, decimals=3, th=thresholds(("#3987e5", None)), display="gradient", values=True,
                 transformations=[{"id": "sortBy", "options": {"sort": [{"field": "Value", "desc": True}]}},
                                  {"id": "organize", "options": {"excludeByName": {
                                      "Time": True, "__name__": True, "job": True, "instance": True, "environment": True}}}],
                 text_size=(12, 14),
                 description="Mean |SHAP| per transformed feature on the validation split."),
    ]
    y += 9
    panels += [
        table("Calibration by method ($model)",
              [target(f'sum by (method) (student_dropout_offline_calibration_metric{{model="$model", metric="{m}"}})', instant=True, fmt="table", ref=r)
               for m, r in (("brier_score", "A"), ("ece", "B"), ("log_loss", "C"), ("roc_auc", "D"))],
              0, y, 12, 6, decimals=4,
              transformations=[{"id": "merge", "options": {}},
                               {"id": "organize", "options": {"excludeByName": {"Time": True},
                                                              "renameByName": {"method": "Method", "Value #A": "Brier",
                                                                               "Value #B": "ECE", "Value #C": "Log loss",
                                                                               "Value #D": "ROC AUC"}}}],
              description="Lower Brier / ECE / log loss is better. Sigmoid calibration inverted the ranking (ROC AUC < 0.5)."),
        table("Automated pipeline — latest validation run",
              [target("student_dropout_offline_pipeline_validation_metric", instant=True, fmt="table")],
              12, y, 12, 6, decimals=3,
              transformations=[{"id": "organize", "options": {"excludeByName": {"Time": True, "__name__": True, "job": True,
                                                                                "instance": True, "environment": True},
                                                              "renameByName": {"metric": "Metric", "Value": "Value"}}}],
              description="reports/pipeline/pipeline_run_*.json (newest)."),
    ]
    y += 6

    # ------------------------------------------------------------------ Fairness
    panels.append(row("Fairness — offline audit ($model, $split split)", y)); y += 1
    panels += [
        bargauge("Demographic parity difference",
                 [target('max by (attribute) (student_dropout_offline_fairness_disparity{model="$model", split="$split", metric="demographic_parity_difference"})', "{{attribute}}", instant=True)],
                 0, y, 8, 7, decimals=3, th=FAIRNESS_TH, display="gradient", maximum=0.25, text_size=(12, 16),
                 description="Max gap in selection rate between groups. Green < 0.05, amber < 0.10."),
        bargauge("Equalized odds difference",
                 [target('max by (attribute) (student_dropout_offline_fairness_disparity{model="$model", split="$split", metric="equalized_odds_difference"})', "{{attribute}}", instant=True)],
                 8, y, 8, 7, decimals=3, th=FAIRNESS_TH, display="gradient", maximum=0.25, text_size=(12, 16),
                 description="Max gap in TPR or FPR between groups. Green < 0.05, amber < 0.10."),
        bargauge("Deployed mitigation: XGBoost + ThresholdOptimizer (gender, test)",
                 [target('max(student_dropout_offline_fairness_disparity{model="xgb", split="test", attribute="gender", metric="equalized_odds_difference"})', "EOD · baseline", "A", instant=True),
                  target('max(student_dropout_offline_mitigation_metric{split="test", attribute="gender", metric="equalized_odds_difference"})', "EOD · mitigated", "B", instant=True),
                  target('max(student_dropout_offline_fairness_disparity{model="xgb", split="test", attribute="gender", metric="demographic_parity_difference"})', "DPD · baseline", "C", instant=True),
                  target('max(student_dropout_offline_mitigation_metric{split="test", attribute="gender", metric="demographic_parity_difference"})', "DPD · mitigated", "D", instant=True),
                  target('max(student_dropout_offline_model_metric{model="xgb", split="test", metric="recall"})', "Recall · baseline", "E", instant=True),
                  target('max(student_dropout_offline_mitigation_metric{split="test", attribute="gender", metric="recall"})', "Recall · mitigated", "F", instant=True)],
                 16, y, 8, 7, decimals=3, display="basic", color_mode="fixed", text_size=(12, 16),
                 overrides=[by_name(n, SERIES[0] if "baseline" in n else SERIES[2]) for n in
                            ("EOD · baseline", "EOD · mitigated", "DPD · baseline", "DPD · mitigated", "Recall · baseline", "Recall · mitigated")],
                 description="Lower EOD / DPD is fairer; higher recall catches more withdrawals."),
    ]
    y += 7
    panels += [
        table("Group outcomes — $attribute",
              [target('student_dropout_offline_group_metric{model="$model", split="$split", attribute="$attribute"}', instant=True, fmt="table")],
              0, y, 16, 12, unit="percentunit", decimals=1,
              transformations=[matrix("group", "metric"),
                               {"id": "organize", "options": {"renameByName": {
                                   "group\\metric": "Group", "selection_rate": "Selection rate",
                                   "true_positive_rate": "True positive rate", "false_positive_rate": "False positive rate",
                                   "precision": "Precision", "recall": "Recall"},
                                   "excludeByName": {"recall": True}}}],
              overrides=[{"matcher": {"id": "byName", "options": n},
                          "properties": [{"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "basic", "valueDisplayMode": "text"}},
                                         {"id": "max", "value": m}, {"id": "color", "value": {"mode": "fixed", "fixedColor": c}}]}
                         for n, m, c in (("selection_rate", 0.25, SERIES[0]), ("true_positive_rate", 0.5, SERIES[2]),
                                         ("false_positive_rate", 0.1, SERIES[1]))],
              sort_by=[{"displayName": "True positive rate", "desc": True}],
              description="Selection rate = share flagged; TPR = withdrawals caught; FPR = false alarms. Groups under 50 students are noisy."),
        bargauge("True positive rate by group — $attribute",
                 [target('max by (group) (student_dropout_offline_group_metric{model="$model", split="$split", attribute="$attribute", metric="true_positive_rate"})', "{{group}}", instant=True)],
                 16, y, 8, 12, unit="percentunit", decimals=1, maximum=0.5, th=thresholds(("#199e70", None)),
                 text_size=(12, 14),
                 description="Equal opportunity view: a fair model catches withdrawals at similar rates in every group."),
    ]
    y += 12

    # ------------------------------------------------------------------ Runtime & alerts
    panels.append(row("Runtime, components & alerts", y)); y += 1
    comp_map = [{"type": "value", "options": {"0": {"text": "Down", "color": CRIT}, "1": {"text": "Up", "color": GOOD}}}]
    panels += [
        state_timeline("Serving components",
                       [target(f"max by (component) (student_dropout_component_up{{{SEL}}})", "{{component}}")],
                       0, y, 12, 7, comp_map, thresholds((CRIT, None), (GOOD, 1)),
                       description="Risk model, intervention engine, fairness post-processor and SHAP explainer health."),
        table("Served model",
              [target(f"student_dropout_model_info{{{SEL}}}", instant=True, fmt="table")],
              12, y, 12, 7,
              transformations=[{"id": "organize", "options": {
                  "excludeByName": {"Time": True, "Value": True, "__name__": True, "job": True, "environment": True,
                                    "instance": True},
                  "indexByName": {"version": 0, "estimator": 1, "explainer_backend": 2, "fairness_mitigator": 3,
                                  "reference_profile": 4},
                  "renameByName": {"version": "Model version", "estimator": "Estimator",
                                   "explainer_backend": "Explainer", "fairness_mitigator": "Fairness mitigator",
                                   "reference_profile": "Drift reference", "instance": "Instance"}}}],
              description="Artifact metadata published by the API at start-up."),
    ]
    y += 7
    panels += [
        timeseries("CPU usage", [target(f"rate(process_cpu_seconds_total{{{SEL}}}[$__rate_interval])", "{{instance}}")],
                   0, y, 6, 7, unit="percentunit", overrides=[], legend_calcs=("mean", "max")),
        timeseries("Resident memory", [target(f"process_resident_memory_bytes{{{SEL}}}", "{{instance}}")],
                   6, y, 6, 7, unit="bytes", legend_calcs=("lastNotNull", "max")),
        timeseries("Requests in flight", [target(f"sum(student_dropout_http_requests_in_progress{{{SEL}}})", "in flight")],
                   12, y, 6, 7, unit="short", legend_calcs=("max",), decimals=0),
        timeseries("Python GC collections", [target(f"sum by (generation) (rate(python_gc_collections_total{{{SEL}}}[$__rate_interval]))", "gen {{generation}}")],
                   18, y, 6, 7, unit="short", legend_calcs=("mean",)),
    ]
    y += 7
    panels += [
        table("Firing alerts",
              [target('ALERTS{alertstate="firing"}', instant=True, fmt="table")],
              0, y, 24, 6,
              transformations=[{"id": "organize", "options": {
                  "excludeByName": {"Time": True, "Value": True, "__name__": True},
                  "renameByName": {"alertname": "Alert", "alertstate": "State", "severity": "Severity"}}}],
              description="Prometheus alert rules in firing state (monitoring/prometheus/alerts.yml)."),
    ]
    panels[-1]["fieldConfig"]["defaults"]["noValue"] = "No alerts firing"

    return {
        "annotations": {"list": [
            {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True, "hide": True,
             "iconColor": "rgba(0, 211, 255, 1)", "name": "Annotations & Alerts", "type": "dashboard"},
            {"datasource": DS, "enable": True, "iconColor": SERIES[6], "name": "API restarts",
             "expr": f"changes(student_dropout_app_start_time_seconds{{{SEL}}}[2m]) > 0",
             "step": "60s", "titleFormat": "API restarted", "textFormat": "New process on {{instance}}"},
            {"datasource": DS, "enable": True, "iconColor": CRIT, "name": "Firing alerts",
             "expr": 'ALERTS{alertstate="firing"}', "step": "60s", "titleFormat": "{{alertname}}",
             "textFormat": "{{severity}} alert firing", "useValueForTime": False},
        ]},
        "description": "Student dropout early-warning service: live operations, prediction analytics, drift, offline model quality and fairness.",
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "links": [
            {"title": "Web UI", "type": "link", "url": "http://localhost:8080", "targetBlank": True, "icon": "external link"},
            {"title": "API docs", "type": "link", "url": "http://localhost:8000/docs", "targetBlank": True, "icon": "doc"},
            {"title": "Prometheus alerts", "type": "link", "url": "http://localhost:9090/alerts", "targetBlank": True, "icon": "bolt"},
        ],
        "liveNow": False,
        "panels": panels,
        "refresh": "10s",
        "schemaVersion": 39,
        "tags": ["mlops", "student-dropout", "drift", "fairness", "explainability"],
        "templating": {"list": [
            {"name": "datasource", "label": "Data source", "type": "datasource", "query": "prometheus",
             "current": {"selected": True, "text": "Prometheus", "value": "prometheus"}, "hide": 0,
             "refresh": 1, "regex": "", "options": [], "includeAll": False, "multi": False},
            {"name": "job", "label": "Job", "type": "query", "datasource": DS,
             "query": {"query": "label_values(student_dropout_app_start_time_seconds, job)", "refId": "job"},
             "definition": "label_values(student_dropout_app_start_time_seconds, job)",
             "refresh": 2, "includeAll": True, "multi": False, "allValue": ".*", "sort": 1,
             "current": {"selected": True, "text": "All", "value": "$__all"}, "options": [], "hide": 0},
            {"name": "instance", "label": "Instance", "type": "query", "datasource": DS,
             "query": {"query": "label_values(student_dropout_app_start_time_seconds{job=~\"$job\"}, instance)", "refId": "instance"},
             "definition": "label_values(student_dropout_app_start_time_seconds{job=~\"$job\"}, instance)",
             "refresh": 2, "includeAll": True, "multi": False, "allValue": ".*", "sort": 1,
             "current": {"selected": True, "text": "All", "value": "$__all"}, "options": [], "hide": 0},
            {"name": "model", "label": "Offline model", "type": "custom", "query": "xgb,rf,lr",
             "current": {"selected": True, "text": "xgb", "value": "xgb"}, "hide": 0, "includeAll": False, "multi": False,
             "options": [{"selected": v == "xgb", "text": v, "value": v} for v in ("xgb", "rf", "lr")]},
            {"name": "split", "label": "Split", "type": "custom", "query": "test,validation",
             "current": {"selected": True, "text": "test", "value": "test"}, "hide": 0, "includeAll": False, "multi": False,
             "options": [{"selected": v == "test", "text": v, "value": v} for v in ("test", "validation")]},
            {"name": "attribute", "label": "Sensitive attribute", "type": "custom",
             "query": "region,imd_band,age_band,gender,disability",
             "current": {"selected": True, "text": "region", "value": "region"}, "hide": 0, "includeAll": False, "multi": False,
             "options": [{"selected": v == "region", "text": v, "value": v} for v in ("region", "imd_band", "age_band", "gender", "disability")]},
        ]},
        "time": {"from": "now-30m", "to": "now"},
        "timepicker": {"refresh_intervals": ["5s", "10s", "30s", "1m", "5m"]},
        "timezone": "browser",
        "title": "Student Dropout EWS · MLOps Command Center",
        "uid": "mlops-monitoring",
        "version": 1,
        "weekStart": "",
    }


def main():
    dashboard = build()
    with open(OUTPUT, "w") as f:
        json.dump(dashboard, f, indent=2)
        f.write("\n")
    print(f"Wrote {len(dashboard['panels'])} panels to {OUTPUT}")


if __name__ == "__main__":
    main()
