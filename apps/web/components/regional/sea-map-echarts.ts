/**
 * The ECharts pieces the Southeast Asia map needs, and nothing else (D-023 #6). Only
 * `sea-map.tsx` imports this, and only with a dynamic `import()` inside an effect, so ECharts
 * is its own chunk that loads on /regional and nowhere else.
 */
import { ScatterChart } from "echarts/charts";
import { GeoComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { LabelLayout } from "echarts/features";
import { SVGRenderer } from "echarts/renderers";

// GeoComponent must be registered before registerMap (ECharts 5.3+). LabelLayout moves
// Singapore's label off Malaysia and draws its leader line.
echarts.use([GeoComponent, ScatterChart, TooltipComponent, LabelLayout, SVGRenderer]);

export const { init, registerMap } = echarts;
