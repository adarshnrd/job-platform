import { createClient } from "@/lib/supabase/server";
import { Sidebar } from "@/components/layout/sidebar";
import { ApproveClient } from "@/components/approve/approve-client";
import { redirect } from "next/navigation";

export const metadata = { title: "Approve Jobs — JobPlatform AI" };

export default async function ApprovePage() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/auth/login");

  return (
    <div className="flex">
      <Sidebar />
      <main className="ml-56 flex-1 min-h-screen p-6">
        <ApproveClient />
      </main>
    </div>
  );
}
