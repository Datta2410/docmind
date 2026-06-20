import { useMe } from "./auth"
import { LoginScreen } from "./components/LoginScreen"
import { AppShell } from "./components/AppShell"

export default function App() {
  const { data: me, isLoading } = useMe()
  if (isLoading) return <div className="p-8 text-slate-400">Loading…</div>
  if (!me) return <LoginScreen />
  return <AppShell user={me} />
}
