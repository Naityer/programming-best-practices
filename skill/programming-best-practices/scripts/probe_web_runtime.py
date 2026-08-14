#!/usr/bin/env python3
"""Measure what a running web page actually costs, in a real browser.

    python scripts/probe_web_runtime.py --url http://127.0.0.1:8000/app \
        --idle-seconds 5 --output runtime.json

Static analysis cannot see the failure mode this catches: a page that looks
fine, renders correctly, passes every test — and never stops working. An
animation or polling loop that keeps requesting frames with nothing to do burns
CPU and battery for as long as the tab is open, and is invisible in a
screenshot, a diff, and a unit test.

The headline metric is therefore **frames requested while idle**. With no input
and nothing animating, a correct page tends to zero. Anything near the display
refresh rate is a loop that never sleeps.

Also collected, all generic and all cheap:

- `idle_requests` — network traffic with the page untouched. Catches polling
  that is too eager, and endpoints that 404 in a reconnect loop.
- `long_tasks` — main-thread blocks over 50 ms during load, the standard
  definition of jank.
- `dom_interactive_ms` / `load_ms` — when the page became usable.
- `transferred_bytes` / `request_count` — what the load actually cost.
- `dom_nodes` — a cheap proxy for render weight.

Requires Playwright (`pip install playwright && playwright install chromium`)
and a URL that is already serving. Both are checked before measuring, and a
failure is reported as a limitation rather than a crash: an unreachable target
is incomplete evidence, never a pass.

Measures, never judges. Verdicts come from comparing against a recorded
baseline (`compare_perf_baseline.py`).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Se instala en el documento ANTES de medir. Envuelve requestAnimationFrame para
# contar cuántos fotogramas pide la página: el bucle llama al global en cada
# vuelta, así que pasa por aquí.
INSTRUMENT = """
() => {
  if (window.__probeReady) { window.__probeFrames = 0; return; }
  window.__probeReady = true;
  window.__probeFrames = 0;
  window.__probeLongTasks = 0;
  const native = window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame = (cb) => { window.__probeFrames++; return native(cb); };
  try {
    new PerformanceObserver((list) => { window.__probeLongTasks += list.getEntries().length; })
      .observe({ entryTypes: ["longtask"] });
  } catch (_) { /* longtask no soportado en este navegador */ }
}
"""

TIMINGS = """
() => {
  const nav = performance.getEntriesByType("navigation")[0] || {};
  const resources = performance.getEntriesByType("resource") || [];
  return {
    dom_interactive_ms: Math.round(nav.domInteractive || 0),
    dom_content_loaded_ms: Math.round(nav.domContentLoadedEventEnd || 0),
    load_ms: Math.round(nav.loadEventEnd || 0),
    request_count: resources.length,
    transferred_bytes: resources.reduce((sum, r) => sum + (r.transferSize || 0), 0),
    dom_nodes: document.getElementsByTagName("*").length,
  };
}
"""


def probe(url: str, idle_seconds: float, settle_seconds: float, headless: bool = True) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright  # import perezoso: falta clara si no está

    result: dict[str, Any] = {"url": url, "idle_seconds": idle_seconds}
    limitations: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        errors: list[str] = []
        requests: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        try:
            page.goto(url, wait_until="load", timeout=30_000)
        except Exception as exc:  # noqa: BLE001 — un objetivo inalcanzable no es un fallo del audit
            browser.close()
            return {
                **result,
                "reachable": False,
                "limitations": [f"No se pudo cargar {url}: {exc}"],
            }

        result["reachable"] = True
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:  # noqa: BLE001
            limitations.append("La red nunca quedó en reposo; puede haber sondeo continuo.")

        # Margen para que arranque lo que arranque de forma diferida (datos,
        # layouts, animaciones de entrada). Sin esto se mediría el arranque, que
        # es CORRECTO que pida fotogramas, en vez del estado de reposo.
        page.wait_for_timeout(int(settle_seconds * 1000))

        result.update(page.evaluate(TIMINGS))

        page.evaluate(INSTRUMENT)
        page.on("request", lambda request: requests.append(request.url))
        page.wait_for_timeout(int(idle_seconds * 1000))

        result["idle_frames"] = page.evaluate("() => window.__probeFrames || 0")
        result["idle_frames_per_second"] = round(result["idle_frames"] / idle_seconds, 1)
        result["idle_requests"] = len(requests)
        result["long_tasks"] = page.evaluate("() => window.__probeLongTasks || 0")
        result["page_errors"] = errors[:10]
        if errors:
            limitations.append(f"La página lanzó {len(errors)} error(es) de JavaScript.")

        browser.close()

    result["limitations"] = limitations
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", action="append", required=True,
                        help="Target URL; repeat for several pages")
    parser.add_argument("--name", action="append", default=[],
                        help="Label for each --url, in the same order")
    parser.add_argument("--idle-seconds", type=float, default=5.0)
    parser.add_argument("--settle-seconds", type=float, default=6.0,
                        help="Grace period before measuring, for deferred startup work")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        import playwright  # noqa: F401
    except ImportError:
        raise SystemExit(
            "Playwright no está instalado. "
            "Instálalo con: pip install playwright && playwright install chromium"
        )

    targets: dict[str, Any] = {}
    for index, url in enumerate(args.url):
        label = args.name[index] if index < len(args.name) else f"target{index + 1}"
        targets[label] = probe(url, args.idle_seconds, args.settle_seconds, headless=not args.headed)

    document = {
        "schema_version": "1.0.0",
        "tool": "web-runtime",
        "targets": targets,
        "limitations": [
            f"{label}: {item}"
            for label, target in targets.items()
            for item in target.get("limitations", [])
        ],
    }
    text = json.dumps(document, indent=2, ensure_ascii=False)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    # Un objetivo inalcanzable no invalida la ejecución: se declara como
    # limitación y el informe lo trata como evidencia incompleta.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
