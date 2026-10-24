/**
 * The live AI trace (D-023 #3): reads POST /emails/{id}/interpret/stream, a
 * server-sent event stream of InterpretStep, and hands each step to the
 * inbox as it arrives. POST, not EventSource, because EventSource cannot send
 * the X-Acting-User header.
 *
 * If the stream fails for any reason (error status, a frame that does not
 * parse, the stream ending before `done`), this falls back to the plain
 * POST /emails/{id}/interpret and returns that result all at once.
 */
import { api, baseHeaders, buildUrl, type Schema } from "@/lib/api/client";
import { reportApiOnline } from "@/lib/api/status";

export type InterpretStep =
  | Schema<"TraceStart">
  | Schema<"TraceBankStripped">
  | Schema<"TraceField">
  | Schema<"TraceLine">
  | Schema<"TraceCategory">
  | Schema<"TraceMissing">
  | Schema<"TraceInjection">
  | Schema<"TraceDone">;

export type TraceSource = Schema<"TraceStart">["source"];

const STEP_KINDS = new Set<InterpretStep["kind"]>([
  "start",
  "bank_stripped",
  "field",
  "line",
  "category",
  "missing",
  "injection",
  "done",
]);

class StreamBroken extends Error {}

function parseStep(data: string): InterpretStep {
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    throw new StreamBroken("A step did not parse as JSON");
  }
  if (
    !value ||
    typeof value !== "object" ||
    !STEP_KINDS.has((value as { kind?: unknown }).kind as InterpretStep["kind"])
  ) {
    throw new StreamBroken("A step had no known kind");
  }
  return value as InterpretStep;
}

/**
 * Splits a text/event-stream body into `event: step` payloads. Frames can
 * arrive split across chunks, or several in one chunk.
 */
async function* readSteps(body: ReadableStream<Uint8Array>): AsyncGenerator<InterpretStep> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      // CRLF to LF; a CR split from its LF is joined on the next pass.
      buffer = buffer.replace(/\r\n/g, "\n");
      let end = buffer.indexOf("\n\n");
      while (end >= 0) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        let event = "message";
        const data: string[] = [];
        for (const line of frame.split("\n")) {
          if (line.startsWith(":")) continue; // comment / keep-alive
          const colon = line.indexOf(":");
          const field = colon < 0 ? line : line.slice(0, colon);
          const raw = colon < 0 ? "" : line.slice(colon + 1);
          const text = raw.startsWith(" ") ? raw.slice(1) : raw;
          if (field === "event") event = text;
          else if (field === "data") data.push(text);
        }
        if (event === "step" && data.length > 0) yield parseStep(data.join("\n"));
        end = buffer.indexOf("\n\n");
      }
      if (done) return;
    }
  } finally {
    reader.releaseLock();
  }
}

export type TraceResult = {
  interpretation: Schema<"Interpretation">;
  /** Null when the stream failed and the plain POST answered instead. */
  source: TraceSource | null;
  streamed: boolean;
};

/**
 * Reads one email with the AI, calling `onStep` for every step of the trace.
 * Throws AbortError when `signal` aborts, and ApiError when the fallback POST fails too.
 */
export async function interpretWithTrace(
  emailId: string,
  opts: { signal: AbortSignal; stepMs?: number; onStep?: (step: InterpretStep) => void },
): Promise<TraceResult> {
  try {
    const url = buildUrl(
      "/emails/{email_id}/interpret/stream",
      { email_id: emailId },
      { step_ms: opts.stepMs },
    );
    const res = await fetch(url, {
      method: "POST",
      headers: { ...baseHeaders(), Accept: "text/event-stream" },
      signal: opts.signal,
      cache: "no-store",
    });
    if (!res.ok || !res.body) throw new StreamBroken(`The stream answered ${res.status}`);
    reportApiOnline();
    let source: TraceSource | null = null;
    for await (const step of readSteps(res.body)) {
      if (step.kind === "start") source = step.source;
      opts.onStep?.(step);
      if (step.kind === "done") {
        return { interpretation: step.interpretation, source, streamed: true };
      }
    }
    throw new StreamBroken("The stream ended before the AI finished");
  } catch (e) {
    if (opts.signal.aborted) throw e;
    // Anything else: read the email the plain way and show the result at once.
    const interpretation = await api.POST("/emails/{email_id}/interpret", {
      path: { email_id: emailId },
      signal: opts.signal,
    });
    return { interpretation, source: null, streamed: false };
  }
}
