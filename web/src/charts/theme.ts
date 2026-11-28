export const COLOR = {
  gold: "#d4b06a",
  mint: "#8fbf7a",
  bad: "#c45c4a",
  muted: "#8b947c",
  line: "#2c3826",
  panel: "#1c2419",
  text: "#e7eadf",
};

export function tip(extra: Record<string, unknown> = {}) {
  return {
    backgroundColor: COLOR.panel,
    borderColor: COLOR.line,
    textStyle: { color: COLOR.text },
    ...extra,
  };
}

export function categoryAxis(data: Array<string | number>) {
  return {
    type: "category" as const,
    data,
    axisLine: { lineStyle: { color: COLOR.line } },
    axisTick: { show: false },
    axisLabel: { color: COLOR.muted },
  };
}

export function valueAxis(name?: string) {
  return {
    type: "value" as const,
    name,
    nameTextStyle: { color: COLOR.muted },
    axisLabel: { color: COLOR.muted },
    splitLine: { lineStyle: { color: COLOR.line } },
  };
}
