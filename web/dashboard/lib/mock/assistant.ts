// Mock CareAgent: canned but state-aware answers for /api/ask and /api/summary, so the demo
// works without Bedrock. Answers are built only from the State (like the real agent's tools),
// and report the same read-only tool names the backend agent uses.

import type { AskResponse, Household, State, SummaryResponse, ToolCall } from "../types";
import { actionHeadline, featuredDelivery, firstName, latestFindings, personFor, visitStatus } from "../derive";
import { exposureDirection, unsafeLimitC } from "../thermal";
import { degBoth } from "../units";
import { fmtDuration, fmtTime, ms } from "../time";

export const MOCK_MODEL = "mock-canned";

const TODAY: ToolCall = { name: "get_today_status", input: {} };
const TIMELINE: ToolCall = { name: "get_timeline", input: { since_hour: 0 } };

const temp = (c: number) => degBoth(c, 1).replace(/\.0°F/, "°F");

function visitAnswer(st: State, h: Household): string {
  const tz = h.patient.timezone;
  const name = firstName(h.patient.name);
  const now = ms(st.now);
  const visits = [...st.visits].filter((v) => ms(v.expectation.window_start) <= now + 60 * 60000);
  if (!visits.length) return `No caregiver visit has started yet today. The next one is scheduled later.`;
  return visits
    .map((v) => {
      const e = v.expectation;
      const who = (v.check_in?.detail.caregiver as string | undefined) ?? e.caregiver ?? "The aide";
      const s = visitStatus(v, st.now, st.findings);
      const at = fmtTime(e.window_start, tz);
      switch (s.key) {
        case "completed":
        case "short": {
          const late = Math.round((ms(v.check_in!.at) - ms(e.window_start)) / 60000);
          return (
            `Yes. ${firstName(who)} checked in at ${fmtTime(v.check_in!.at, tz)} for the ${at} visit` +
            (late > 15 ? ` (${late} min late)` : "") +
            ` and left at ${fmtTime(v.check_out!.at, tz)}, ${v.minutes_on_site} of ${e.planned_minutes} planned minutes.` +
            (s.key === "short" ? " That's short, so we flagged it for the agency." : "")
          );
        }
        case "in_progress":
          return `Yes. ${firstName(who)} checked in at ${fmtTime(v.check_in!.at, tz)} with her rotating code and is with ${name} now.`;
        case "missed":
          return `Not yet. No one has checked in for the ${at} visit, so it's marked missed and we've contacted the agency.`;
        case "late":
          return `Not yet. ${firstName(who)} is late for the ${at} visit; the agency has been told.`;
        case "awaiting":
          return `${firstName(who)} is due now for the ${at} visit; no check-in yet.`;
        default:
          return `${firstName(who)} is scheduled for ${at}.`;
      }
    })
    .join(" ");
}

function insulinAnswer(st: State, h: Household): string {
  const tz = h.patient.timezone;
  const d = featuredDelivery(st);
  if (!d) return "There's no medication delivery on today's plan.";
  const med = d.expectation.medication?.name ?? "The medication";
  const est = d.estimate;
  const dir = exposureDirection(est, d.expectation.medication, h.ambient.celsius);
  const cold = dir === "cold";
  if (!d.dropped || !est) {
    return `${med} hasn't been delivered yet. It's expected between ${fmtTime(d.expectation.window_start, tz)} and ${fmtTime(d.expectation.window_end, tz)}; we'll start an exposure clock as soon as the Ring doorbell sees it on the porch${cold ? ` (it's ${temp(h.ambient.celsius)} outside, so freezing is the risk)` : ""}.`;
  }
  const limitC = unsafeLimitC(est, d.expectation.medication, dir);
  const limit = limitC !== null ? degBoth(limitC) : "its limit";
  if (d.removed) {
    if (est.status === "compromised") {
      return cold
        ? `It was brought inside at ${fmtTime(d.removed.at, tz)}, but after ${fmtDuration(est.minutes_on_porch)} on the porch it may have frozen. Frozen insulin has to be thrown away, so please don't use it and call the pharmacy for a replacement. (Temperatures are model estimates, not a thermometer.)`
        : `It was brought inside at ${fmtTime(d.removed.at, tz)}, but after ${fmtDuration(est.minutes_on_porch)} on the porch the box likely passed ${limit}. Please call the pharmacy before using it. (Temperatures are model estimates, not a thermometer.)`;
    }
    return `It looks OK. ${med} sat on the porch ${fmtDuration(est.minutes_on_porch)} and was brought inside at ${fmtTime(d.removed.at, tz)}. Our estimate ${cold ? "bottomed out" : "peaked"} around ${temp(est.estimated_internal_c)}, ${cold ? `just above freezing (${limit}), so it most likely didn't freeze` : `under the ${limit} limit`}. It should go in the fridge now. (Estimate from a thermal model, not a thermometer.)`;
  }
  if (est.status === "compromised") {
    return cold
      ? `It's still on the porch after ${fmtDuration(est.minutes_on_porch)} and the box is estimated at or below freezing, so it may have frozen. Frozen insulin must be thrown away; don't use it until the pharmacy confirms.`
      : `It's still on the porch after ${fmtDuration(est.minutes_on_porch)} and the box is estimated past ${limit}. Don't use it until the pharmacy confirms.`;
  }
  const left = est.minutes_until_excursion_max;
  return `It's on the porch right now, ${fmtDuration(est.minutes_on_porch)} so far, estimated ${temp(est.estimated_internal_c)} inside the box${
    left !== null ? `, about ${fmtDuration(left)} before it ${cold ? `freezes at ${limit}` : `reaches ${limit}`}` : ""
  }. ${est.status === "at_risk" ? "We're asking the next person on the list to bring it inside." : `We've asked ${firstName(h.patient.name)} to bring it in.`}`;
}

function luisAnswer(st: State, h: Household): string {
  const tz = h.patient.timezone;
  const luis = h.people.find((p) => p.role === "neighbor");
  const mine = st.actions.filter((a) => luis && personFor(h, a.target)?.name === luis.name);
  if (!luis || !mine.length) return `We haven't contacted ${luis ? firstName(luis.name) : "the neighbor"} today.`;
  const a = mine[0];
  const f = st.findings.find((x) => x.id === a.finding_id);
  const before = st.actions.filter((x) => ms(x.at) < ms(a.at) && x.finding_id && personFor(h, x.target)?.role === "patient");
  const reply = a.data.reply ? ` He replied "${String(a.data.reply)}".` : "";
  return (
    `At ${fmtTime(a.at, tz)} we ${actionHeadline(a, h).split(" ")[0].toLowerCase()} ${firstName(luis.name)} because ${
      f ? reasonFor(f, h) : "the insulin needed to come inside"
    }.` +
    (before.length ? ` ${firstName(h.patient.name)} had been contacted first and didn't respond.` : "") +
    reply +
    ` He's next in the order the family set: ${firstName(h.patient.name)}, then ${firstName(luis.name)}, then family.`
  );
}

function reasonFor(f: State["findings"][number], h: Household): string {
  const name = firstName(h.patient.name);
  const c = typeof f.data.estimated_internal_c === "number" ? f.data.estimated_internal_c : null;
  const left = typeof f.data.minutes_until_excursion_max === "number" ? f.data.minutes_until_excursion_max : null;
  if (f.kind === "package_at_risk" && f.data.direction === "cold") {
    return `${name}'s insulin was getting too cold on the porch${c !== null ? ` (box estimated at ${temp(c)}` : ""}${
      c !== null && left !== null ? `, about ${fmtDuration(left)} from freezing)` : c !== null ? ")" : ""
    } and she hadn't brought it in`;
  }
  return f.summary.charAt(0).toLowerCase() + f.summary.slice(1).replace(/\.$/, "");
}

function genericAnswer(st: State, h: Household): string {
  const issues = latestFindings(st.findings).filter((f) => f.severity !== "info");
  return issues.length
    ? `So far today: ${issues.map((f) => f.summary).join(" ")}`
    : `Everything expected at ${firstName(h.patient.name)}'s door so far has arrived. Nothing needs your attention.`;
}

export function mockAsk(question: string, st: State, h: Household): AskResponse {
  const q = question.toLowerCase();
  let answer: string;
  let tools: ToolCall[] = [TODAY];
  if (/insulin|medic|fridge|porch|package|box|pharm/.test(q)) answer = insulinAnswer(st, h);
  else if (/luis|neighbo|text|call|why did/.test(q)) {
    answer = luisAnswer(st, h);
    tools = [TODAY, TIMELINE];
  } else if (/maria|aide|caregiver|visit|come|came|arriv/.test(q)) {
    answer = visitAnswer(st, h);
    tools = [TODAY, TIMELINE];
  } else answer = genericAnswer(st, h);
  return { answer, tool_calls: tools, model: MOCK_MODEL, latency_ms: 0, usage: null };
}

export function mockSummary(st: State, h: Household): SummaryResponse {
  const name = firstName(h.patient.name);
  const parts = [visitAnswer(st, h).replace(/^Yes\. /, ""), insulinAnswer(st, h).replace(/^It looks OK\. /, "")];
  const contacted = st.actions.filter((a) => a.kind === "notify" || a.kind === "request_backup").length;
  const text =
    `${name}'s day so far. ${parts.join(" ")}` +
    (contacted ? ` DoorLedger sent ${contacted} message${contacted > 1 ? "s" : ""} or call${contacted > 1 ? "s" : ""} to handle it.` : "");
  return { summary: text, tool_calls: [TODAY, TIMELINE], model: MOCK_MODEL, latency_ms: 0, usage: null };
}
