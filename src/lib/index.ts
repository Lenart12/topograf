// place files you want to import through the `$lib` alias in this folder.

import type { ControlPoint } from "./types";

export function get_cp_name(cp: ControlPoint, control_points: ControlPoint[]) {
  if (cp.options.name) return cp.options.name;
  if (!control_points) return '???';
  const index = control_points.findIndex((c) => c.id === cp.id);
  if (index === -1) return '???';
  if (index === 0) return 'START';
  if (index === control_points.length - 1 && !cp.options.connect_next) return 'FINISH';
  return `KT${index}`;
}