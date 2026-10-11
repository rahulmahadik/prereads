import { useEffect, useState } from "react";
import { api } from "../api";
import Cover from "../components/Cover";
import ReadinessMeter from "../components/ReadinessMeter";
import { FAMILIARITY, TopBar, useBack } from "../components/ui";
import { navigate } from "../router";
import { meetPlan, meetSummary } from "../meet";
import type { Route, Stop } from "../types";

function Picker({ label, level, onChange }: { label: string; level: number; onChange: (l: number) => void }) {
  return (
    <fieldset className="meet-picker">
      <legend>{label}</legend>
      <div className="meet-levels">
        {FAMILIARITY.map((f) => (
          <button key={f.level} type="button" className={`meet-level ${f.level === level ? "on" : ""}`} aria-pressed={f.level === level} onClick={() => onChange(f.level)}>
            {f.title}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

export default function Meet({ id, title, author }: { id: string; title: string; author: string }) {
  const goBack = useBack("home");
  const [route, setRoute] = useState<Route | null>(null);
  const [error, setError] = useState("");
  const [la, setLa] = useState(1);
  const [lb, setLb] = useState(3);

  useEffect(() => {
    setRoute(null);
    setError("");
    api.route(id, title, author).then(setRoute).catch((e) => setError((e as Error).message));
  }, [id, title, author]);

  const plan = route ? meetPlan(route, la, lb) : null;
  const open = (s: Stop) => navigate("book", { id, title, author, stop: s.book.id });

  const Column = ({ name, stops, hours }: { name: string; stops: Stop[]; hours: number }) => (
    <section className="meet-col" aria-label={name}>
      <h2 className="meet-h">{name} <span className="hint">{stops.length} {stops.length === 1 ? "book" : "books"} · {hours} h</span></h2>
      {stops.length === 0 && <p className="hint">Nothing to read first. Ready to go.</p>}
      <ul className="meet-list">
        {stops.map((s) => (
          <li key={s.book.id}>
            <button type="button" className="stop-card" onClick={() => open(s)}>
              <Cover book={s.book} size="s" />
              <span className="stop-main">
                {plan!.shared.includes(s.book.id) && <span className="meet-badge">You both read this</span>}
                <strong className="stop-title">{s.book.title}</strong>
                <span className="stop-why">{s.why}</span>
                <ReadinessMeter level={s.readiness.level} hours={s.readiness.hours} compact />
              </span>
              <span className="chev" aria-hidden="true">›</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );

  return (
    <main className="screen meet-screen">
      <TopBar onBack={goBack} title="Read it with someone" />
      <p className="hint">Two readers, two reading paths, one book to talk about.</p>
      <div className="meet-pickers">
        <Picker label="Reader 1" level={la} onChange={setLa} />
        <Picker label="Reader 2" level={lb} onChange={setLb} />
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {!route && !error && <p className="hint">Working out both paths…</p>}
      {plan && (
        <>
          <p className="meet-summary" aria-live="polite">{meetSummary(plan)}</p>
          <div className="meet-cols">
            <Column name="Reader 1" stops={plan.a} hours={plan.hoursA} />
            <Column name="Reader 2" stops={plan.b} hours={plan.hoursB} />
          </div>
          {plan.target && (
            <button type="button" className="stop-card meet-target" onClick={() => open(plan.target!)}>
              <Cover book={plan.target.book} size="s" />
              <span className="stop-main">
                <strong className="stop-title">You meet at {plan.target.book.title}</strong>
                <span className="stop-why">{plan.target.book.author}</span>
              </span>
              <span className="chev" aria-hidden="true">›</span>
            </button>
          )}
          <p className="hint demo-foot">Not an NLB product.</p>
        </>
      )}
    </main>
  );
}
