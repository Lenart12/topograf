import { platform } from 'os';
import fs from 'node:fs';
import { CREATE_MAP_PY_FOLDER } from '$env/static/private';
import { MAX_MAPPERS } from '$env/static/private';
import { spawn } from 'node:child_process';
import { ProgressError } from '$lib/api/progress_tracker';
import pLimit from 'p-limit';

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

const concurrent_execution_limit = pLimit(parseInt(MAX_MAPPERS) || 2);

export async function runCreateMapPy(request: Object, on_progress: (progress: number) => void, on_message: (message: string) => void, on_error: (error: string) => void) {
  const with_limit = concurrent_execution_limit(() => new Promise((resolve, reject) => {
    const args = [script_path, ...Object.entries(request).flatMap((kv) => [`--${kv[0]}`, kv[1]]), '--emit-progress'];

    on_message('Zagon obdelave');
    const child = spawn(python_bin, args);

    child.stdout.on('data', (data) => {
      const output = data.toString().trim();
      console.log(output);
    });

    let last_error = 'Interna napaka';
    child.stderr.on('data', (data) => {
      const output = data.toString();
      const lines = output.split('\n');
      let latest_progress;
      let latest_message;
      let latest_error;
      lines.forEach((line: string) => {
        if (line.length === 0) return;
        if (line.startsWith('PROGRESS:')) {
          latest_progress = parseFloat(line.split(' ')[1])
        }
        else if (line.startsWith('MESSAGE: ')) {
          latest_message = line.substring(9);
        }
        else if (line.startsWith('ERROR: ')) {
          latest_error = line.substring(7);
        }
        else {
          console.error(line);
        }
      });
      if (latest_progress !== undefined && on_progress !== undefined) {
        on_progress(latest_progress)
      }
      if (latest_message !== undefined && on_message !== undefined) {
        on_message(latest_message)
      }
      if (latest_error !== undefined && on_error !== undefined) {
        last_error = latest_error;
        on_error(latest_error)
      }
    });

    child.on('error', (error) => {
      console.error(error);
      reject(error);
    });

    child.on('close', (code) => {
      if (code === 0) {
        resolve(code);
      } else {
        reject(new ProgressError(last_error));
      }
    });
  }))
  on_message('Čakanje na vrsto');
  return with_limit;
}