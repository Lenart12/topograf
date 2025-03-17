
export interface ProgressProccess {
  progress?: number
  message?: string
  error?: string
}

interface WaitingPromise {
  resolve: (value: ProgressProccess | PromiseLike<ProgressProccess>) => void
  reject: (reason?: any) => void
  timeout: NodeJS.Timeout
  finish_deadline?: number
  finish_timeout?: NodeJS.Timeout
}

export class ProgressError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ProgressError';
  }
}

const use_pt_debug = false
const pt_dbg = use_pt_debug ? console.log : () => { }
const pt_err = use_pt_debug ? console.error : () => { }

export class ProgressTracker {
  private _runs: Map<string, ProgressProccess> = new Map()
  private _waiting: Map<string, WaitingPromise> = new Map()

  public static E_WAITING = 'Already waiting for progress'
  public static E_WAIT_TIMEOUT = 'Timeout waiting for progress'
  public static E_MISSING_RUN = 'Missing progress run'

  public addRun(id: string): [(progress: number) => void, (message: string) => void, (error: string) => void] {
    const run = { progress: undefined, message: undefined, error: undefined } as ProgressProccess
    this._runs.set(id, run)

    // Returns setters for progress, message and error
    pt_dbg(`Run[${id}]: start`)
    return [
      (progress: number) => {
        pt_dbg(`Progress[${id}]: ${progress}`)
        run.progress = progress
        this._finish_wait(id)
      },
      (message: string) => {
        pt_dbg(`Message[${id}]: ${message}`)
        run.message = message
        this._finish_wait(id)
      },
      (error: string) => {
        pt_err(`Error[${id}]: ${error}`)
        run.error = error
        this._finish_wait(id)
      }
    ]
  }

  public hasRun(id: string) {
    return this._runs.has(id)
  }

  public getRun(id: string) {
    return this._runs.get(id)
  }

  public finishRun(id: string) {
    if (!this.hasRun(id)) return
    pt_dbg(`Run[${id}]: finish`)

    this._waiting.get(id)?.resolve(this.getRun(id)!)
    this._runs.delete(id)
  }

  private _wait_counter = 0
  public wait(id: string, current?: ProgressProccess): Promise<ProgressProccess> {
    const this_wait = this._wait_counter++
    if (this._waiting.has(id)) {
      return new Promise((_, reject) => {
        reject(new Error(ProgressTracker.E_WAITING))
      })
    }

    let immediate_finish = current === undefined && this.hasRun(id)

    if (current !== undefined && !this.hasRun(id)) {
      pt_err(`Waiting[${id}-${this_wait}]: missing run`)
      return new Promise((_, reject) => {
        reject(new Error(ProgressTracker.E_MISSING_RUN))
      })
    }

    pt_dbg(`Waiting[${id}-${this_wait}]: start`)
    return new Promise((resolve, reject) => {
      const waiting_promise = {} as WaitingPromise
      const cleanup = () => {
        pt_dbg(`Waiting[${id}-${this_wait}]: cleanup`)
        clearTimeout(waiting_promise.finish_timeout)
        clearTimeout(waiting_promise.timeout)
        this._waiting.delete(id)
      }
      waiting_promise.resolve = (value) => {
        pt_dbg(`Waiting[${id}-${this_wait}]: resolve`)
        resolve(value)
        cleanup()
      }
      waiting_promise.reject = (reason) => {
        pt_err(`Waiting[${id}-${this_wait}]: reject`, reason)
        reject(reason)
        cleanup()
      }
      waiting_promise.timeout = setTimeout(() => {
        pt_err(`Waiting[${id}-${this_wait}]: timeout`)
        waiting_promise.reject(new Error(ProgressTracker.E_WAIT_TIMEOUT))
      }, 30000)
      this._waiting.set(id, waiting_promise)
      if (immediate_finish) {
        pt_dbg(`Waiting[${id}-${this_wait}]: immediate finish`)
        this._finish_wait(id)
      }
    })
  }

  private _finish_wait(id: string) {
    const waiting_promise = this._waiting.get(id)
    if (waiting_promise === undefined) return
    if (!waiting_promise.finish_deadline) {
      waiting_promise.finish_deadline = Date.now() + 100
    }

    if (Date.now() < waiting_promise.finish_deadline || !waiting_promise.finish_timeout) {
      clearTimeout(waiting_promise.finish_timeout)
      pt_dbg(`Waiting[${id}]: finish attempt`)
      waiting_promise.finish_timeout = setTimeout(() => {
        pt_dbg(`Waiting[${id}]: finish`)
        waiting_promise.resolve(this.getRun(id)!)
      }, 50)
    } else {
      pt_dbg(`Waiting[${id}]: finish deadline`)
    }
  }

  public async handleProgressUpdateRequest(map_id: string, body: string) {
    let current_progress: ProgressProccess | undefined;
    try {
      if (body.length !== 0) {
        current_progress = JSON.parse(body) as ProgressProccess;
      }
    } catch (error) {
      console.log('Progress with bad format:', error);
    }

    try {
      const new_progress = await this.wait(map_id, current_progress);
      return new Response(JSON.stringify(new_progress), { headers: { 'Content-Type': 'application/json' } });
    } catch (error) {
      if (!(error instanceof Error)) {
        return new Response('Internal error', { status: 500 });
      }

      if (error.message === ProgressTracker.E_MISSING_RUN) {
        return new Response(error.message, { status: 404 });
      } else if (error.message === ProgressTracker.E_WAIT_TIMEOUT) {
        return new Response(error.message, { status: 408 });
      } else if (error.message === ProgressTracker.E_WAITING) {
        return new Response(error.message, { status: 429 });
      } else {
        return new Response(`${error}`, { status: 400 });
      }
    }
  }
}

export const CreateMapProgress = new ProgressTracker()
export const MapPreviewProgress = new ProgressTracker()
