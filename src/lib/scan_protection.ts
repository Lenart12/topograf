import type { RequestEvent } from "@sveltejs/kit";
import { RateLimiter } from "sveltekit-rate-limiter/server";

const notFoundLimiter = new RateLimiter({
  IP: [5, '5m'] // 5 requests per minute per IP
})


export default {
  _timedOut: new Set<string>(),

  async isLimited(event: RequestEvent) {
    if (this._timedOut.has(event.getClientAddress())) {
      const limited = await notFoundLimiter.isLimited(event);
      if (limited) {
        return true;
      } else {
        this._timedOut.delete(event.getClientAddress());
      }
    }

    return false;
  },

  async check(event: RequestEvent) {
    const limited = await notFoundLimiter.isLimited(event);
    if (limited) {
      this._timedOut.add(event.getClientAddress());
    }
    return limited;
  },
}