import { createClient } from "@/lib/supabase/server";
import { Sidebar } from "@/components/layout/sidebar";
import { AnswersClient } from "@/components/answers/answers-client";
import { redirect } from "next/navigation";

export default async function AnswersPage() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/auth/login");
  return (
    <div className="flex">
      <Sidebar />
      <main className="ml-56 flex-1 min-h-screen p-6">
        <AnswersClient />
      </main>
    </div>
  );
}
