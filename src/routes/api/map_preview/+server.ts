import { platform } from 'os';
import util from 'util';
import { exec } from 'child_process';
import fs from 'node:fs';
import { CREATE_MAP_PY_FOLDER, DTK50_FOLDER, DTK25_FOLDER } from '$env/static/private';
const aexec = util.promisify(exec);
import { RateLimiter } from 'sveltekit-rate-limiter/server';
import crypto_js from 'crypto-js';
const { MD5 } = crypto_js;
import { TEMP_FOLDER } from '$env/static/private';

interface MapPreviewRequest {
  request_type: string;
  map_w: number;
  map_s: number;
  map_e: number;
  map_n: number;
  epsg: string;
  raster_source: string;
  raster_folder: string;
  output_file: string;
}

function get_map_id(validated: MapPreviewRequest) {
  return MD5(JSON.stringify(validated), Object.keys(validated).sort()).toString();
}

async function validate_request(fd: FormData) {
  const validated = {} as MapPreviewRequest;
  validated.request_type = 'map_preview';

  validated.map_w = parseInt(fd.get('map_w') as string);
  if (isNaN(validated.map_w)) throw new Error('Napačen map_w');
  validated.map_s = parseInt(fd.get('map_s') as string);
  if (isNaN(validated.map_s)) throw new Error('Napačen map_s');
  validated.map_e = parseInt(fd.get('map_e') as string);
  if (isNaN(validated.map_e)) throw new Error('Napačen map_e');
  validated.map_n = parseInt(fd.get('map_n') as string);
  if (isNaN(validated.map_n)) throw new Error('Napačen map_n');
  validated.epsg = fd.get('epsg') as string;
  if (!/^EPSG:\d+$|^Brez$/.test(validated.epsg)) throw new Error('Koordinatni sistem je napačen (EPSG:xxxx ali Brez)');

  if (validated.map_w >= validated.map_e) throw new Error('map_w >= map_e');
  if (validated.map_s >= validated.map_n) throw new Error('map_s >= map_n');

  console.log(DTK25_FOLDER)
  const raster_layer = fd.get('raster_layer') as string;
  validated.raster_source = raster_layer;
  if (raster_layer === 'dtk50') validated.raster_folder = DTK50_FOLDER;
  else if (raster_layer === 'dtk25') validated.raster_folder = DTK25_FOLDER;
  else if (raster_layer === 'osm') validated.raster_folder = 'https://a.tile.openstreetmap.org/{z}/{x}/{y}.png';
  else if (raster_layer === 'otm') validated.raster_folder = 'https://tile.opentopomap.org/{z}/{x}/{y}.png';
  else if (raster_layer === '') validated.raster_folder = '';
  else throw new Error('Napačen raster sloj');

  const output_dir = `${TEMP_FOLDER}/map_previews`;
  if (!fs.existsSync(output_dir)) await fs.promises.mkdir(output_dir, { recursive: true });
  validated.output_file = `${output_dir}/${get_map_id(validated)}.png`;

  return validated;
}

const limiter = new RateLimiter({
  IP: [200, 'h'],
  IPUA: [20, 'm'],
});

export async function POST(event) {
  console.log('POST /api/map_preview');
  const { request } = event;

  let validated: MapPreviewRequest;
  try {
    validated = await validate_request(await request.formData());
  } catch (error) {
    let error_message = '';
    if (error instanceof Error) error_message = error.message;
    else error_message = `${error}`;
    console.log('Bad request:', error_message);
    return new Response(error_message, { status: 400 });
  }
  console.log(`Request for map preview ${validated.map_w} ${validated.map_s} ${validated.map_e} ${validated.map_n} ${validated.epsg} ${validated.raster_folder}`);

  if (fs.existsSync(validated.output_file)) {
    console.log('Returning cached image');
    const png = await fs.promises.readFile(validated.output_file);
    return new Response(png, { headers: { 'Content-Type': 'image/png' } });
  }

  if (await limiter.isLimited(event))
    return new Response("Preveč zahtev", { status: 429 });

  const pythonCommand = getPythonCommand(`${CREATE_MAP_PY_FOLDER}/.venv`);
  const scriptPath = `${CREATE_MAP_PY_FOLDER}/create_map.py`;
  const map_config = Buffer.from(JSON.stringify(validated)).toString('base64');
  const command = `${pythonCommand} ${scriptPath} ${map_config}`;

  try {
    const { stdout, stderr } = await aexec(command);
    if (stdout) console.log(stdout);
    if (stderr) console.error(stderr);
    const png = await fs.promises.readFile(validated.output_file);
    return new Response(png, { headers: { 'Content-Type': 'image/png' } });
  } catch (error) {
    console.error(error);
    return new Response("Interna napaka pri ustvarjanju karte", { status: 500 });
  }
}

function getPythonCommand(venv_folder: string) {
  if (platform() === 'win32') {
    return `${venv_folder}/Scripts/python.exe`;
  } else {
    return `${venv_folder}/bin/python`;
  }
}
