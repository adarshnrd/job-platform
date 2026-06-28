"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import {
  LayoutDashboard, Briefcase, FileText, BookOpen,
  BarChart3, Settings, LogOut, CheckCircle, Bot, KeyRound, Bell,
} from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useRouter } from "next/navigation";

const NAV = [
  { href: "/dashboard",    icon: LayoutDashboard, label: "Pipeline" },
  { href: "/jobs",         icon: Briefcase,        label: "Jobs" },
  { href: "/applications", icon: BarChart3,        label: "Applications" },
  { href: "/approve",      icon: CheckCircle,      label: "Approve Jobs" },
  { href: "/copilot",      icon: Bot,              label: "AI Copilot",  badge: "AI" },
  { href: "/resume",       icon: FileText,         label: "Resume" },
  { href: "/interview",    icon: BookOpen,         label: "Interview Prep" },
  { href: "/analytics",    icon: Bell,             label: "Analytics" },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const supabase = createClient();

  const signOut = async () => {
    await supabase.auth.signOut();
    router.push("/auth/login");
  };

  return (
    <aside className="w-56 min-h-screen bg-zinc-950 border-r border-zinc-800/60 flex flex-col fixed left-0 top-0">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-zinc-800/60">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 bg-amber-500 rounded-lg flex items-center justify-center text-black font-bold text-sm">⚡</div>
          <span className="font-bold text-sm tracking-tight">JobPlatform AI</span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {NAV.map(({ href, icon: Icon, label, badge }: any) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link key={href} href={href}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors",
                active
                  ? "bg-amber-500/10 text-amber-400 font-medium"
                  : "text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/60"
              )}>
              <Icon size={16} className={active ? "text-amber-400" : ""} />
              <span className="flex-1">{label}</span>
              {badge && (
                <span className="text-[9px] font-black bg-amber-500 text-black px-1.5 py-0.5 rounded-full">
                  {badge}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* Bottom */}
      <div className="px-3 py-4 border-t border-zinc-800/60 space-y-0.5">
        <Link href="/settings"
          className={cn("flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors",
            pathname === "/settings" ? "bg-amber-500/10 text-amber-400" : "text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/60")}>
          <Settings size={16} />
          Settings
        </Link>
        <button onClick={signOut}
          className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-zinc-400 hover:text-red-400 hover:bg-zinc-800/60 transition-colors">
          <LogOut size={16} />
          Sign Out
        </button>
      </div>
    </aside>
  );
}
