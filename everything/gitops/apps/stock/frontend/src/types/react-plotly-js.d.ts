declare module "react-plotly.js" {
  import type { ComponentType } from "react";

  type PlotProps = {
    data: unknown[];
    layout?: unknown;
    config?: unknown;
    style?: unknown;
    onClick?: (event: unknown) => void;
    onDoubleClick?: (event: unknown) => void;
  };

  const Plot: ComponentType<PlotProps>;
  export default Plot;
}


