import { createClient } from "@/lib/supabase/server";
import { Sidebar } from "@/components/layout/sidebar";
import { CopilotClient } from "@/components/copilot/copilot-client";
import { redirect } from "next/navigation";

export const metadata = { title: "AI Career Copilot" };

export default async function CopilotPage() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/auth/login");

  return (
    <div className="flex">
      <Sidebar />
      <main className="ml-56 flex-1 min-h-screen p-6">
        <CopilotClient />
      </main>
    </div>
  );
}
