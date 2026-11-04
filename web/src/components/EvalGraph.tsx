// v0.8 (FR-11.12): the eval graph for the whole game. One series (White's side, clamped to ±10), a zero
// baseline, the current move marked, a tooltip per move, and a click jumps to that move. The move list
// beside it is the table view. Colors as in RatingTrend (checked with the dataviz validator per scheme).
import { useComputedColorScheme } from "@mantine/core";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ReviewMove } from "../api/types";
import { moveLabel } from "../state/games";

const LINE = { light: "#087f5b", dark: "#0ca678" };
const INK = { light: "#495057", dark: "#ced4da" }; // muted text tokens: baseline, current move, axes

export function EvalGraph({ moves, ply, onPly }: { moves: ReviewMove[]; ply: number; onPly: (ply: number) => void }) {
  const scheme = useComputedColorScheme("light");
  const data = moves.map((m) => ({
    ply: m.ply,
    pawns: m.eval_white === null ? null : m.eval_white / 100,
    label: `${moveLabel(m.ply)} ${m.san}${m.symbol ?? ""}`,
    text: m.eval_text ?? "",
  }));
  return (
    <div style={{ width: "100%", height: 160, cursor: "pointer" }} data-testid="eval-graph" aria-label="Evaluation graph: White's advantage per move">
      <ResponsiveContainer>
        <LineChart
          data={data}
          margin={{ top: 8, right: 8, bottom: 0, left: -16 }}
          onClick={(e) => {
            const i = (e as { activeTooltipIndex?: number | string } | null)?.activeTooltipIndex;
            if (i !== undefined && i !== null) onPly(Number(i));
          }}
        >
          <CartesianGrid vertical={false} strokeOpacity={0.15} />
          <XAxis dataKey="ply" tick={false} axisLine={false} />
          <YAxis domain={[-10, 10]} ticks={[-10, -5, 0, 5, 10]} tick={{ fontSize: 11, fill: INK[scheme] }} axisLine={false} tickLine={false} />
          <ReferenceLine y={0} stroke={INK[scheme]} strokeOpacity={0.6} />
          <ReferenceLine x={ply} stroke={INK[scheme]} strokeDasharray="3 3" />
          <Tooltip
            isAnimationActive={false}
            formatter={(_v, _n, item) => [(item.payload as { text: string }).text, "Eval (White)"]}
            labelFormatter={(_l, items) => (items?.[0]?.payload as { label: string } | undefined)?.label ?? ""}
          />
          <Line
            type="linear"
            dataKey="pawns"
            stroke={LINE[scheme]}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 5 }}
            isAnimationActive={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
