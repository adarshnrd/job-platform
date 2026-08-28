import { createClient } from "@/lib/supabase/server";
import { Sidebar } from "@/components/layout/sidebar";
import { ApplicationsClient } from "@/components/applications/applications-client";
import { redirect } from "next/navigation";

export default async function ApplicationsPage() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/auth/login");
  return (
    <div className="flex">
      <Sidebar />
      <main className="ml-56 flex-1 min-h-screen p-6">
        <ApplicationsClient userId={user.id} />
      </main>
    </div>
  );
}
