import Cover from "../components/Cover";
import { FAMILIARITY, TopBar, setReaderLevel, useBack } from "../components/ui";
import { navigate } from "../router";

const CHOICES = FAMILIARITY;

export default function Ready({ id, title, author }: { id: string; title: string; author: string }) {
  const goBack = useBack("home");
  const pick = (level: number) => {
    setReaderLevel(level);
    navigate("line", { id, title, author }, true);
  };
  return (
    <main className="screen ready">
      <TopBar onBack={goBack} title="One quick question" />
      <div className="ready-book">
        <Cover book={{ id, title, author, subjects: [], summary: "", source: "seed" }} size="m" />
        <div>
          <p className="hint">You picked</p>
          <h2 className="ready-title">{title}</h2>
          <p className="by">{author}</p>
        </div>
      </div>
      <h3 className="ready-q">How familiar are you with this topic?</h3>
      <div className="choices">
        {CHOICES.map((c) => (
          <button key={c.level} type="button" className="choice" onClick={() => pick(c.level)}>
            <strong>{c.title}</strong>
            <span>{c.sub}</span>
          </button>
        ))}
      </div>
      <button type="button" className="link-btn" onClick={() => pick(1)}>
        Skip, show me everything
      </button>
    </main>
  );
}
