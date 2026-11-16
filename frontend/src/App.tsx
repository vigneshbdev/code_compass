// Application shell (task T028): sidebar | main | drawer. Story features plug into these areas.
import { HealthBanner, isBlocking } from "./components/HealthBanner";
import { useHealth } from "./api/queries";
import { useTheme } from "./hooks/useTheme";

export function App() {
  const { theme, toggle } = useTheme();
  const health = useHealth();
  const blocked = health.data ? isBlocking(health.data) : false;

  return (
    <div className="flex h-screen flex-col bg-white text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-2 dark:border-slate-800">
        <h1 className="text-base font-semibold">CodeCompass</h1>
        <button
          type="button"
          onClick={toggle}
          className="rounded px-2 py-1 text-sm hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:hover:bg-slate-800"
          aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          {theme === "dark" ? "☀︎ Light" : "☾ Dark"}
        </button>
      </header>
      {health.data && <HealthBanner health={health.data} />}
      {health.isError && (
        <div role="alert" className="bg-red-50 px-4 py-2 text-sm text-red-900 dark:bg-red-950 dark:text-red-100">
          The CodeCompass server is not responding.
        </div>
      )}
      <div className="flex min-h-0 flex-1" aria-hidden={blocked || undefined}>
        <nav aria-label="Codebases and conversations" className="w-72 shrink-0 overflow-y-auto border-r border-slate-200 p-3 dark:border-slate-800" />
        <main className="min-w-0 flex-1 overflow-y-auto p-4" />
        <aside aria-label="Details" className="hidden" />
      </div>
    </div>
  );
}
