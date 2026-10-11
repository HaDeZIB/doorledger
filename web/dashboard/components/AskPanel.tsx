"use client";

import { useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { firstName, modelLabel } from "@/lib/derive";
import type { AskResponse, Household, SummaryResponse, ToolCall } from "@/lib/types";
import type { Mode } from "@/lib/useDoorLedger";
import { IconArrow, IconMail, IconMessage } from "./icons";
import { Card, CardHeader, cx } from "./ui";

const SUGGESTIONS = ["Did Maria come today?", "Is mom's insulin OK?", "Why did you text Luis?"];

interface Exchange {
  id: number;
  question: string;
  reply: AskResponse | null;
  error: string | null;
}

function errorText(e: unknown): string {
  if (e instanceof ApiError && e.status === 503) {
    return "The assistant isn't available right now (no AI model is configured on the server). Everything else on this page still works.";
  }
  if (e instanceof DOMException && e.name === "AbortError") return "That took too long. Please try again.";
  return `Couldn't get an answer: ${e instanceof Error ? e.message : "unknown error"}`;
}

/** "Ask about Rosa's day…": family Q&A over read-only tools. Never auto-called. */
export function AskCard({
  household,
  mode,
  ask,
}: {
  household: Household;
  mode: Mode;
  ask: (q: string) => Promise<AskResponse>;
}) {
  const name = firstName(household.patient.name);
  const [q, setQ] = useState("");
  const [log, setLog] = useState<Exchange[]>([]);
  const [pending, setPending] = useState(false);
  const nextId = useRef(1);
  const inputRef = useRef<HTMLInputElement>(null);

  const submit = async (question: string) => {
    const text = question.trim();
    if (!text || pending) return;
    const id = nextId.current++;
    setLog((l) => [...l.slice(-3), { id, question: text, reply: null, error: null }]);
    setQ("");
    setPending(true);
    try {
      const reply = await ask(text);
      setLog((l) => l.map((x) => (x.id === id ? { ...x, reply } : x)));
    } catch (e) {
      setLog((l) => l.map((x) => (x.id === id ? { ...x, error: errorText(e) } : x)));
    } finally {
      setPending(false);
      inputRef.current?.focus();
    }
  };

  return (
    <Card aria-labelledby="ask-title" className="flex flex-col">
      <CardHeader
        id="ask-title"
        eyebrow={
          <span className="inline-flex items-center gap-1.5">
            <IconMessage size={15} /> Ask DoorLedger
          </span>
        }
        title={`Questions about ${name}'s day`}
      />
      <div className="px-5 pb-5 pt-3 sm:px-6 sm:pb-6">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit(q);
          }}
          className="flex items-center gap-2 rounded-2xl border border-line-strong bg-canvas/60 p-1.5 pl-4 focus-within:border-brand focus-within:bg-surface"
        >
          <label htmlFor="ask-input" className="sr-only">
            Ask a question about {name}&apos;s day
          </label>
          <input
            id="ask-input"
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={`Ask about ${name}'s day…`}
            autoComplete="off"
            maxLength={300}
            className="min-w-0 flex-1 bg-transparent py-2 text-[1.05rem] text-ink placeholder:text-ink-3 focus:outline-none"
          />
          <button
            type="submit"
            disabled={pending || !q.trim()}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-xl bg-brand px-4 py-2 font-semibold text-white transition hover:bg-brand-strong disabled:opacity-40"
          >
            Ask <IconArrow size={16} />
          </button>
        </form>

        <div className="mt-3 flex flex-wrap gap-2" aria-label="Suggested questions">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              disabled={pending}
              onClick={() => void submit(s)}
              className="rounded-full border border-line bg-surface px-3 py-1.5 text-[0.95rem] text-ink-2 transition hover:border-brand/40 hover:bg-brand-soft hover:text-brand-strong disabled:opacity-50"
            >
              {s}
            </button>
          ))}
        </div>

        {log.length > 0 && (
          <ol className="mt-5 space-y-4" aria-live="polite">
            {log.map((x) => (
              <li key={x.id} className="space-y-2">
                <div className="flex justify-end">
                  <p className="max-w-[85%] rounded-2xl rounded-br-md bg-brand-soft px-4 py-2 text-brand-strong">{x.question}</p>
                </div>
                <div className="flex">
                  {x.reply ? (
                    <div className="max-w-[92%] animate-enter">
                      <div className="rounded-2xl rounded-bl-md border border-line bg-canvas px-4 py-3 text-ink">
                        <RichText text={x.reply.answer} />
                      </div>
                      <Provenance tools={x.reply.tool_calls} model={x.reply.model} latencyMs={x.reply.latency_ms} />
                    </div>
                  ) : x.error ? (
                    <p className="max-w-[92%] rounded-2xl rounded-bl-md border border-warn-bar/40 bg-warn-soft px-4 py-3 text-warn">{x.error}</p>
                  ) : (
                    <p className="rounded-2xl rounded-bl-md border border-line bg-canvas px-4 py-3 text-ink-3">
                      <Dots /> Checking today&apos;s records…
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )}

        <p className="mt-4 text-sm text-ink-3">
          Answers come only from what the doorbell saw and what DoorLedger did today. Asking never sends a message to anyone.
          {mode === "mock" && " Demo mode: answers are pre-written from the recorded day."}
        </p>
      </div>
    </Card>
  );
}

/** "Write today's summary": explicit click only (it calls a paid model). */
export function SummaryCard({ mode, summarize }: { mode: Mode; summarize: () => Promise<SummaryResponse> }) {
  const [res, setRes] = useState<SummaryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const run = async () => {
    setPending(true);
    setError(null);
    try {
      setRes(await summarize());
    } catch (e) {
      setError(errorText(e));
    } finally {
      setPending(false);
    }
  };

  return (
    <Card aria-labelledby="summary-title" className="flex flex-col">
      <CardHeader
        id="summary-title"
        eyebrow={
          <span className="inline-flex items-center gap-1.5">
            <IconMail size={15} /> For the family
          </span>
        }
        title="Daily summary"
      />
      <div className="flex flex-1 flex-col px-5 pb-5 pt-3 sm:px-6 sm:pb-6">
        {res ? (
          <div className="animate-enter" aria-live="polite">
            <div className="rounded-2xl bg-canvas px-4 py-3 text-ink">
              <RichText text={res.summary} />
            </div>
            <Provenance tools={res.tool_calls} model={res.model} latencyMs={res.latency_ms} />
          </div>
        ) : (
          <p className="text-ink-2">A short, plain-language recap of today, written from the ledger. Good for sending to the rest of the family.</p>
        )}
        {error && <p className="mt-3 rounded-2xl border border-warn-bar/40 bg-warn-soft px-4 py-3 text-warn">{error}</p>}
        <div className="mt-auto pt-4">
          <button
            type="button"
            onClick={() => void run()}
            disabled={pending}
            className={cx(
              "inline-flex items-center gap-2 rounded-xl px-4 py-2 font-semibold transition disabled:opacity-50",
              res ? "border border-line-strong bg-surface text-ink-2 hover:bg-canvas" : "bg-brand text-white hover:bg-brand-strong",
            )}
          >
            {pending ? (
              <>
                <Dots /> Writing…
              </>
            ) : res ? (
              "Write it again"
            ) : (
              "Write today's summary"
            )}
          </button>
          {mode === "mock" && !res && <p className="mt-2 text-sm text-ink-3">Demo mode: uses a pre-written template.</p>}
        </div>
      </div>
    </Card>
  );
}

function Provenance({ tools, model, latencyMs }: { tools: ToolCall[]; model: string; latencyMs: number }) {
  const names = [...new Set((tools ?? []).map((t) => t.name))];
  return (
    <p className="mt-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-0.5 px-1 text-[0.8rem] text-ink-3">
      <span>
        grounded in:{" "}
        {names.length ? <span className="font-mono text-[0.76rem] text-ink-2">{names.join(", ")}</span> : <span>no records (general answer)</span>}
      </span>
      {model && (
        <span title={model}>
          · {modelLabel(model)}
          {latencyMs > 0 && ` · ${(latencyMs / 1000).toFixed(1)} s`}
        </span>
      )}
    </p>
  );
}

function Dots() {
  return (
    <span className="mr-1 inline-flex gap-0.5 align-middle" aria-hidden>
      {[0, 1, 2].map((i) => (
        <span key={i} className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" style={{ animationDelay: `${i * 160}ms` }} />
      ))}
    </span>
  );
}

/** Minimal formatting for model text: paragraphs, "- " bullets and **bold**. No HTML injection. */
function RichText({ text }: { text: string }) {
  const blocks = text.trim().split(/\n{2,}/);
  return (
    <div className="space-y-2 leading-relaxed">
      {blocks.map((b, i) => {
        const lines = b.split("\n");
        if (lines.every((l) => /^\s*([-*•]|\d+\.)\s+/.test(l))) {
          return (
            <ul key={i} className="list-disc space-y-1 pl-5">
              {lines.map((l, j) => (
                <li key={j}>
                  <Inline text={l.replace(/^\s*([-*•]|\d+\.)\s+/, "")} />
                </li>
              ))}
            </ul>
          );
        }
        return (
          <p key={i} className="whitespace-pre-line">
            <Inline text={b.replace(/^#+\s*/gm, "")} />
          </p>
        );
      })}
    </div>
  );
}

function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("**") && p.endsWith("**") ? (
          <strong key={i} className="font-semibold">
            {p.slice(2, -2)}
          </strong>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}
