/** Minimal page frame. The design-system bead replaces this with the real shell. */
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-5xl px-6 py-12">
      <main data-testid="app-shell">{children}</main>
    </div>
  );
}
