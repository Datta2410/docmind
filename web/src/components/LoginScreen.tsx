const PROVIDERS = [
  { id: "google", label: "Continue with Google" },
  { id: "github", label: "Continue with GitHub" },
  { id: "twitter", label: "Continue with Twitter" },
]

export function LoginScreen() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-6 bg-slate-50">
      <h1 className="text-3xl font-semibold">YDG DocMind</h1>
      <p className="text-slate-500">Chat with any document. Tables, charts and all.</p>
      <div className="flex flex-col gap-3 w-72">
        {PROVIDERS.map((p) => (
          <a key={p.id} href={`/api/auth/${p.id}/login`}
             className="rounded-lg border px-4 py-2 text-center hover:bg-slate-100">
            {p.label}
          </a>
        ))}
      </div>
    </div>
  )
}
