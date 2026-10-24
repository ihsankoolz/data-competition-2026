"use client";

import { useEffect, useRef, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { signedPct, usdShort } from "@/lib/analytics";
import type { Schema } from "@/lib/api/client";
import { countryName } from "@/lib/format";
import { usePrefersReducedMotion } from "@/lib/use-reduced-motion";

type CountryGrowth = Schema<"CountryGrowth">;
type Country = CountryGrowth["country"];
type Echarts = typeof import("./sea-map-echarts");
type Chart = ReturnType<Echarts["init"]>;
type GeoJson = Parameters<Echarts["registerMap"]>[1];

const MAP = "sea-5";
const GEOJSON_URL = "/geo/sea-5.geojson";

/*
 * Diverging scale on 12-month growth (D-023 #5): a neutral grey for "about flat", the heatmap's
 * sage-green ramp (hue 133, every other step of its RAMP) for growth, and a matching ochre ramp
 * at the same lightness steps for shrinking. Hex, not oklch: ECharts parses colours itself.
 * Each step is 10 percentage points; the label on every country carries the exact figure, so
 * colour is never the only cue.
 */
const GROW = ["#d6e8ca", "#b5d2a0", "#93b879", "#719656", "#50713a", "#344d26"];
const SHRINK = ["#f1dec5", "#e4c195", "#d3a067", "#ba7d44", "#9b5e30", "#794220"];
const FLAT = "#d6d9d3";
const FLAT_BAND = 2; // |growth| under 2% reads as flat
const STEP_PCT = 10;
const OUTLINE = "#a8ada3";
const INK = "#10130e"; // --foreground (theme B)
const PAGE = "#f4f7f1"; // --background (theme B), the label halo

/** Where each country's label sits (lon, lat), chosen by hand so none collide. */
const LABEL_AT: Record<Country, [number, number]> = {
  TH: [101.0, 15.6],
  VN: [109.4, 13.2],
  MY: [116.9, 5.3],
  ID: [113.4, -1.0],
  SG: [103.82, 1.35], // the dot itself: Singapore is too small to click as a shape
};
const LABEL_POSITION: Record<Country, "inside" | "right"> = {
  TH: "inside",
  VN: "right",
  MY: "inside",
  ID: "inside",
  SG: "right",
};
const ORDER: Country[] = ["SG", "MY", "ID", "VN", "TH"];

export function growthColor(g: number | null | undefined): string {
  if (g === null || g === undefined || Math.abs(g) < FLAT_BAND) return FLAT;
  const i = Math.min(GROW.length - 1, Math.floor(Math.abs(g) / STEP_PCT));
  return g > 0 ? GROW[i] : SHRINK[i];
}

function describe(g: CountryGrowth): string {
  return `${countryName(g.country)} ${signedPct(g.growth_12m_pct)}`;
}

function tooltipHtml(g: CountryGrowth, selected: boolean): string {
  const change =
    g.growth_12m_pct === null
      ? "No sales in the 12 months before, so there is no growth figure."
      : `${signedPct(g.growth_12m_pct)} against ${usdShort(g.prior_value_usd)} in the 12 months before.`;
  const action = selected
    ? "Click again to show all five countries."
    : `Click to show only ${countryName(g.country)}.`;
  return (
    `<strong style="font-weight:600">${countryName(g.country)}</strong><br/>` +
    `${usdShort(g.value_usd)} of confirmed POs in the last 12 months,<br/>${change}<br/>` +
    `<span style="opacity:.75">${action}</span>`
  );
}

type Status = "loading" | "ready" | "error";

export function SeaMap({
  growth,
  country,
  onSelect,
}: {
  /** All five countries; the same whatever the filter (`RegionalView.country_growth`). */
  growth: CountryGrowth[] | null;
  country: Country | null;
  /** Clicking the selected country again clears the filter (null = all five). */
  onSelect: (c: Country | null) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<Chart | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const reduced = usePrefersReducedMotion();
  // The click handler is bound once; it reads the latest selection and callback from here.
  const latest = useRef({ country, onSelect });
  useEffect(() => {
    latest.current = { country, onSelect };
  }, [country, onSelect]);

  // Load ECharts (its own chunk, only on this page) and the shapes once.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    let disposed = false;
    let observer: ResizeObserver | null = null;
    Promise.all([
      import("./sea-map-echarts"),
      fetch(GEOJSON_URL).then((r) => {
        if (!r.ok) throw new Error(`map shapes: HTTP ${r.status}`);
        return r.json() as Promise<GeoJson>;
      }),
    ]).then(
      ([echarts, shapes]) => {
        if (disposed) return;
        echarts.registerMap(MAP, shapes);
        const c = echarts.init(el, null, { renderer: "svg" });
        chart.current = c;
        c.on("click", (p) => {
          const code = (
            p.componentType === "geo" ? p.name : (p.data as { code?: string } | undefined)?.code
          ) as Country | undefined;
          if (!code || !ORDER.includes(code)) return;
          const { country: now, onSelect: select } = latest.current;
          select(code === now ? null : code);
        });
        // "Drawn and settled", for tests and the rehearsal screenshots, set straight on the
        // element (no re-render). ECharts fires `finished` once a draw and its animation end;
        // the draw effect below marks a draw as pending.
        c.on("finished", () => {
          if (el.dataset.drawn === "false") el.dataset.drawn = "true";
        });
        observer = new ResizeObserver(() => c.resize());
        observer.observe(el);
        setStatus("ready");
      },
      () => {
        // A plain message replaces the map; the country buttons still filter the page.
        if (!disposed) setStatus("error");
      },
    );
    return () => {
      disposed = true;
      observer?.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  // Draw (and redraw on a filter change) from the data.
  useEffect(() => {
    const c = chart.current;
    if (status !== "ready" || !c || !growth) return;
    const byCode = new Map(growth.map((g) => [g.country, g]));
    const font = getComputedStyle(box.current ?? document.body).fontFamily;
    const regions = ORDER.map((code) => {
      const g = byCode.get(code);
      const fill = growthColor(g?.growth_12m_pct);
      const on = country === code;
      const dim = country !== null && !on;
      return {
        name: code,
        itemStyle: {
          areaColor: fill,
          borderColor: on ? INK : OUTLINE,
          borderWidth: on ? 2 : 0.6,
          opacity: dim ? 0.4 : 1,
        },
        emphasis: {
          itemStyle: { areaColor: fill, borderColor: INK, borderWidth: on ? 2 : 1.2 },
          label: { show: false },
        },
      };
    });
    const labels = ORDER.flatMap((code) => {
      const g = byCode.get(code);
      if (!g) return [];
      const sg = code === "SG";
      const on = country === code;
      const dim = country !== null && !on;
      return [
        {
          name: countryName(code),
          code,
          value: LABEL_AT[code],
          symbolSize: sg ? 12 : 0,
          itemStyle: sg
            ? {
                color: growthColor(g.growth_12m_pct),
                borderColor: on ? INK : "#ffffff",
                borderWidth: on ? 2.5 : 1.5,
                opacity: dim ? 0.4 : 1,
              }
            : undefined,
          label: {
            position: LABEL_POSITION[code],
            distance: 6,
            opacity: dim ? 0.55 : 1,
            formatter: `{n|${countryName(code)}}\n{g|${signedPct(g.growth_12m_pct)}}`,
            rich: {
              n: { fontWeight: on ? 700 : 600, fontSize: 12, lineHeight: 15 },
              g: { fontSize: 12, lineHeight: 15 },
            },
          },
        },
      ];
    });
    const tip = (code: Country) => {
      const g = byCode.get(code);
      return g ? tooltipHtml(g, country === code) : "";
    };
    if (box.current) box.current.dataset.drawn = "false";
    c.setOption(
      {
        animation: !reduced,
        textStyle: { fontFamily: font, color: INK },
        tooltip: {
          trigger: "item",
          confine: true,
          transitionDuration: reduced ? 0 : 0.15,
          backgroundColor: INK,
          borderWidth: 0,
          padding: [6, 10],
          textStyle: { color: PAGE, fontSize: 12, lineHeight: 17, fontFamily: font },
          extraCssText: "border-radius:6px;box-shadow:none;",
          formatter: (p: unknown) => {
            const q = p as { componentType?: string; name?: string; data?: { code?: Country } };
            const code = (q.componentType === "geo" ? q.name : q.data?.code) as Country;
            return tip(code);
          },
        },
        geo: {
          map: MAP,
          nameProperty: "iso_a2",
          roam: false,
          aspectScale: 1, // near the equator a degree of longitude is about a degree of latitude
          top: 6,
          bottom: 6,
          left: 4,
          right: 4,
          selectedMode: false,
          silent: false,
          tooltip: { show: true },
          label: { show: false },
          itemStyle: { areaColor: FLAT, borderColor: OUTLINE, borderWidth: 0.6 },
          emphasis: { label: { show: false } },
          regions,
        },
        series: [
          {
            type: "scatter",
            coordinateSystem: "geo",
            symbol: "circle",
            cursor: "pointer",
            z: 3,
            label: {
              show: true,
              color: INK,
              textBorderColor: PAGE,
              textBorderWidth: 3,
            },
            emphasis: { scale: false, label: { show: true } },
            data: labels,
          },
        ],
      },
      { notMerge: true },
    );
  }, [status, growth, country, reduced]);

  const summary = growth
    ? "Map of sales growth, last 12 months vs the 12 before: " +
      ORDER.map((code) => growth.find((g) => g.country === code))
        .filter((g): g is CountryGrowth => g !== undefined)
        .map(describe)
        .join(", ") +
      "." +
      (country ? ` Showing ${countryName(country)} only.` : "")
    : "Map of sales growth by country, loading.";

  return (
    <div className="flex flex-col gap-3" data-testid="sea-map-panel">
      <div className="relative h-[360px] w-full">
        <div
          ref={box}
          role="img"
          aria-label={summary}
          data-testid="sea-map"
          data-status={status}
          data-selected={country ?? "ALL"}
          className="absolute inset-0"
        />
        {(status === "loading" || !growth) && status !== "error" && (
          <Skeleton className="absolute inset-0" aria-busy data-testid="sea-map-loading" />
        )}
        {status === "error" && (
          <p
            className="absolute inset-0 flex items-center justify-center rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground"
            data-testid="sea-map-error"
          >
            The map could not be loaded. Use the country buttons above to filter.
          </p>
        )}
      </div>
      <div className="flex flex-col gap-1.5 text-xs text-muted-foreground">
        <div className="flex items-center gap-3 whitespace-nowrap" aria-hidden>
          <span>Shrinking</span>
          <span className="flex h-2 w-40 overflow-hidden rounded-full">
            {[...SHRINK].reverse().map((c) => (
              <span key={c} className="flex-1" style={{ backgroundColor: c }} />
            ))}
            <span className="flex-1" style={{ backgroundColor: FLAT }} />
            {GROW.map((c) => (
              <span key={c} className="flex-1" style={{ backgroundColor: c }} />
            ))}
          </span>
          <span>Growing</span>
          <span className="ml-auto">Each shade is 10 percentage points</span>
        </div>
        <p data-testid="sea-map-hint">
          Click a country to show only that country; click it again for all five.
        </p>
      </div>
    </div>
  );
}
