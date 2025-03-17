import { TEMP_FOLDER, DTK25_FOLDER, DTK50_FOLDER } from "$env/static/private";
import fs from "node:fs";
import { TopoFormData, get_request_id } from "./validation_util";
import type { PathLike } from "node:fs";
import type { RasterType } from "./dto"

export type RequestType = 'map_preview' | 'create_map';

class MapBaseRequest {
  id: string = '';

  request_type: RequestType;
  map_w: number;
  map_s: number;
  map_e: number;
  map_n: number;
  epsg: string;
  raster_type: RasterType;
  raster_source: PathLike;
  map_size_w_m: number;
  map_size_h_m: number;

  output_folder: PathLike;


  constructor(request_type: RequestType, fd: TopoFormData) {
    this.request_type = request_type;
    this.map_w = fd.get_number('map_w');
    this.map_s = fd.get_number('map_s');
    this.map_e = fd.get_number('map_e');
    this.map_n = fd.get_number('map_n');
    if (this.map_w >= this.map_e) throw new Error('map_w >= map_e');
    if (this.map_s >= this.map_n) throw new Error('map_s >= map_n');
    this.epsg = fd.get('epsg');
    if (!/^EPSG:\d+$|^Brez$/.test(this.epsg)) throw new Error('Koordinatni sistem je napačen (EPSG:xxxx ali Brez)');
    this.raster_type = fd.get('raster_type') as RasterType;
    this.raster_source = (() => {
      switch (this.raster_type) {
        case 'dtk50': return DTK50_FOLDER;
        case 'dtk25': return DTK25_FOLDER;
        case 'osm': return 'https://a.tile.openstreetmap.org/{z}/{x}/{y}.png';
        case 'otm': return 'https://tile.opentopomap.org/{z}/{x}/{y}.png';
        case '': return '';
        default: throw new Error('Napačen raster sloj');
      }
    })()
    this.map_size_w_m = fd.get_number('map_size_w_m');
    this.map_size_h_m = fd.get_number('map_size_h_m');
    if (this.map_size_w_m > 1) throw new Error('Velikost karte je prevelika (širina) (max 1m)');
    if (this.map_size_h_m > 1) throw new Error('Velikost karte je prevelika (višina) (max 1m)');
    if (this.map_size_w_m < 0.1) throw new Error('Velikost karte je premajhna (širina) (min 0.1m)');
    if (this.map_size_h_m < 0.1) throw new Error('Velikost karte je premajhna (višina) (min 0.1m)');
    this.output_folder = TEMP_FOLDER;
    if (!fs.existsSync(this.output_folder)) fs.mkdirSync(this.output_folder, { recursive: true });
  }
}

export class MapPreviewRequest extends MapBaseRequest {
  private constructor(tfd: TopoFormData) {
    super('map_preview', tfd);
  }

  public static async validate(fd: FormData) {
    const validated = new MapPreviewRequest(new TopoFormData(fd));
    validated.id = get_request_id(validated);
    return validated;
  }
}

export class MapCreateRequest extends MapBaseRequest {
  target_scale: number;
  edge_wgs84: boolean;
  naslov1: string;
  naslov2: string;
  dodatno: string;
  slikal: PathLike;
  slikad: PathLike;
  control_points: string;

  private constructor(tfd: TopoFormData) {
    super('create_map', tfd);
    this.target_scale = tfd.get_number('target_scale');
    if (this.target_scale < 1000) throw new Error('Merilo je napačno ali preveliko (max 1:1000)');
    else if (this.target_scale > 100000) throw new Error('Merilo je napačno ali preveliko (max 1:100000)');
    this.naslov1 = tfd.get('naslov1');
    if (this.naslov1.length > 30) throw new Error('Naslov (1) je predolg (max 30 znakov)');
    this.naslov2 = tfd.get('naslov2');
    if (this.naslov2.length > 30) throw new Error('Naslov (2) je predolg (max 30 znakov)');
    this.dodatno = tfd.get('dodatno');
    if (this.dodatno.length > 70) throw new Error('Dodatna vrstica je predolgo (max 70 znakov)');
    this.edge_wgs84 = tfd.get('edge_wgs84') === 'true';
    this.slikal = ''
    this.slikad = ''
    this.control_points = tfd.get('control_points');
    if (this.control_points.length !== 0) {
      try {
        const cps = JSON.parse(this.control_points);
        if (!Array.isArray(cps.cps)) throw new Error('Kontrolne točke niso v pravilni obliki (JSON)');
      } catch (error) {
        throw new Error('Kontrolne točke niso v pravilni obliki (JSON)');
      }
    }
  }

  public static async validate(fd: FormData, skip_write_files = false) {
    let tfd = new TopoFormData(fd)
    const validated = new MapCreateRequest(tfd);
    try {
      validated.slikal = await tfd.get_file('slikal', skip_write_files);
      validated.slikad = await tfd.get_file('slikad', skip_write_files);
    } catch (error) {
      if (validated.slikal) await fs.promises.unlink(validated.slikal);
      if (validated.slikad) await fs.promises.unlink(validated.slikad);
      throw error;
    }
    validated.id = get_request_id(validated);
    return validated;
  }
}
