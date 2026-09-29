import { AppShell } from "./components/AppShell";
import { Sidebar } from "./components/Sidebar";
import { useDocumentPolling } from "./hooks/useDocumentPolling";

export default function App() {
  useDocumentPolling();
  return (
    <div className="flex h-full overflow-hidden">
      <Sidebar />
      <AppShell />
    </div>
  );
}
