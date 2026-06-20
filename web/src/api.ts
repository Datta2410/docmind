export type Me = { id: number; email: string; name: string; avatar_url: string | null }

export async function fetchMe(): Promise<Me | null> {
  const res = await fetch("/api/me")
  if (res.status === 401) return null
  if (!res.ok) throw new Error("failed to load session")
  return res.json()
}
