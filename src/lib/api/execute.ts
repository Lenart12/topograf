import { platform } from 'os';
import fs from 'node:fs';
import { CREATE_MAP_PY_FOLDER } from '$env/static/private';
import util from 'util';
import { execFile as execFileSync } from 'node:child_process';
const execFile = util.promisify(execFileSync);

function getPythonBin(venv_folder: string) {
  if (platform() === 'win32') {
    return `${venv_folder}/Scripts/python.exe`;
  } else {
    return `${venv_folder}/bin/python`;
  }
}

const python_bin = getPythonBin(`${CREATE_MAP_PY_FOLDER}/.venv`);
const script_path = `${CREATE_MAP_PY_FOLDER}/create_map.py`;

if (!fs.existsSync(script_path)) {
  console.error(`Script not found: ${script_path}`);
  process.exit(1);
}

export async function runCreateMapPy(request: Object) {
  const child = execFile(
    python_bin,
    [script_path, ...Object.entries(request).flatMap((kv) => [`--${kv[0]}`, kv[1]])]
  )

  const { stdout, stderr } = await child;
  if (stdout) console.log(stdout);
  if (stderr) console.error(stderr);
}