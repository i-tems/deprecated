export type Company = {
  ticker: string;
  name: string;
  marketCap: number;
  corpCode?: string | null;
  currency: string;
  unit: string;
};

export type QuarterOption = {
  id: string; // e.g. "2023Q4", "2025H1", "20259M"
  label: string; // e.g. "2023 Q4", "2025 H1", "2025 9M"
};

export type SankeyNode = {
  id: string;
  label: string;
  group: string;
  colorKey: string;
};

export type SankeyLink = {
  source: string; // node id
  target: string; // node id
  value: number;
};

export type QuarterKpiItem = {
  value: number;
  qoqPct: number | null;
  yoyPct: number | null;
};

export type QuarterPayload = {
  ticker: string;
  quarter: string;
  label: string;
  currency: string;
  unit: string;
  kpi: {
    revenue: QuarterKpiItem;
    opIncome: QuarterKpiItem;
    netIncome: QuarterKpiItem;
  };
  sankey: {
    nodes: SankeyNode[];
    links: SankeyLink[];
  };
};

export type TimePoint = { quarter: string; value: number };
export type TimeSeriesPayload = {
  ticker: string;
  series: Record<string, TimePoint[]>;
};

export type CompanyQuartersResponse = {
  ticker: string;
  quarters: QuarterOption[];
};

export type DartParsedSofcAvailableItem = {
  id: string; // e.g. "2023Q4", "2025H1", "20259M"
  year: number;
  quarter: string; // period/ytd, e.g. "Q4", "H1", "9M"
  sourcePath: string;
  receiptId?: string | null;
};

export type DartParsedSofcAvailableResponse = {
  ticker: string;
  corpCode: string;
  items: DartParsedSofcAvailableItem[];
};

export type DartParsedSofcResponse = {
  ticker: string;
  corpCode: string;
  year: number;
  quarter: string; // period/ytd, e.g. "Q4", "H1", "9M"
  sourcePath: string;
  receiptId?: string | null;
  data: unknown;
};



