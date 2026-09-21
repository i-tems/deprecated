"use client";

import dynamic from "next/dynamic";

// react-plotly.js needs the browser (window). This keeps it SSR-safe.
export const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });


