import fs from 'node:fs';
import { Readable } from 'node:stream';
import { TEMP_FOLDER } from '$env/static/private';

export async function GET(event) {
  const { map_id, file_name } = event.params;

  const maps_folder = `${TEMP_FOLDER}/maps`;
  const file_path = `${maps_folder}/${map_id}/${file_name}`;
  const file_path_abs = fs.realpathSync(file_path);

  if (!file_path_abs.startsWith(fs.realpathSync(maps_folder))) return new Response('Path traversal detected', { status: 400 });
  if (!fs.existsSync(file_path_abs)) return new Response('File not found', { status: 404 });

  const file_stream = fs.createReadStream(file_path_abs);
  const content_type = (() => {
    if (file_name.endsWith('.pdf')) return 'application/pdf';
    if (file_name.endsWith('.json')) return 'application/json';
    if (file_name.endsWith('.png')) return 'image/png';
    return 'application/octet-stream';
  })();

  const readable = Readable.toWeb(file_stream) as ReadableStream;
  return new Response(readable, {
    headers: {
      'Content-Type': content_type,
    },
  });
}

