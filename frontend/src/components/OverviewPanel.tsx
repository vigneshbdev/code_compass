// Codebase overview (FR-020, task T149): language breakdown and declared dependencies.
import type { Overview } from "../api/client";

export function OverviewPanel({ overview }: { overview: Overview }) {
  const totalFiles = overview.languages.reduce((n, l) => n + l.files, 0) || 1;
  const byManifest = overview.dependencies.reduce<Record<string, Overview["dependencies"]>>((acc, d) => {
    (acc[d.manifest] ??= []).push(d);
    return acc;
  }, {});
  return (
    <section aria-label="Overview" className="grid gap-4 text-sm md:grid-cols-2">
      <div>
        <h3 className="mb-2 font-semibold">Languages</h3>
        <div className="mb-2 flex h-2 overflow-hidden rounded" aria-hidden="true">
          {overview.languages.map((l, i) => (
            <div
              key={l.language}
              style={{ width: `${(l.files / totalFiles) * 100}%` }}
              className={["bg-sky-600", "bg-emerald-600", "bg-amber-500", "bg-violet-500", "bg-slate-400"][i % 5]}
            />
          ))}
        </div>
        <table className="w-full text-xs">
          <thead className="text-left text-slate-500">
            <tr>
              <th className="font-normal">Language</th>
              <th className="font-normal">Files</th>
              <th className="font-normal">Lines</th>
            </tr>
          </thead>
          <tbody>
            {overview.languages.slice(0, 8).map((l) => (
              <tr key={l.language}>
                <td>{l.language}</td>
                <td>{l.files}</td>
                <td>{l.lines.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <h3 className="mb-2 font-semibold">Dependencies</h3>
        {overview.dependencies.length === 0 && <p className="text-xs text-slate-500">No manifests found.</p>}
        <div className="max-h-48 space-y-2 overflow-y-auto">
          {Object.entries(byManifest).map(([manifest, deps]) => (
            <div key={manifest}>
              <p className="font-mono text-xs text-slate-500">{manifest}</p>
              <ul className="flex flex-wrap gap-1">
                {deps.map((d) => (
                  <li
                    key={`${d.name}-${d.dev}`}
                    title={d.spec || undefined}
                    className={`rounded px-1.5 text-xs ${d.dev ? "bg-slate-100 text-slate-500 dark:bg-slate-800" : "bg-sky-50 dark:bg-sky-950"}`}
                  >
                    {d.name}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
