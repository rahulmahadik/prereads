import { useEffect, useState } from "react";
import { useLocation } from "./router";
import Home from "./screens/Home";
import Ready from "./screens/Ready";
import Line from "./screens/Line";
import Book from "./screens/Book";
import ChatPanel from "./components/ChatPanel";

export default function App() {
  const loc = useLocation();
  const [senior, setSenior] = useState(() => localStorage.getItem("prereads.senior") === "1");

  useEffect(() => {
    document.documentElement.classList.toggle("senior", senior);
    localStorage.setItem("prereads.senior", senior ? "1" : "0");
  }, [senior]);

  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [loc.screen, loc.params.stop]);

  const p = loc.params;
  const common = { id: p.id ?? "", title: p.title ?? "", author: p.author ?? "" };

  let screen = <Home senior={senior} onSenior={() => setSenior((v) => !v)} />;
  if (loc.screen === "ready" && p.id) screen = <Ready {...common} />;
  else if (loc.screen === "line" && p.id) screen = <Line {...common} />;
  else if (loc.screen === "book" && p.id && p.stop) screen = <Book {...common} stopId={p.stop} />;
  return (
    <>
      {screen}
      <ChatPanel />
    </>
  );
}
