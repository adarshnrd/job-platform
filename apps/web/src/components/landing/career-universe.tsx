"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import { motion, useInView } from "framer-motion";

// ── Data ─────────────────────────────────────────────────────

interface CareerSector {
  name: string;
  icon: string;
  glowHex: string;
  roles: string[];
  avgSalary: string;
  companies: string[];
  tagline: string;
}

const SECTORS: CareerSector[] = [
  {
    name: "AI & Machine Learning",
    icon: "🤖",
    glowHex: "#6366f1",
    roles: ["ML Engineer", "AI Researcher", "Data Scientist", "LLM Engineer"],
    avgSalary: "₹18 – 45 LPA",
    companies: ["Google DeepMind", "OpenAI", "Anthropic", "Microsoft"],
    tagline: "The frontier of intelligence. Build systems that think, reason, and create.",
  },
  {
    name: "Software Engineering",
    icon: "⚡",
    glowHex: "#3b82f6",
    roles: ["Full Stack Dev", "Backend Engineer", "Platform Engineer", "DevOps"],
    avgSalary: "₹12 – 38 LPA",
    companies: ["Atlassian", "GitHub", "Stripe", "Vercel"],
    tagline: "The backbone of digital civilization. Build products used by billions.",
  },
  {
    name: "Healthcare Tech",
    icon: "🏥",
    glowHex: "#10b981",
    roles: ["Health Data Engineer", "Clinical Informaticist", "Biotech Developer"],
    avgSalary: "₹10 – 28 LPA",
    companies: ["Practo", "Philips Digital", "Siemens Healthineers", "1mg"],
    tagline: "Technology meeting humanity. Solve problems that save lives.",
  },
  {
    name: "Finance & Fintech",
    icon: "💎",
    glowHex: "#f59e0b",
    roles: ["Quant Analyst", "Risk Engineer", "Fintech Developer", "Blockchain Dev"],
    avgSalary: "₹14 – 42 LPA",
    companies: ["Zerodha", "Razorpay", "CRED", "Goldman Sachs India"],
    tagline: "Where mathematics meets money. Shape the global financial system.",
  },
  {
    name: "Design & Product",
    icon: "🎨",
    glowHex: "#ec4899",
    roles: ["UX Designer", "Product Designer", "Design Engineer", "Motion Designer"],
    avgSalary: "₹8 – 24 LPA",
    companies: ["Figma", "Adobe", "InVision", "Notion"],
    tagline: "Craft experiences people love. Design is the soul of every great product.",
  },
  {
    name: "Marketing & Growth",
    icon: "📈",
    glowHex: "#f97316",
    roles: ["Growth Hacker", "Brand Strategist", "Performance Marketer", "SEO Lead"],
    avgSalary: "₹6 – 22 LPA",
    companies: ["HubSpot", "Salesforce", "Zomato", "Swiggy"],
    tagline: "Grow audiences, grow revenue, grow brands. Marketing is art and science.",
  },
  {
    name: "Remote & Global",
    icon: "🌍",
    glowHex: "#06b6d4",
    roles: ["Remote Engineer", "Digital Nomad", "Consultant", "Distributed Team Lead"],
    avgSalary: "₹15 – 55 LPA",
    companies: ["Toptal", "Remote.com", "Deel", "Arc.dev"],
    tagline: "Work from anywhere. The global talent marketplace awaits.",
  },
];

const FEATURES = [
  { icon: "🎯", title: "AI Match Scoring", desc: "Every role gets a 0–100 compatibility score based on your skills, experience, and career trajectory.", color: "#6366f1" },
  { icon: "⚡", title: "Auto-Apply Engine", desc: "Jobs scoring 80%+ are applied to automatically. Your AI agent fills forms, uploads resumes, and submits.", color: "#f59e0b" },
  { icon: "✍️", title: "AI Cover Letters", desc: "Role-specific cover letters crafted in your voice, highlighting the exact skills each job demands.", color: "#ec4899" },
  { icon: "🔍", title: "Multi-Platform Discovery", desc: "Scrapers search LinkedIn, Naukri, Indeed, Wellfound, and 8 more platforms every 4 hours.", color: "#06b6d4" },
  { icon: "📋", title: "Approval Queue", desc: "Borderline matches (60–79%) land in your queue for one-click approval or dismissal.", color: "#10b981" },
  { icon: "🎤", title: "Interview Intelligence", desc: "AI-generated questions, STAR behavioral answers, salary strategy, and automated follow-ups.", color: "#3b82f6" },
];

const STEPS = [
  { num: "01", title: "Upload Resume", desc: "AI parses your skills, experience, and goals in seconds.", color: "#3b82f6" },
  { num: "02", title: "AI Discovers Jobs", desc: "Scrapers search 10+ platforms every 4 hours for matching roles.", color: "#8b5cf6" },
  { num: "03", title: "Smart Scoring", desc: "Each role gets a 0–100 match score against your unique profile.", color: "#f59e0b" },
  { num: "04", title: "Auto-Apply", desc: "The bot fills forms, answers questions, and submits applications.", color: "#10b981" },
  { num: "05", title: "Track & Interview", desc: "Monitor applications, prep with AI, and land your dream role.", color: "#ec4899" },
];

// ── Animation helpers ────────────────────────────────────────

const fadeUp = {
  hidden: { opacity: 0, y: 30 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.1, duration: 0.6, ease: [0.16, 1, 0.3, 1] },
  }),
};

function AnimatedCounter({ value, suffix = "" }: { value: string; suffix?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-50px" });
  const [display, setDisplay] = useState("0");

  useEffect(() => {
    if (!inView) return;
    const num = parseInt(value.replace(/\D/g, ""), 10);
    if (isNaN(num)) { setDisplay(value); return; }
    const duration = 2000;
    const start = performance.now();
    const tick = (now: number) => {
      const p = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 4);
      setDisplay(Math.floor(eased * num).toLocaleString());
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }, [inView, value]);

  return <span ref={ref}>{display}{suffix}</span>;
}

// ── Feature card with hover tilt ─────────────────────────────

function FeatureCard({ feature, index }: { feature: (typeof FEATURES)[0]; index: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [mouse, setMouse] = useState({ x: 0.5, y: 0.5 });

  const handleMove = useCallback((e: React.MouseEvent) => {
    if (!ref.current) return;
    const r = ref.current.getBoundingClientRect();
    setMouse({ x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height });
  }, []);

  return (
    <motion.div
      ref={ref}
      custom={index}
      variants={fadeUp}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-40px" }}
      onMouseMove={handleMove}
      onMouseLeave={() => setMouse({ x: 0.5, y: 0.5 })}
      className="group relative rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6 transition-colors duration-300 hover:border-white/[0.12] hover:bg-white/[0.04]"
      style={{
        transform: `perspective(800px) rotateX(${(0.5 - mouse.y) * 5}deg) rotateY(${(mouse.x - 0.5) * 5}deg)`,
      }}
    >
      <div
        className="absolute inset-0 rounded-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none"
        style={{ background: `radial-gradient(circle at ${mouse.x * 100}% ${mouse.y * 100}%, ${feature.color}10 0%, transparent 60%)` }}
      />
      <div className="relative z-10">
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center text-lg mb-4"
          style={{ background: `${feature.color}12`, border: `1px solid ${feature.color}20` }}
        >
          {feature.icon}
        </div>
        <h3 className="text-base font-semibold text-white mb-2">{feature.title}</h3>
        <p className="text-sm text-zinc-400 leading-relaxed">{feature.desc}</p>
      </div>
    </motion.div>
  );
}

// ── Main Component ───────────────────────────────────────────

export function CareerUniverseClient() {
  const [selectedSector, setSelectedSector] = useState<CareerSector | null>(null);

  return (
    <main className="relative bg-[#030308] overflow-x-hidden">

      {/* ── Ambient background ── */}
      <div className="fixed inset-0 pointer-events-none z-0">
        <div className="absolute top-[-20%] left-1/2 -translate-x-1/2 w-[800px] h-[800px] rounded-full opacity-[0.04]"
          style={{ background: "radial-gradient(circle, #6366f1 0%, transparent 70%)" }} />
        <div className="absolute top-[40%] right-[-10%] w-[600px] h-[600px] rounded-full opacity-[0.03]"
          style={{ background: "radial-gradient(circle, #f59e0b 0%, transparent 70%)" }} />
        <div className="absolute bottom-[-10%] left-[-10%] w-[700px] h-[700px] rounded-full opacity-[0.03]"
          style={{ background: "radial-gradient(circle, #ec4899 0%, transparent 70%)" }} />
      </div>

      {/* ── Nav ── */}
      <nav className="sticky top-0 z-50 border-b border-white/[0.04] bg-[#030308]/80 backdrop-blur-xl">
        <div className="max-w-6xl mx-auto flex items-center justify-between px-6 h-14">
          <span className="font-bold text-sm tracking-tight">
            <span className="text-amber-400">Career</span><span className="text-white/70">OS</span>
          </span>
          <div className="hidden sm:flex items-center gap-6">
            {["Features", "How It Works", "Sectors"].map((l) => (
              <a key={l} href={`#${l.toLowerCase().replace(/ /g, "-")}`} className="text-xs text-zinc-500 hover:text-white transition-colors">{l}</a>
            ))}
          </div>
          <Link href="/auth/login" className="text-xs font-semibold text-black bg-amber-400 hover:bg-amber-300 rounded-lg px-4 py-1.5 transition-colors">
            Sign In
          </Link>
        </div>
      </nav>

      {/* ════════════ HERO ════════════ */}
      <section className="relative z-10 max-w-4xl mx-auto px-6 pt-28 pb-32 text-center">
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7 }}>
          <div className="inline-flex items-center gap-2 border border-white/[0.06] bg-white/[0.02] rounded-full px-4 py-1.5 text-[11px] tracking-widest text-zinc-500 font-mono mb-8">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
            AI-POWERED CAREER AGENT
          </div>
        </motion.div>

        <motion.h1
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15, duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
          className="text-5xl sm:text-7xl lg:text-8xl font-black tracking-[-0.04em] leading-[0.92] mb-7"
        >
          <span className="text-white">Your AI applies</span>
          <br />
          <span className="hero-gradient-text">while you sleep.</span>
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3, duration: 0.7 }}
          className="text-lg text-zinc-400 max-w-xl mx-auto leading-relaxed mb-10"
        >
          CareerOS discovers relevant jobs across 10+ platforms, scores your fit,
          tailors your resume, and auto-submits applications — 24/7.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.45, duration: 0.7 }}
          className="flex flex-wrap gap-3 justify-center mb-14"
        >
          <Link
            href="/auth/login"
            className="px-8 py-3 text-sm font-bold text-black rounded-xl transition-transform hover:scale-[1.03] active:scale-[0.98]"
            style={{ background: "linear-gradient(135deg, #f59e0b, #f97316)", boxShadow: "0 0 30px rgba(245,158,11,0.25)" }}
          >
            Get Started Free
          </Link>
          <a
            href="#features"
            className="px-8 py-3 text-sm font-medium text-zinc-300 rounded-xl border border-white/[0.08] hover:bg-white/[0.04] transition-colors"
          >
            See How It Works
          </a>
        </motion.div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.7, duration: 1 }}
          className="grid grid-cols-3 gap-6 max-w-sm mx-auto border-t border-white/[0.04] pt-8"
        >
          {[
            { v: "500000", s: "+", l: "Live Roles" },
            { v: "10000", s: "+", l: "Companies" },
            { v: "24", s: "/7", l: "Auto-Apply" },
          ].map(({ v, s, l }) => (
            <div key={l} className="text-center">
              <div className="text-2xl font-black text-white font-mono"><AnimatedCounter value={v} suffix={s} /></div>
              <div className="text-[10px] text-zinc-600 mt-1 uppercase tracking-wider">{l}</div>
            </div>
          ))}
        </motion.div>
      </section>

      {/* ════════════ LOGOS / PLATFORMS ════════════ */}
      <section className="relative z-10 border-y border-white/[0.04] py-8">
        <div className="max-w-5xl mx-auto px-6">
          <p className="text-center text-[10px] text-zinc-600 uppercase tracking-[0.25em] mb-5 font-mono">Sources jobs from</p>
          <div className="flex flex-wrap items-center justify-center gap-x-8 gap-y-3">
            {["LinkedIn", "Naukri", "Indeed", "Wellfound", "Glassdoor", "Dice", "RemoteOK", "Instahyre"].map((p) => (
              <span key={p} className="text-sm text-zinc-600 font-medium">{p}</span>
            ))}
          </div>
        </div>
      </section>

      {/* ════════════ FEATURES ════════════ */}
      <section id="features" className="relative z-10 max-w-6xl mx-auto px-6 py-28">
        <div className="text-center mb-14">
          <motion.p variants={fadeUp} custom={0} initial="hidden" whileInView="visible" viewport={{ once: true }}
            className="text-amber-400/60 text-[11px] font-mono tracking-[0.25em] uppercase mb-4">
            Capabilities
          </motion.p>
          <motion.h2 variants={fadeUp} custom={1} initial="hidden" whileInView="visible" viewport={{ once: true }}
            className="text-3xl sm:text-5xl font-black tracking-tight text-white">
            Everything you need, <span className="text-amber-400">automated.</span>
          </motion.h2>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {FEATURES.map((f, i) => <FeatureCard key={f.title} feature={f} index={i} />)}
        </div>
      </section>

      {/* ════════════ HOW IT WORKS ════════════ */}
      <section id="how-it-works" className="relative z-10 max-w-4xl mx-auto px-6 py-28">
        <div className="text-center mb-14">
          <motion.p variants={fadeUp} custom={0} initial="hidden" whileInView="visible" viewport={{ once: true }}
            className="text-pink-400/60 text-[11px] font-mono tracking-[0.25em] uppercase mb-4">
            The Process
          </motion.p>
          <motion.h2 variants={fadeUp} custom={1} initial="hidden" whileInView="visible" viewport={{ once: true }}
            className="text-3xl sm:text-5xl font-black tracking-tight text-white">
            From upload to <span className="text-pink-400">offer letter.</span>
          </motion.h2>
        </div>

        <div className="relative">
          <div className="absolute left-7 sm:left-8 top-0 bottom-0 w-px bg-gradient-to-b from-transparent via-white/[0.06] to-transparent" />
          <div className="space-y-10">
            {STEPS.map((step, i) => (
              <motion.div
                key={step.num}
                custom={i}
                variants={fadeUp}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true, margin: "-40px" }}
                className="relative flex items-start gap-6 group"
              >
                <div
                  className="relative z-10 shrink-0 w-14 h-14 rounded-2xl flex items-center justify-center font-mono font-black text-base border border-white/[0.06] transition-transform duration-300 group-hover:scale-110"
                  style={{ background: `${step.color}10`, color: step.color }}
                >
                  {step.num}
                </div>
                <div className="pt-2.5 flex-1">
                  <h3 className="text-lg font-bold text-white mb-1">{step.title}</h3>
                  <p className="text-sm text-zinc-500 leading-relaxed">{step.desc}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* ════════════ SECTORS ════════════ */}
      <section id="sectors" className="relative z-10 max-w-6xl mx-auto px-6 py-28">
        <div className="text-center mb-14">
          <motion.p variants={fadeUp} custom={0} initial="hidden" whileInView="visible" viewport={{ once: true }}
            className="text-violet-400/60 text-[11px] font-mono tracking-[0.25em] uppercase mb-4">
            Career Sectors
          </motion.p>
          <motion.h2 variants={fadeUp} custom={1} initial="hidden" whileInView="visible" viewport={{ once: true }}
            className="text-3xl sm:text-5xl font-black tracking-tight text-white">
            Seven industries. <span className="text-violet-400">One platform.</span>
          </motion.h2>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {SECTORS.map((s, i) => (
            <motion.button
              key={s.name}
              custom={i}
              variants={fadeUp}
              initial="hidden"
              whileInView="visible"
              viewport={{ once: true }}
              onClick={() => setSelectedSector(s)}
              className="group flex items-center gap-4 rounded-xl border border-white/[0.05] bg-white/[0.02] px-5 py-4 text-left transition-all duration-200 hover:bg-white/[0.05] hover:border-white/[0.1]"
            >
              <div className="w-10 h-10 rounded-lg flex items-center justify-center text-lg shrink-0"
                style={{ background: `${s.glowHex}12` }}>
                {s.icon}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-white">{s.name}</div>
                <div className="text-xs text-zinc-500">{s.avgSalary}</div>
              </div>
              <span className="text-xs opacity-0 group-hover:opacity-100 transition-opacity shrink-0" style={{ color: s.glowHex }}>
                View →
              </span>
            </motion.button>
          ))}
        </div>
      </section>

      {/* ════════════ STATS ════════════ */}
      <section className="relative z-10 border-y border-white/[0.04] py-20">
        <div className="max-w-5xl mx-auto px-6 grid grid-cols-2 lg:grid-cols-4 gap-8">
          {[
            { v: "10", s: "+", l: "Job Platforms", c: "#3b82f6" },
            { v: "500000", s: "+", l: "Roles Indexed", c: "#f59e0b" },
            { v: "24", s: "/7", l: "Auto-Apply", c: "#10b981" },
            { v: "95", s: "%", l: "Match Accuracy", c: "#ec4899" },
          ].map(({ v, s, l, c }, i) => (
            <motion.div key={l} custom={i} variants={fadeUp} initial="hidden" whileInView="visible" viewport={{ once: true }}
              className="text-center">
              <div className="text-4xl sm:text-5xl font-black font-mono mb-1" style={{ color: c }}>
                <AnimatedCounter value={v} suffix={s} />
              </div>
              <div className="text-[10px] text-zinc-600 uppercase tracking-widest">{l}</div>
            </motion.div>
          ))}
        </div>
      </section>

      {/* ════════════ FINAL CTA ════════════ */}
      <section className="relative z-10 max-w-3xl mx-auto px-6 py-32 text-center">
        <motion.h2 variants={fadeUp} custom={0} initial="hidden" whileInView="visible" viewport={{ once: true }}
          className="text-4xl sm:text-6xl font-black tracking-tight mb-6">
          <span className="text-white">Ready to automate</span><br />
          <span className="hero-gradient-text">your job search?</span>
        </motion.h2>
        <motion.p variants={fadeUp} custom={1} initial="hidden" whileInView="visible" viewport={{ once: true }}
          className="text-zinc-400 text-lg max-w-lg mx-auto mb-10">
          Upload your resume once. CareerOS discovers roles, scores matches, and applies — so you can focus on interviews.
        </motion.p>
        <motion.div variants={fadeUp} custom={2} initial="hidden" whileInView="visible" viewport={{ once: true }}>
          <Link
            href="/auth/login"
            className="inline-block px-10 py-4 text-base font-bold text-black rounded-xl transition-transform hover:scale-[1.03] active:scale-[0.98]"
            style={{ background: "linear-gradient(135deg, #6366f1, #ec4899, #f59e0b)", boxShadow: "0 0 50px rgba(99,102,241,0.2), 0 0 100px rgba(236,72,153,0.1)" }}
          >
            Get Started Free →
          </Link>
          <p className="text-xs text-zinc-700 mt-5">Free to start · No credit card required</p>
        </motion.div>
      </section>

      {/* ── Footer ── */}
      <footer className="relative z-10 border-t border-white/[0.04] py-10">
        <div className="max-w-5xl mx-auto px-6 text-center">
          <p className="text-zinc-700 text-xs">© 2024 CareerOS · AI-Powered Career Intelligence</p>
        </div>
      </footer>

      {/* ── Sector Detail Panel ── */}
      {selectedSector && (
        <motion.div
          initial={{ x: "100%" }}
          animate={{ x: 0 }}
          exit={{ x: "100%" }}
          transition={{ type: "spring", damping: 28, stiffness: 220 }}
          className="fixed inset-y-0 right-0 z-[60] w-full max-w-sm"
        >
          <div className="h-full bg-[#0a0a12]/95 backdrop-blur-xl border-l border-white/[0.06] p-8 flex flex-col overflow-y-auto">
            <button
              onClick={() => setSelectedSector(null)}
              className="self-end w-8 h-8 rounded-full border border-white/[0.08] flex items-center justify-center text-zinc-500 hover:text-white hover:bg-white/[0.06] transition-all mb-8 text-sm"
            >
              ✕
            </button>
            <div className="text-4xl mb-4">{selectedSector.icon}</div>
            <h3 className="text-xl font-bold text-white mb-1">{selectedSector.name}</h3>
            <div className="text-sm font-mono mb-3" style={{ color: selectedSector.glowHex }}>{selectedSector.avgSalary}</div>
            <p className="text-zinc-500 text-sm leading-relaxed mb-8">{selectedSector.tagline}</p>

            <div className="space-y-6 flex-1">
              <div>
                <p className="text-zinc-600 text-[10px] uppercase tracking-[0.2em] mb-3 font-mono">Top Roles</p>
                <div className="space-y-2">
                  {selectedSector.roles.map((r) => (
                    <div key={r} className="flex items-center gap-3 bg-white/[0.02] rounded-lg px-4 py-2.5 border border-white/[0.04]">
                      <div className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: selectedSector.glowHex }} />
                      <span className="text-zinc-300 text-sm">{r}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-zinc-600 text-[10px] uppercase tracking-[0.2em] mb-3 font-mono">Companies Hiring</p>
                <div className="flex flex-wrap gap-2">
                  {selectedSector.companies.map((c) => (
                    <span key={c} className="text-xs px-3 py-1.5 rounded-full bg-white/[0.03] text-zinc-500 border border-white/[0.05]">{c}</span>
                  ))}
                </div>
              </div>
            </div>

            <Link
              href="/auth/login"
              className="mt-8 block text-center rounded-xl py-3.5 font-bold text-black text-sm transition-transform hover:scale-[1.02]"
              style={{ background: `linear-gradient(135deg, ${selectedSector.glowHex}, #f59e0b)` }}
            >
              Find {selectedSector.name.split(" & ")[0]} Roles →
            </Link>
          </div>
        </motion.div>
      )}
    </main>
  );
}
