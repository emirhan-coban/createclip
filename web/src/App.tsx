import { BrowserRouter, Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { MotionConfig } from "motion/react";
import { Wordmark } from "./components/Wordmark";
import Home from "./pages/Home";
import Panel from "./pages/Panel";
import Editor from "./pages/Editor";

function Bar() {
  const l = ({ isActive }: { isActive: boolean }) => `rounded-full px-4 py-2 text-[0.95rem] transition ${isActive ? "font-semibold" : "text-ink-2 hover:text-ink"}`;
  return (
    <header className="sticky top-0 z-40 border-b border-line/70 bg-paper/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
        <Link to="/" aria-label="Kliparya ana sayfa"><Wordmark /></Link>
        <nav className="flex items-center gap-1" aria-label="Ana menü">
          <NavLink to="/" end className={l}>Yeni klip</NavLink>
          <NavLink to="/panel" className={l}>Panel</NavLink>
        </nav>
      </div>
    </header>
  );
}

function Chrome() {
  return useLocation().pathname.startsWith("/editor") ? null : <Bar />;     // the editor uses the whole screen
}

export default function App() {
  return (
    <MotionConfig reducedMotion="user">
      <BrowserRouter>
        <Chrome />
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/panel/*" element={<Panel />} />
          <Route path="/editor/:id" element={<Editor />} />
        </Routes>
      </BrowserRouter>
    </MotionConfig>
  );
}
