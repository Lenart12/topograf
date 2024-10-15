import type { ParamMatcher } from '@sveltejs/kit';

export const match = ((param: string): boolean => {
  // Check map_id is a valid MD5 hash and that the map exists
  if (!param) return false;
  if (!/^[a-f0-9]{32}$/.test(param)) return false;

  return true;
}) satisfies ParamMatcher;