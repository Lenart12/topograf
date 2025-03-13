import type { MapOptions, Marker, Polyline } from 'leaflet';
import type { ControlPointOptions } from './api/dto';

export type CreatedMapConf = {
  map_size_w_m: number;
  map_size_h_m: number;
  map_w: number;
  map_s: number;
  map_e: number;
  map_n: number;
  target_scale: number;
  naslov1: string;
  naslov2: string;
  dodatno: string;
  epsg: string;
  edge_wgs84: boolean;
  raster_folder: string;
  slikal: string | null;
  slikad: string | null;
  map_id: string;
};

export type GetMapOptions = (L: typeof import('leaflet')) => MapOptions;

export type ControlPoint = {
  // id of the control point
  id: number;
  // marker representing the control point
  marker: Marker | null;
  // html element representing the control point
  marker_html: HTMLDivElement | null;
  // line to next point
  line_to_next: Polyline | null;
  // control point options
  options: ControlPointOptions;
};
