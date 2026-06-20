type User = { name: string; avatar_url: string | null }

export function AppShell({ user }: { user: User }) {
  return (
    <div className="min-h-screen">
      <header className="flex items-center justify-between border-b px-6 py-3">
        <span className="font-semibold">YDG DocMind</span>
        <div className="flex items-center gap-3">
          {user.avatar_url && (
            <img src={user.avatar_url} alt="" className="h-8 w-8 rounded-full" />
          )}
          <span>{user.name}</span>
          <button
            onClick={async () => {
              await fetch("/api/auth/logout", { method: "POST" })
              window.location.reload()
            }}
            className="text-sm text-slate-500 hover:underline">
            Sign out
          </button>
        </div>
      </header>
      <main className="p-8">
        <div className="rounded-xl border border-dashed p-12 text-center text-slate-400">
          No knowledge bases yet. (Creation arrives in Phase 2.)
        </div>
      </main>
    </div>
  )
}
