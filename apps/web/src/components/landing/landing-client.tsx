"use client";
import { useEffect, useRef } from "react";
import Link from "next/link";

const STEPS = [
  {
    step: "01", title: "Build Your Profile",
    desc: "Add your skills, experience, salary expectations, and career goals. Upload your resume — the AI parses and extracts everything automatically.",
    icon: "👤", glow: "59,130,246", accent: "rgba(59,130,246,0.12)", border: "rgba(59,130,246,0.22)",
  },
  {
    step: "02", title: "AI Discovers Jobs",
    desc: "Every 4 hours, scrapers search LinkedIn, Naukri, Indeed, and Wellfound for roles matching your profile. Each job is AI-scored 0–100 against your skills.",
    icon: "🔍", glow: "139,92,246", accent: "rgba(139,92,246,0.12)", border: "rgba(139,92,246,0.22)",
  },
  {
    step: "03", title: "Smart Match Scoring",
    desc: "Jobs scoring 80%+ are auto-queued. 60–79% land in your Approve Queue for one-click review. Below that goes to Watchlist or is archived.",
    icon: "🎯", glow: "245,158,11", accent: "rgba(245,158,11,0.12)", border: "rgba(245,158,11,0.22)",
  },
  {
    step: "04", title: "Auto-Apply Bot",
    desc: "You log in once through your browser — we securely save the session. The bot then fills every form, answers screening questions, uploads your resume, and submits.",
    icon: "⚡", glow: "16,185,129", accent: "rgba(16,185,129,0.12)", border: "rgba(16,185,129,0.22)",
  },
  {
    step: "05", title: "Tailored Cover Letters",
    desc: "Before each application, the AI writes a role-specific cover letter in your voice — highlighting the exact skills the job description asks for.",
    icon: "✍️", glow: "244,63,94", accent: "rgba(244,63,94,0.12)", border: "rgba(244,63,94,0.22)",
  },
  {
    step: "06", title: "Interview Prep & Follow-ups",
    desc: "Get AI-generated technical questions, STAR behavioral answers, and salary strategy. Stale applications auto-generate a personalized follow-up email.",
    icon: "🎤", glow: "6,182,212", accent: "rgba(6,182,212,0.12)", border: "rgba(6,182,212,0.22)",
  },
];

const PARTICLES = Array.from({ length: 16 }, (_, i) => ({
  id: i,
  size: 1.5 + (i % 3) * 1.5,
  color: ["#f59e0b", "#8b5cf6", "#06b6d4", "#10b981"][i % 4],
  left: `${4 + i * 5.8}%`,
  top: `${6 + ((i * 19) % 70)}%`,
  opacity: 0.15 + (i % 5) * 0.07,
  duration: `${5 + i * 0.6}s`,
  delay: `${i * 0.3}s`,
}));

export function LandingClient() {
  const heroRef = useRef<HTMLDivElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);

  /* ── Scroll-driven 3D hero tilt ── */
  useEffect(() => {
    let rafId: number;
    let smooth = 0;

    const tick = () => {
      smooth += (window.scrollY - smooth) * 0.07;
      const p = Math.min(smooth / window.innerHeight, 1);

      if (heroRef.current) {
        heroRef.current.style.transform =
          `perspective(1400px) rotateX(${p * -13}deg) translateY(${smooth * 0.2}px) scale(${1 - p * 0.04})`;
        heroRef.current.style.opacity = `${Math.max(0, 1 - p * 1.6)}`;
      }
      if (gridRef.current) {
        gridRef.current.style.backgroundPositionY = `${smooth * 0.55}px`;
        gridRef.current.style.transform =
          `perspective(500px) rotateX(65deg) translateY(${-smooth * 0.22}px)`;
      }
      rafId = requestAnimationFrame(tick);
    };

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, []);

  /* ── Staggered card entrance ── */
  useEffect(() => {
    const cards = document.querySelectorAll(".step-card");
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const el = entry.target as HTMLElement;
          const idx = Number(el.dataset.index ?? 0);
          setTimeout(() => el.classList.add("step-card--visible"), idx * 115);
          io.unobserve(el);
        });
      },
      { threshold: 0.1, rootMargin: "0px 0px -40px 0px" }
    );
    cards.forEach((c) => io.observe(c));
    return () => io.disconnect();
  }, []);

  /* ── Mouse-tracking 3D tilt + specular highlight ── */
  useEffect(() => {
    const cards = document.querySelectorAll(".step-card");
    const handlers = new Map<Element, { move: EventListener; leave: EventListener }>();

    cards.forEach((card) => {
      const move: EventListener = (e) => {
        const me = e as MouseEvent;
        const el = card as HTMLElement;
        if (!el.classList.contains("step-card--visible")) return;
        const r = el.getBoundingClientRect();
        const x = (me.clientX - r.left) / r.width;
        const y = (me.clientY - r.top) / r.height;
        const rx = (0.5 - y) * 22;
        const ry = (x - 0.5) * 22;
        // Disable CSS transition so tilt tracks cursor instantly
        el.style.transition = "box-shadow 0.15s ease";
        el.style.transform =
          `perspective(900px) rotateX(${rx}deg) rotateY(${ry}deg) translateZ(30px) scale(1.03)`;
        el.style.boxShadow = [
          `${-ry * 0.7}px ${rx * 0.7}px 40px rgba(0,0,0,0.5)`,
          `0 0 60px rgba(${el.dataset.glow ?? "245,158,11"},0.12)`,
          `inset 0 1px 0 rgba(255,255,255,0.06)`,
        ].join(", ");
        const shine = el.querySelector(".card-shine") as HTMLElement | null;
        if (shine) {
          shine.style.background =
            `radial-gradient(ellipse at ${x * 100}% ${y * 100}%, rgba(255,255,255,0.09) 0%, transparent 65%)`;
          shine.style.opacity = "1";
        }
      };

      const leave: EventListener = () => {
        const el = card as HTMLElement;
        // Restore CSS transition → smooth spring-back
        el.style.transition = "";
        el.style.transform = "";
        el.style.boxShadow = "";
        const shine = el.querySelector(".card-shine") as HTMLElement | null;
        if (shine) shine.style.opacity = "0";
      };

      handlers.set(card, { move, leave });
      card.addEventListener("mousemove", move);
      card.addEventListener("mouseleave", leave);
    });

    return () => {
      handlers.forEach(({ move, leave }, card) => {
        card.removeEventListener("mousemove", move);
        card.removeEventListener("mouseleave", leave);
      });
    };
  }, []);

  return (
    <main className="bg-zinc-950 overflow-x-hidden">

      {/* ── Fixed ambient background ── */}
      <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden">

        {/* Perspective grid floor */}
        <div
          ref={gridRef}
          className="absolute bottom-0 left-1/2 -translate-x-1/2 w-[220%] h-[55vh]"
          style={{
            backgroundImage: [
              "linear-gradient(rgba(245,158,11,0.06) 1px, transparent 1px)",
              "linear-gradient(90deg, rgba(245,158,11,0.06) 1px, transparent 1px)",
            ].join(", "),
            backgroundSize: "60px 60px",
            transform: "perspective(500px) rotateX(65deg)",
            transformOrigin: "center bottom",
            maskImage: "linear-gradient(to top, rgba(0,0,0,0.85) 0%, transparent 100%)",
            WebkitMaskImage: "linear-gradient(to top, rgba(0,0,0,0.85) 0%, transparent 100%)",
          }}
        />

        {/* Vignette */}
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_80%_70%_at_50%_40%,transparent_20%,#09090b_100%)]" />

        {/* Central amber bloom */}
        <div
          className="absolute top-[38%] left-1/2 -translate-x-1/2 -translate-y-1/2 w-[520px] h-[520px] rounded-full animate-pulse-slow"
          style={{ background: "radial-gradient(ellipse, rgba(245,158,11,0.045) 0%, transparent 70%)" }}
        />

        {/* Floating particles */}
        {PARTICLES.map((p) => (
          <div
            key={p.id}
            className="absolute rounded-full animate-float-particle"
            style={{
              width: p.size, height: p.size,
              background: p.color,
              left: p.left, top: p.top,
              opacity: p.opacity,
              animationDuration: p.duration,
              animationDelay: p.delay,
              boxShadow: `0 0 ${p.size * 4}px ${p.color}88`,
            }}
          />
        ))}
      </div>

      {/* ── Hero ── */}
      <div
        ref={heroRef}
        className="relative z-10 min-h-screen flex flex-col items-center justify-center p-6"
        style={{ transformOrigin: "50% 80%" }}
      >
        {/* Orbit rings */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none select-none">
          {[{ size: 280, dur: "22s", dir: "normal" }, { size: 190, dur: "14s", dir: "reverse" }, { size: 110, dur: "30s", dir: "normal" }].map(({ size, dur, dir }, i) => (
            <div
              key={size}
              className="absolute rounded-full animate-spin-slow"
              style={{
                width: size, height: size,
                top: "50%", left: "50%",
                marginTop: -size / 2, marginLeft: -size / 2,
                border: `1px solid rgba(245,158,11,${0.05 + i * 0.03})`,
                animationDuration: dur,
                animationDirection: dir as "normal" | "reverse",
              }}
            />
          ))}
          {/* Orbiting dot on outer ring */}
          <div className="absolute animate-spin-slow" style={{ width: 280, height: 280, top: "50%", left: "50%", marginTop: -140, marginLeft: -140, animationDuration: "22s" }}>
            <div className="absolute -top-[3px] left-1/2 -translate-x-1/2 w-[6px] h-[6px] rounded-full bg-amber-400"
              style={{ boxShadow: "0 0 8px #f59e0b, 0 0 20px rgba(245,158,11,0.5)" }} />
          </div>
          {/* Second orbiting dot (smaller, inner ring, opposite phase) */}
          <div className="absolute animate-spin-slow" style={{ width: 190, height: 190, top: "50%", left: "50%", marginTop: -95, marginLeft: -95, animationDuration: "14s", animationDirection: "reverse" }}>
            <div className="absolute -bottom-[2px] left-1/2 -translate-x-1/2 w-[4px] h-[4px] rounded-full bg-violet-400"
              style={{ boxShadow: "0 0 6px #8b5cf6, 0 0 14px rgba(139,92,246,0.5)" }} />
          </div>
        </div>

        <div className="relative z-10 max-w-3xl mx-auto text-center space-y-8">
          {/* Badge */}
          <div className="inline-flex items-center gap-2 bg-zinc-900/70 backdrop-blur border border-zinc-800 rounded-full px-4 py-1.5 text-sm text-zinc-400">
            <span className="w-2 h-2 bg-amber-500 rounded-full animate-pulse" />
            AI-Powered Career Agent
          </div>

          {/* Headline */}
          <h1 className="text-5xl sm:text-7xl font-bold tracking-tight leading-[1.06]">
            Your AI applies{" "}
            <span className="relative text-amber-400">
              while you sleep
              <span className="absolute inset-x-4 -bottom-1 h-px bg-gradient-to-r from-transparent via-amber-400/50 to-transparent" />
            </span>
          </h1>

          <p className="text-lg text-zinc-400 max-w-xl mx-auto leading-relaxed">
            JobPlatform discovers relevant jobs, scores your fit, tailors your resume,
            and auto-submits applications — 24/7. You only focus on interviews.
          </p>

          {/* Pills */}
          <div className="flex flex-wrap gap-2 justify-center">
            {["LinkedIn · Naukri · Indeed · Wellfound", "AI Match Scoring", "Auto Apply", "Interview Prep", "Skill Gap Analysis"].map((f) => (
              <span key={f} className="text-xs bg-zinc-900/70 backdrop-blur border border-zinc-800 rounded-full px-3 py-1 text-zinc-400 hover:border-amber-500/40 hover:text-amber-300 transition-colors cursor-default">
                {f}
              </span>
            ))}
          </div>

          {/* CTAs */}
          <div className="flex gap-3 justify-center">
            <Link href="/auth/login" className="btn-primary text-base px-7 py-3"
              style={{ boxShadow: "0 0 30px rgba(245,158,11,0.3), 0 0 60px rgba(245,158,11,0.1)" }}>
              Get Started Free
            </Link>
            <Link href="#features" className="btn-secondary text-base px-7 py-3 hover:border-amber-500/40 hover:text-amber-200 transition-colors">
              See How It Works
            </Link>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-3 gap-4 pt-8 border-t border-zinc-800/50 max-w-sm mx-auto">
            {[["10+", "Job Boards"], ["24/7", "Auto Apply"], ["AI", "Match Score"]].map(([v, l]) => (
              <div key={l} className="text-center group cursor-default">
                <div className="text-2xl font-bold text-amber-400 font-mono group-hover:scale-110 transition-transform origin-bottom">{v}</div>
                <div className="text-xs text-zinc-500 mt-0.5">{l}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Scroll cue */}
        <div className="absolute bottom-10 left-1/2 -translate-x-1/2 flex flex-col items-center gap-2 animate-bounce">
          <span className="text-[9px] tracking-[0.3em] text-zinc-700 uppercase font-medium">Scroll</span>
          <div className="w-px h-8 bg-gradient-to-b from-zinc-700 to-transparent" />
        </div>
      </div>

      {/* ── How It Works ── */}
      <section id="features" className="relative z-10 w-full max-w-5xl mx-auto px-6 py-32">
        <div className="text-center mb-16 space-y-3">
          <p className="text-[11px] font-mono tracking-[0.3em] text-amber-500/60 uppercase">The Process</p>
          <h2 className="text-4xl sm:text-5xl font-bold tracking-tight">
            How It <span className="text-amber-400">Works</span>
          </h2>
          <p className="text-zinc-400 max-w-md mx-auto text-sm leading-relaxed">
            Set up in 5 minutes. The platform handles your entire job search 24/7.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
          {STEPS.map((s, i) => (
            <div
              key={s.step}
              className="step-card"
              data-index={i}
              data-glow={s.glow}
            >
              {/* Specular reflection layer */}
              <div className="card-shine" />

              <div className="relative z-10">
                <div className="flex items-center justify-between mb-5">
                  <div
                    className="w-11 h-11 rounded-2xl flex items-center justify-center text-xl flex-none"
                    style={{
                      background: s.accent,
                      border: `1px solid ${s.border}`,
                      boxShadow: `0 0 24px ${s.accent}, inset 0 1px 0 rgba(255,255,255,0.06)`,
                    }}
                  >
                    {s.icon}
                  </div>
                  <span
                    className="text-[10px] font-mono tracking-[0.22em] font-semibold"
                    style={{ color: `rgba(${s.glow},0.6)` }}
                  >
                    STEP {s.step}
                  </span>
                </div>

                <h3 className="font-semibold text-[15px] text-white mb-2 leading-snug">{s.title}</h3>
                <p className="text-sm text-zinc-400 leading-relaxed">{s.desc}</p>

                <div className="mt-5 h-px"
                  style={{ background: `linear-gradient(90deg, transparent, ${s.border}, transparent)` }} />
              </div>
            </div>
          ))}
        </div>

        {/* Bottom CTA */}
        <div className="mt-20 text-center">
          <Link
            href="/auth/login"
            className="btn-primary text-base px-10 py-4 font-semibold"
            style={{ boxShadow: "0 0 40px rgba(245,158,11,0.25), 0 0 80px rgba(245,158,11,0.08)" }}
          >
            Start Applying on Autopilot →
          </Link>
          <p className="text-xs text-zinc-700 mt-4">Free to start · No credit card required</p>
        </div>
      </section>
    </main>
  );
}
