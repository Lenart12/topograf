import { platform } from 'os';
import util from 'util';
import { exec } from 'child_process';
import { tmpdir } from 'os';
import fs from 'node:fs';
import { CREATE_MAP_PY_FOLDER, DTK50_FOLDER } from '$env/static/private';
const aexec = util.promisify(exec);


const allowed_chars = /^[a-zA-Z0-9À-ž\-\.\,\! ]*$/;

interface CreateMapRequest {
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
  slikal: string;
  slikad: string;
  dtk50_folder: string;
  output_file: string;
}

async function validate_request_file(file: File | string | null) {
  if (file === null) return '';
  if (file === '') return '';
  if (!(file instanceof File)) throw new Error('Datoteka za sliko ni datoteka');

  if (!['image/jpeg', 'image/png'].includes(file.type)) throw new Error('Datoteka za sliko ni slika (jpeg/png)');
  if (file.size > 5000000) throw new Error('Slika je prevelika (max 5MB)');
  if (file.name.length > 100) throw new Error('Slika ima predolgo ime (max 100 znakov)');
  if (!allowed_chars.test(file.name)) throw new Error('Ime slike vsebuje nedovoljene znake');

  const file_path = `${tmpdir()}/topodtk-${Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join('')}-${file.name}`;
  const ab = Buffer.from(await file.arrayBuffer());
  await fs.promises.writeFile(file_path, ab);
  return file_path;
}

async function validate_request(fd: FormData) {
  const validated = {} as CreateMapRequest;
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
  try {
    validated.slikal = await validate_request_file(fd.get('slikal') as File | string | null);
    validated.slikad = await validate_request_file(fd.get('slikad') as File | string | null);
  } catch (error) {
    if (validated.slikal) await fs.promises.unlink(validated.slikal);
    if (validated.slikad) await fs.promises.unlink(validated.slikad);
    throw error;
  }
  validated.dtk50_folder = DTK50_FOLDER;
  validated.output_file = `${tmpdir()}/topodtk-${Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join('')}.pdf`;
  return validated;
}

export async function POST({ request, cookies }) {
  let validated: CreateMapRequest;
  try {
    validated = await validate_request(await request.formData());
  } catch (error) {
    return new Response(`${error}`, { status: 400 });
  }
  console.log(validated);

  const pythonCommand = getPythonCommand(`${CREATE_MAP_PY_FOLDER}/.venv`);
  const scriptPath = `${CREATE_MAP_PY_FOLDER}/create_map.py`;
  const map_config = Buffer.from(JSON.stringify(validated)).toString('base64');
  const command = `${pythonCommand} ${scriptPath} ${map_config}`;

  try {
    const { stdout, stderr } = await aexec(command);
    console.log(`Output: ${stdout}`);
    console.error(`Error: ${stderr}`);
    const pdf = await fs.promises.readFile(validated.output_file);
    // await fs.promises.unlink(validated.output_file);
    return new Response(pdf, { headers: { 'Content-Type': 'application/pdf' } });
  } catch (error) {
    console.error(`Error: ${error}`);
    return new Response("Interna napaka pri ustvarjanju karte", { status: 500 });
  } finally {
    if (validated.slikal) await fs.promises.unlink(validated.slikal);
    if (validated.slikad) await fs.promises.unlink(validated.slikad);
  }
}

function getPythonCommand(venv_folder: string) {
  if (platform() === 'win32') {
    return `${venv_folder}/Scripts/python.exe`;
  } else {
    return `${venv_folder}/bin/python`;
  }
}
