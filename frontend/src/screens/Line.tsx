import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import Cover from "../components/Cover";
import ReadinessMeter from "../components/ReadinessMeter";
import ListenButton from "../components/ListenButton";
import NearestLibraries from "../components/NearestLibraries";
import { lineScript } from "../speech";
import { sameShelfGroups, sameShelfText } from "../shelf";
import { ShareCard } from "../components/Extras";
import { AvailToggle, FAMILIARITY, Sheet, TopBar, getBranch, getOnlyAvailable, getReaderLevel, setBranch, setOnlyAvailable, setReaderLevel, shelfStatus, shortBranch, useBack, useReadSet } from "../components/ui";
import { navigate } from "../router";
import HeartButton from "../components/HeartButton";
import { getNote, recordPath, useStoreVersion } from "../myshelf";
import type { Branch, Route, Stop } from "../types";

function statusText(st: ReturnType<typeof shelfStatus>): { text: string; cls: string } {
  switch (st.kind) {
    case "available":
      return { text: `Available at ${shortBranch(st.branch)}`, cls: "ok" };
    case "elsewhere":
      return { text: `Not at ${shortBranch(st.here)} — nearest at ${shortBranch(st.branch)}`, cls: "alt" };
    case "waiting":
      return { text: "All out — join the waiting list", cls: "no" };
    default:
      return { text: "No copies listed — try the eBook", cls: "no" };
  }
}

export default function Line({ id, title, author }: { id: string; title: string; author: string }) {
  const goBack = useBack("home");
  const [route, setRoute] = useState<Route | null>(null);
  const [error, setError] = useState("");
  const [readSet, toggleRead] = useReadSet();
  const [walk, setWalk] = useState(false);
  const [share, setShare] = useState(false);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [branch, setBranchState] = useState(getBranch());
  const [level, setLevel] = useState(getReaderLevel());
  const [fam, setFam] = useState(false);
  const [onlyAvail, setOnlyAvailState] = useState(getOnlyAvailable());
  const flipAvail = (v: boolean) => {
    setOnlyAvailable(v);
    setOnlyAvailState(v);
  };
  const isAvail = (s: Stop) => shelfStatus(s, branch || undefined).kind === "available";
  const chooseBranch = (code: string) => {
    setBranch(code);
    setBranchState(code);
  };
  const chooseLevel = (l: number) => {
    setReaderLevel(l);
    setLevel(l);
    setFam(false);
  };

  useEffect(() => {
    setRoute(null);
    setError("");
    api
      .route(id, title, author)
      .then((r) => {
        setRoute(r);
        recordPath(r, title, author);
      })
      .catch((e) => setError((e as Error).message));
  }, [id, title, author]);
  useStoreVersion();

  useEffect(() => {
    api.branches().then((r) => setBranches(r.branches)).catch(() => setBranches([]));
  }, []);

  const stops = route?.stops ?? [];
  const target = stops.find((s) => s.role === "target");
  const before = stops.filter((s) => s.role === "before");
  const visibleBefore = before.filter((s) => s.readiness.level >= level);
  const skipped = before.length - visibleBefore.length;
  const after = stops.filter((s) => s.role === "after");
  const shownBefore = onlyAvail ? visibleBefore.filter(isAvail) : visibleBefore;
  const shownAfter = onlyAvail ? after.filter(isAvail) : after;
  const hiddenCount = onlyAvail ? visibleBefore.length - shownBefore.length + (after.length - shownAfter.length) : 0;
  const doneBefore = visibleBefore.filter((s) => readSet.has(s.book.id)).length;
  const firstTodo = visibleBefore.find((s) => !readSet.has(s.book.id));
  const hoursLeft = visibleBefore.filter((s) => !readSet.has(s.book.id)).reduce((a, s) => a + s.readiness.hours, 0);

  const here = useMemo(() => {
    if (!branch) return [];
    const name = branches.find((b) => b.code === branch)?.name;
    return stops
      .map((s) => ({ s, a: s.availability.find((a) => a.branch_code === branch || a.branch === name) }))
      .filter((x) => x.a && x.a.available > 0)
      .sort((x, y) => (x.a!.call_number || "").localeCompare(y.a!.call_number || ""));
  }, [branch, stops, branches]);

  const trip = useMemo(() => {
    const name = branches.find((b) => b.code === branch)?.name;
    const visible = new Set(visibleBefore.map((s) => s.book.id));
    return sameShelfGroups(stops.filter((s) => visible.has(s.book.id)), branch, name, readSet)[0];
  }, [branch, branches, stops, level, readSet]);

  const open = (s: Stop) => navigate("book", { id, title, author, stop: s.book.id });

  const Row = ({ s, kind }: { s: Stop; kind: "before" | "target" | "after" }) => {
    const where = statusText(shelfStatus(s, branch || undefined));
    const read = readSet.has(s.book.id);
    const isStart = firstTodo?.book.id === s.book.id;
    return (
      <li className={`stop-row ${kind} ${read ? "read" : ""}`}>
        {kind === "target" ? (
          <span className="node target" aria-hidden="true" />
        ) : (
          <button
            type="button"
            className="node-btn"
            onClick={() => toggleRead(s.book.id)}
            aria-pressed={read}
            aria-label={read ? `Mark ${s.book.title} as not read` : `Mark ${s.book.title} as read`}
          >
            <span className={`node ${kind}`} aria-hidden="true">
              {read ? "✓" : ""}
            </span>
          </button>
        )}
        <button type="button" className="stop-card" onClick={() => open(s)} aria-label={`${s.book.title}, level ${s.readiness.level}, ${where.text}`}>
          <Cover book={s.book} size="s" />
          <span className="stop-main">
            <span className="stop-kicker">{kind === "target" ? "Your book" : kind === "before" ? (isStart ? "Start here · PreRead" : "PreRead") : "NextRead"}</span>
            <strong className="stop-title">{s.book.title}</strong>
            <span className="stop-why">{kind === "target" ? s.readiness.one_line || s.why : s.why}</span>
            <ReadinessMeter level={s.readiness.level} hours={s.readiness.hours} compact />
            <span className={`where ${where.cls}`}>{where.text}</span>
            {getNote(s.book.id) && <span className="note-chip">📝 Note</span>}
          </span>
          <span className="chev" aria-hidden="true">
            ›
          </span>
        </button>
        <HeartButton className="row-heart" book={{ id: s.book.id, title: s.book.title, author: s.book.author, lineId: id, lineTitle: title, lineAuthor: author }} />
      </li>
    );
  };

  return (
    <main className="screen line-screen">
      <TopBar
        onBack={goBack}
        title="Your reading path"
        right={
          route && (
            <button type="button" className="icon-btn" onClick={() => setShare(true)} aria-label="Share this path">
              ↗
            </button>
          )
        }
      />

      {!route && !error && (
        <div className="skeleton" role="status" aria-label="Drawing the reading path">
          <div className="sk-book">
            <div className="sk-cover" />
            <div className="sk-lines">
              <span />
              <span />
              <span />
            </div>
          </div>
          <div className="sk-line" style={{ marginTop: 20 }} />
          <div className="sk-line" style={{ marginTop: 14, width: "70%" }} />
        </div>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {route && target && (
        <div className="line-grid">
          <section className="line-summary">
            {visibleBefore.length === 0 ? (
              <p className="summary-main">
                You can start <strong>{target.book.title}</strong> today. Nothing needs to come first.
              </p>
            ) : (
              <p className="summary-main">
                <strong>{visibleBefore.length - doneBefore}</strong> {visibleBefore.length - doneBefore === 1 ? "book" : "books"} before{" "}
                <strong>{target.book.title}</strong> · about {Math.round(hoursLeft)} h of reading
              </p>
            )}
            {skipped > 0 && <p className="hint">Skipped {skipped} easier {skipped === 1 ? "book" : "books"} because you know the topic a bit.</p>}
            {visibleBefore.length > 0 && <p className="hint">Tap a circle when you've finished that book.</p>}
            {trip && (
              <p className="trip-note" role="note">
                <strong>{sameShelfText(trip)}</strong>
                <span>{trip.stops.map((s) => s.book.title).join(" · ")}</span>
              </p>
            )}
            <div className="line-actions">
              <ListenButton
                id={`line:${route.target_id}`}
                label="Listen to the path"
                text={() =>
                  lineScript({
                    target: target.book.title,
                    hours: hoursLeft,
                    trip: trip ? sameShelfText(trip) : undefined,
                    before: visibleBefore.filter((s) => !readSet.has(s.book.id)).map((s) => ({ title: s.book.title, why: s.why, hours: s.readiness.hours, where: statusText(shelfStatus(s, branch || undefined)).text })),
                  })
                }
              />
              <button type="button" className="chip-btn" onClick={() => setFam(true)} aria-haspopup="dialog">
                <span className="chip-k">You</span> {FAMILIARITY.find((f) => f.level === level)?.title ?? "New to this"} ▾
              </button>
              <button type="button" className="chip-btn" onClick={() => setWalk(true)} aria-haspopup="dialog">
                <span className="chip-k">At</span> {branch ? shortBranch(branches.find((b) => b.code === branch)?.name ?? branch) : "any library"} ▾
              </button>
              <AvailToggle on={onlyAvail} onChange={flipAvail} label={branch ? "Only on the shelf here" : "Only available now"} />
            </div>
            {hiddenCount > 0 && (
              <p className="hint hidden-note">
                Hiding {hiddenCount} {hiddenCount === 1 ? "book that isn't" : "books that aren't"} available right now.{" "}
                <button type="button" className="link-btn inline" onClick={() => flipAvail(false)}>Show them too</button>
              </p>
            )}
          </section>

          <div className="line-main">
          <ol className="route">
            {shownBefore.map((s) => (
              <Row key={s.book.id} s={s} kind="before" />
            ))}
            <Row s={target} kind="target" />
            {shownAfter.map((s) => (
              <Row key={s.book.id} s={s} kind="after" />
            ))}
          </ol>

          {route.notes.length > 0 && (
            <details className="section">
              <summary className="hint">Why some books were left off ({route.notes.length})</summary>
              <ul className="hint">
                {route.notes.map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            </details>
          )}
          <p className="hint demo-foot">{stops.some((s) => s.availability.some((a) => a.demo)) ? "Shelf data is demo data until the NLB key is connected. " : ""}Not an NLB product.</p>
          </div>

          <Sheet open={walk} title="Which library are you in?" onClose={() => setWalk(false)}>
            <NearestLibraries branches={branches} onPick={chooseBranch} />
            <select className="select" aria-label="Library" value={branch} onChange={(e) => chooseBranch(e.target.value)}>
              <option value="">Any library</option>
              {branches.map((b) => (
                <option key={b.code} value={b.code}>
                  {b.name}
                </option>
              ))}
            </select>
            {branch && (
              <ol className="walk-list">
                {here.length === 0 && <li className="hint">None of this path is on the shelf here right now.</li>}
                {here.map(({ s, a }) => (
                  <li key={s.book.id}>
                    <button type="button" className="walk-item" onClick={() => open(s)}>
                      <strong>{s.book.title}</strong>
                      <span className="call">{a!.call_number || "ask staff for the shelf"} · directions ›</span>
                    </button>
                  </li>
                ))}
              </ol>
            )}
            {branch && here.length > 0 && <p className="hint">Sorted by call number, so you can walk the shelves in order.</p>}
          </Sheet>

          <Sheet open={share} title="Share this path" onClose={() => setShare(false)}>
            <ShareCard route={route} />
          </Sheet>

          <Sheet open={fam} title="How familiar are you with this topic?" onClose={() => setFam(false)}>
            <div className="choices">
              {FAMILIARITY.map((c) => (
                <button key={c.level} type="button" className={`choice ${c.level === level ? "on" : ""}`} onClick={() => chooseLevel(c.level)}>
                  <strong>{c.title}</strong>
                  <span>{c.sub}</span>
                </button>
              ))}
            </div>
          </Sheet>
        </div>
      )}
    </main>
  );
}
