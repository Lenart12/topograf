import crypto_js from 'crypto-js';
import { TEMP_FOLDER } from '$env/static/private';
const { MD5 } = crypto_js;
import fs from "node:fs";

export class TopoFormData {
  fd: FormData;
  constructor(fd: FormData) {
    this.fd = fd;
  }
  get(key: string): string {
    if (!this.fd.has(key)) throw new Error(`Manjka vrednost za ${key}`);
    return this.fd.get(key) as string;
  }
  get_number(key: string): number {
    const value = parseFloat(this.get(key));
    if (isNaN(value)) throw new Error(`Napačna vrednost za ${key}`);
    return value;
  }
  async get_file(key: string, skip_write?: boolean, required?: boolean): Promise<string> {
    if (!this.fd.has(key)) {
      if (required) throw new Error(`Manjka datoteka za ${key}`);
      return '';
    }

    const file = this.fd.get(key);
    if (!file || !(file instanceof File)) throw new Error(`Napačna datoteka za ${key}`);
    if (file.size > 5 * 1024 * 1024) throw new Error(`Datoteka za ${key} je prevelika (max 5MiB)`);
    const ab = await file.arrayBuffer();
    const hash = MD5(crypto_js.lib.WordArray.create(ab)).toString();
    const dest_dir = `${TEMP_FOLDER}/uploads`;
    if (!skip_write && !fs.existsSync(dest_dir)) fs.mkdirSync(dest_dir, { recursive: true });
    const ext = file.name.split('.').pop();
    const dest = `${dest_dir}/${hash}.${ext}`;
    if (!skip_write) await fs.promises.writeFile(dest, new Uint8Array(ab));
    return dest;
  }
}

export function get_request_id(validated: Object) {
  return MD5(JSON.stringify(validated), Object.keys(validated).sort()).toString();
}