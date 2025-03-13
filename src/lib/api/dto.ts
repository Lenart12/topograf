
export type RasterType = 'dtk50' | 'dtk25' | 'osm' | 'otm' | '';

export type ControlPointOptions = {
  // northing in meters (D96/TM)
  n: number;
  // easting in meters (D96/TM)
  e: number;
  // name of the control point (or undefined for automatic point names "START"->"KT1"->"KT2"->"CILJ")
  name: string | undefined;
  // type
  kind: 'circle' | 'triangle' | 'dot' | 'skip' | 'point';
  // color
  color: string;
  // line color
  color_line: string;
  // connection to the next point
  connect_next: boolean;
}

export type ControlPointsConfig = {
  // size of the control point in meters
  cp_size: number;
  // array of control points
  cps: ControlPointOptions[];
  // control point bounds (for restoring from json file)
  bounds?: [number, number, number, number];
}

export interface CreateMapBaseRequest {
  map_w: number;
  map_s: number;
  map_e: number;
  map_n: number;
  epsg: string;
  raster_type: RasterType;
}

export interface CreateMapPreviewRequest extends CreateMapBaseRequest { }
export interface CreateMapCreateRequest extends CreateMapBaseRequest {
  map_size_w_m: number;
  map_size_h_m: number;
  target_scale: number;
  edge_wgs84: boolean;
  naslov1: string;
  naslov2: string;
  dodatno: string;
  slikal?: File
  slikad?: File
  control_points: string; // ControlPointsConfig as JSON string
}

function FormatMapBaseRequest(c: CreateMapBaseRequest) {
  const fd = new FormData();
  fd.append('map_w', c.map_w.toString());
  fd.append('map_s', c.map_s.toString());
  fd.append('map_e', c.map_e.toString());
  fd.append('map_n', c.map_n.toString());
  fd.append('epsg', c.epsg);
  fd.append('raster_type', c.raster_type);
  return fd;
}

export function FormatMapPreviewRequest(c: CreateMapPreviewRequest) {
  return FormatMapBaseRequest(c);
}

export function FormatMapCreateRequest(c: CreateMapCreateRequest) {
  const fd = FormatMapBaseRequest(c);
  console.log(c)
  fd.append('map_size_w_m', c.map_size_w_m.toString());
  fd.append('map_size_h_m', c.map_size_h_m.toString());
  fd.append('target_scale', c.target_scale.toString());
  fd.append('edge_wgs84', c.edge_wgs84.toString());
  fd.append('naslov1', c.naslov1);
  fd.append('naslov2', c.naslov2);
  fd.append('dodatno', c.dodatno);
  if (c.slikal) fd.append('slikal', c.slikal);
  if (c.slikad) fd.append('slikad', c.slikad);
  fd.append('control_points', c.control_points);
  return fd;
}