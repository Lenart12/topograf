import { platform } from 'os';
import util from 'util';
import { exec } from 'child_process';
import fs from 'node:fs';
import { CREATE_MAP_PY_FOLDER, DTK50_FOLDER, TEMP_FOLDER } from '$env/static/private';
const aexec = util.promisify(exec);
import { RateLimiter } from 'sveltekit-rate-limiter/server';
import crypto_js from 'crypto-js';
const { MD5 } = crypto_js;

const allowed_chars = /^[a-zA-Z0-9À-ž\-.,! ]*$/;

interface CreateMapRequest {
  map_id: string;
  request_type: string;

  map_size_w_m: number;
  map_size_h_m: number;

  map_w: number;
  map_s: number;
  map_e: number;
  map_n: number;

  target_scale: number;
  epsg: string;
  edge_wgs84: boolean;

  naslov1: string;
  naslov2: string;
  dodatno: string;
  slikal: string;
  slikad: string;

  control_points: string;

  raster_folder: string;
  temp_folder: string;
}

async function validate_request_file(file: File | string | null) {
  if (file === null) return '';
  if (file === '') return '';
  if (!(file instanceof File)) throw new Error('Datoteka za sliko ni datoteka');

  if (!['image/jpeg', 'image/png'].includes(file.type)) throw new Error('Datoteka za sliko ni slika (jpeg/png)');
  if (file.size > 5000000) throw new Error('Slika je prevelika (max 5MB)');
  if (file.name.length > 100) throw new Error('Slika ima predolgo ime (max 100 znakov)');
  if (!allowed_chars.test(file.name)) throw new Error('Ime slike vsebuje nedovoljene znake');

  const ab = await file.arrayBuffer();
  const hexdigest = MD5(crypto_js.lib.WordArray.create(ab)).toString();

  const cache_dir = `${TEMP_FOLDER}/imgs`;
  if (!fs.existsSync(cache_dir)) await fs.promises.mkdir(cache_dir);

  const ext = file.type === 'image/jpeg' ? 'jpg' : 'png';
  const fn = `${TEMP_FOLDER}/imgs/${hexdigest}.${ext}`;

  await fs.promises.writeFile(fn, new Uint8Array(ab));
  return fn;
}

async function validate_request(fd: FormData) {
  const validated = {} as CreateMapRequest;
  validated.request_type = 'create_map';

  validated.map_size_w_m = parseFloat(fd.get('map_size_w_m') as string);
  if (isNaN(validated.map_size_w_m) || validated.map_size_w_m > 1) throw new Error('Velikost karte je prevelika (širina) (max 1m)');
  validated.map_size_h_m = parseFloat(fd.get('map_size_h_m') as string);
  if (isNaN(validated.map_size_h_m) || validated.map_size_h_m > 1) throw new Error('Velikost karte je prevelika (višina) (max 1m)');
  validated.map_w = parseInt(fd.get('map_w') as string);
  if (isNaN(validated.map_w)) throw new Error('Napačen map_w');
  validated.map_s = parseInt(fd.get('map_s') as string);
  if (isNaN(validated.map_s)) throw new Error('Napačen map_s');
  validated.map_e = parseInt(fd.get('map_e') as string);
  if (isNaN(validated.map_e)) throw new Error('Napačen map_e');
  validated.map_n = parseInt(fd.get('map_n') as string);
  if (isNaN(validated.map_n)) throw new Error('Napačen map_n');

  if (validated.map_w >= validated.map_e) throw new Error('map_w >= map_e');
  if (validated.map_s >= validated.map_n) throw new Error('map_s >= map_n');

  validated.target_scale = parseInt(fd.get('target_scale') as string);
  if (isNaN(validated.target_scale) || validated.target_scale > 100000) throw new Error('Merilo je napačno ali preveliko (max 1:100000)');
  validated.naslov1 = fd.get('naslov1') as string;
  if (validated.naslov1.length > 30) throw new Error('Naslov (1) je predolg (max 30 znakov)');
  validated.naslov2 = fd.get('naslov2') as string;
  if (validated.naslov2.length > 30) throw new Error('Naslov (2) je predolg (max 30 znakov)');
  validated.dodatno = fd.get('dodatno') as string;
  if (validated.dodatno.length > 70) throw new Error('Dodatna vrstica je predolgo (max 70 znakov)');
  validated.epsg = fd.get('epsg') as string;
  if (!/^EPSG:\d+$|^Brez$/.test(validated.epsg)) throw new Error('Koordinatni sistem je napačen (EPSG:xxxx ali Brez)');
  validated.edge_wgs84 = fd.get('edge_wgs84') === 'true';
  validated.control_points = fd.get('control_points') as string;
  if (validated.control_points.length !== 0) {
    try {
      const cps = JSON.parse(validated.control_points);
      if (!Array.isArray(cps.cps)) throw new Error('Kontrolne točke niso v pravilni obliki (JSON)');
    } catch (error) {
      throw new Error('Kontrolne točke niso v pravilni obliki (JSON)');
    }
  }

  if (fd.get('raster_layer') === 'dtk50') validated.raster_folder = DTK50_FOLDER;
  else if (fd.get('raster_layer') === '') validated.raster_folder = '';
  else throw new Error('Napačen raster sloj');
  validated.temp_folder = TEMP_FOLDER;

  try {
    validated.slikal = await validate_request_file(fd.get('slikal') as File | string | null);
    validated.slikad = await validate_request_file(fd.get('slikad') as File | string | null);
  } catch (error) {
    if (validated.slikal) await fs.promises.unlink(validated.slikal);
    if (validated.slikad) await fs.promises.unlink(validated.slikad);
    throw error;
  }
  return validated;
}

function get_map_id(validated: CreateMapRequest) {
  return MD5(JSON.stringify(validated), Object.keys(validated).sort()).toString();
}

const limiter = new RateLimiter({
  IP: [10, 'h'],
  IPUA: [2, 'm'],
});

export async function POST(event) {
  console.log('POST /api/create_map');
  const { request } = event;
  let validated: CreateMapRequest;
  try {
    validated = await validate_request(await request.formData());
  } catch (error) {
    let error_message = '';
    if (error instanceof Error) error_message = error.message;
    else error_message = `${error}`;
    console.log('Bad request:', error_message);
    return new Response(error_message, { status: 400 });
  }

  validated.map_id = get_map_id(validated);

  console.log(`Request for map ID: ${validated.map_id}`);
  const maps_folder = `${TEMP_FOLDER}/maps`;

  if (!fs.existsSync(maps_folder)) await fs.promises.mkdir(maps_folder);

  if (fs.existsSync(`${maps_folder}/${validated.map_id}/map.pdf`)) {
    console.log(`Using cached map`);
    return new Response(validated.map_id);
  }

  if (await limiter.isLimited(event))
    return new Response("Preveč zahtev na strežnik. Poskusi kasneje!", { status: 429 });

  const pythonCommand = getPythonCommand(`${CREATE_MAP_PY_FOLDER}/.venv`);
  const scriptPath = `${CREATE_MAP_PY_FOLDER}/create_map.py`;
  const map_config = Buffer.from(JSON.stringify(validated)).toString('base64');
  const command = `${pythonCommand} ${scriptPath} ${map_config}`;

  try {
    const { stdout, stderr } = await aexec(command);
    if (stdout) console.log(stdout);
    if (stderr) console.error(stderr);
    return new Response(validated.map_id);
  } catch (error) {
    console.error(error);
    return new Response("Interna napaka pri ustvarjanju karte", { status: 500 });
  } finally {
    if (validated.slikal && fs.existsSync(validated.slikal)) await fs.promises.unlink(validated.slikal);
    if (validated.slikad && fs.existsSync(validated.slikad)) await fs.promises.unlink(validated.slikad);
  }
}

function getPythonCommand(venv_folder: string) {
  if (platform() === 'win32') {
    return `${venv_folder}/Scripts/python.exe`;
  } else {
    return `${venv_folder}/bin/python`;
  }
}
