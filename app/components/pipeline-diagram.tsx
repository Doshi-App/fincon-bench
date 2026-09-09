import type { ReactNode } from "react";

function Step({ title, detail, human }: { title: string; detail: string; human?: boolean }) {
  return (
    <div
      className={`min-w-[11rem] flex-1 rounded-lg border bg-surface-1 p-3.5 ${
        human ? "border-t-[3px] border-t-accent border-x-border border-b-border" : "border-border"
      }`}
    >
      <p className="text-sm font-semibold text-fg">{title}</p>
      <p className="mt-1 text-xs leading-relaxed text-muted">{detail}</p>
    </div>
  );
}

function Arrow() {
  return (
    <div className="flex shrink-0 items-center justify-center px-1 text-muted" aria-hidden="true">
      <svg width="20" height="12" viewBox="0 0 20 12" fill="none">
        <path d="M0 6H17M17 6L12 1M17 6L12 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  );
}

function Lane({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</p>
      <div className="mt-3 flex flex-wrap items-stretch gap-2 sm:flex-nowrap">{children}</div>
    </div>
  );
}

/**
 * The 2-pass run, as a diagram — the mechanism the site keeps referring
 * back to, not a decorative flowchart. A teal top border marks a step a
 * person does, same convention as the README's mermaid diagram.
 */
export function PipelineDiagram() {
  return (
    <div className="space-y-8">
      <Lane title="Pass 1 — choose the judge (the replies already exist)">
        <Step human title="Meta-eval set" detail="394 probes with a pre-written reply (274 written by hand, 120 drafted by a model and authored by a person) plus 150 replies written by leaderboard models." />
        <Arrow />
        <div className="flex flex-1 flex-col gap-2 sm:flex-row">
          <Step human title="Labellers" detail="424 rows, two blind passes: one by a person, one model-assisted. A person adjudicates the disagreements against the rule." />
          <Step title="Candidate judges" detail="28 models mark the same rows, blind to the labels, never on rows their own family wrote." />
        </div>
        <Arrow />
        <Step title="The judges" detail="Two judges from the leading group, by macro-F1 and running cost, plus a tiebreak for the replies they disagree on." />
      </Lane>
      <Lane title="Pass 2 — score the assistants (the replies do not exist yet)">
        <Step title="Benchmark set" detail="The same probes, reply column empty." />
        <Arrow />
        <Step title="Assistants under test" detail="Each model writes its own reply; repeated probes run several passes and the majority verdict counts." />
        <Arrow />
        <Step title="The judges" detail="Both judges mark every reply against the same rules; the tiebreak decides where they split." />
        <Arrow />
        <Step title="Leaderboard" detail="Fail = a finding that cites its clause. Pass = no record." />
      </Lane>
      <p className="text-xs text-muted">
        <span className="mr-1.5 inline-block h-2.5 w-2.5 rounded-sm border-t-2 border-t-accent bg-surface-1 align-middle" />
        marks a step a person does. Everything else is a model.
      </p>
    </div>
  );
}
