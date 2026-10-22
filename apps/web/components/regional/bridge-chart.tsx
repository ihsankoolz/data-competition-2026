"use client";

import { Bar, BarChart, Cell, LabelList, Tooltip, XAxis, YAxis } from "recharts";

import { usdFull, usdShort } from "@/lib/analytics";
import type { Schema } from "@/lib/api/client";

type BridgeStep = Schema<"BridgeStep">;

// Two short lines each, so six labels never run into each other at 1440 px.
const LABELS: Record<BridgeStep["step"], string> = {
  start: "Prior|3 months",
  new: "New|customers",
  expansion: "Bought|more",
  contraction: "Bought|less",
  lost: "Stopped|buying",
  end: "Last|3 months",
};

function TwoLineTick({ x, y, payload }: { x?: number; y?: number; payload?: { value: string } }) {
  const [first, second] = String(payload?.value ?? "").split("|");
  return (
    <text x={x} y={y} textAnchor="middle" fontSize={11} fill="var(--viz-axis)">
      <tspan x={x} dy={12}>
        {first}
      </tspan>
      {second && (
        <tspan x={x} dy={13}>
          {second}
        </tspan>
      )}
    </text>
  );
}

type Row = {
  label: string;
  base: number;
  value: number;
  signed: number;
  customers: number;
  kind: "total" | "gain" | "loss";
};

function rows(bridge: BridgeStep[]): Row[] {
  const out: Row[] = [];
  let running = 0;
  for (const s of bridge) {
    if (s.step === "start" || s.step === "end") {
      out.push({
        label: LABELS[s.step],
        base: 0,
        value: s.value_usd,
        signed: s.value_usd,
        customers: s.customers,
        kind: "total",
      });
      running = s.value_usd;
    } else {
      const next = running + s.value_usd;
      out.push({
        label: LABELS[s.step],
        base: Math.min(running, next),
        value: Math.abs(s.value_usd),
        signed: s.value_usd,
        customers: s.customers,
        kind: s.value_usd >= 0 ? "gain" : "loss",
      });
      running = next;
    }
  }
  return out;
}

const FILL = {
  total: "var(--viz-neutral)",
  gain: "var(--viz-accent)",
  loss: "var(--viz-loss)",
} as const;

function BridgeTooltip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  const row = payload?.[0]?.payload;
  if (!active || !row) return null;
  const who = `${row.customers} ${row.customers === 1 ? "customer" : "customers"}`;
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-sm">
      <p className="font-medium">{row.label.replace("|", " ")}</p>
      <p className="tabular-nums">
        {row.kind === "total"
          ? usdFull(row.value)
          : `${row.signed >= 0 ? "+" : ""}${usdFull(row.signed)}`}
      </p>
      <p className="text-muted-foreground">{who}</p>
    </div>
  );
}

export function BridgeChart({ bridge }: { bridge: BridgeStep[] }) {
  const data = rows(bridge);
  return (
    <div data-testid="bridge-chart">
      <BarChart
        data={data}
        responsive
        style={{ width: "100%", height: 244 }}
        margin={{ top: 22, right: 4, bottom: 0, left: 4 }}
        barCategoryGap={10}
        accessibilityLayer
      >
        <XAxis
          dataKey="label"
          tickLine={false}
          axisLine={{ stroke: "var(--viz-grid)" }}
          tick={<TwoLineTick />}
          height={34}
          interval={0}
        />
        <YAxis hide domain={[0, "dataMax"]} />
        <Tooltip content={<BridgeTooltip />} cursor={{ fill: "var(--muted)", opacity: 0.5 }} />
        <Bar dataKey="base" stackId="w" fill="transparent" isAnimationActive={false} />
        <Bar dataKey="value" stackId="w" radius={[4, 4, 4, 4]} isAnimationActive={false}>
          {data.map((r) => (
            <Cell key={r.label} fill={FILL[r.kind]} />
          ))}
          <LabelList
            dataKey="signed"
            position="top"
            fontSize={11}
            fill="var(--foreground)"
            formatter={(v: unknown) => usdShort(Number(v))}
          />
        </Bar>
      </BarChart>
      <table className="sr-only">
        <caption>Revenue bridge</caption>
        <tbody>
          {data.map((r) => (
            <tr key={r.label}>
              <th scope="row">{r.label.replace("|", " ")}</th>
              <td>{usdFull(r.signed)}</td>
              <td>{r.customers} customers</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
