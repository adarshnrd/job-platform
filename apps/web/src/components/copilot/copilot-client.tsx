"use client";

import { useState, useRef, useEffect } from "react";
import { api } from "@/lib/api";
import { Send, Bot, User, Zap, FileText, MessageSquare, TrendingUp, DollarSign, Sparkles, ChevronRight, RotateCcw } from "lucide-react";

interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

const QUICK_ACTIONS = [
  { label: "Review My Resume",     icon: FileText,      context: "resume_review",  prompt: "Please review my resume and give me specific, actionable feedback to improve my chances of getting interviews." },
  { label: "Write Cover Letter",   icon: MessageSquare, context: "cover_letter",   prompt: "Help me write a compelling cover letter template that I can customize for different roles." },
  { label: "Mock Interview",       icon: Zap,           context: "interview",      prompt: "Start a mock technical interview with me. Ask me the first question as if you're a senior engineering interviewer." },
  { label: "Salary Negotiation",   icon: DollarSign,    context: "salary",         prompt: "Coach me on salary negotiation. What's the best strategy to negotiate a higher offer?" },
  { label: "Career Path Advice",   icon: TrendingUp,    context: "general",        prompt: "Based on my profile, what career paths should I focus on and what's the fastest way to reach a senior/lead position?" },
  { label: "Skill Gap Analysis",   icon: Sparkles,      context: "general",        prompt: "What skills am I missing that are most in demand right now? Give me a prioritized learning plan." },
];

const WELCOME = `# Welcome to your AI Career Copilot 🚀

I'm your personal career agent, powered by AI. Here's what I can help you with:

**Resume & Applications**
- Deep resume review with ATS optimization tips
- Tailored cover letters for specific roles
- Application strategy for maximum callbacks

**Interview Preparation**
- Role-specific technical questions
- Behavioral question coaching (STAR method)
- Salary negotiation scripts and tactics

**Career Growth**
- Personalized skill gap analysis
- Course & certification recommendations
- Career path planning and progression

**Quick Start:** Pick an action below, or just ask me anything about your career journey.`;

export function CopilotClient() {
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: WELCOME, timestamp: new Date() },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<{ suggestions: string; top_skill_gaps: any[] } | null>(null);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    loadCareerSuggestions();
  }, []);

  const loadCareerSuggestions = async () => {
    setLoadingSuggestions(true);
    try {
      const data = await api.copilot.careerSuggestions();
      setSuggestions(data);
    } catch {
      // Suggestions panel is non-critical
    } finally {
      setLoadingSuggestions(false);
    }
  };

  const sendMessage = async (text: string, context = "general") => {
    if (!text.trim() || loading) return;

    const userMsg: Message = { role: "user", content: text, timestamp: new Date() };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const history = messages.slice(-6).map(m => ({ role: m.role, content: m.content }));
      const data = await api.copilot.chat({ message: text, context, history });
      const assistantMsg: Message = {
        role: "assistant",
        content: data.response || "I couldn't generate a response. Please try again.",
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, assistantMsg]);
    } catch (err) {
      setMessages(prev => [...prev, {
        role: "assistant",
        content: "Sorry, I encountered an error. Please try again — make sure the API server is running.",
        timestamp: new Date(),
      }]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    sendMessage(input);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const clearChat = () => {
    setMessages([{ role: "assistant", content: WELCOME, timestamp: new Date() }]);
  };

  const renderMessage = (content: string) => {
    // Simple markdown-like rendering
    return content
      .split("\n")
      .map((line, i) => {
        if (line.startsWith("# ")) return <h2 key={i} className="text-lg font-black text-white mt-1 mb-2">{line.slice(2)}</h2>;
        if (line.startsWith("## ")) return <h3 key={i} className="text-base font-bold text-zinc-100 mt-3 mb-1">{line.slice(3)}</h3>;
        if (line.startsWith("**") && line.endsWith("**")) return <p key={i} className="font-bold text-white mt-2">{line.slice(2, -2)}</p>;
        if (line.startsWith("- ")) return <li key={i} className="ml-4 text-zinc-300 list-disc">{renderInline(line.slice(2))}</li>;
        if (line.startsWith("• ")) return <li key={i} className="ml-4 text-zinc-300 list-disc">{renderInline(line.slice(2))}</li>;
        if (line.match(/^\d+\./)) return <li key={i} className="ml-4 text-zinc-300 list-decimal">{renderInline(line.replace(/^\d+\.\s*/, ""))}</li>;
        if (line === "") return <div key={i} className="h-1" />;
        return <p key={i} className="text-zinc-300 leading-relaxed">{renderInline(line)}</p>;
      });
  };

  const renderInline = (text: string) => {
    const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
    return parts.map((part, i) => {
      if (part.startsWith("**") && part.endsWith("**")) return <strong key={i} className="text-white font-semibold">{part.slice(2, -2)}</strong>;
      if (part.startsWith("`") && part.endsWith("`")) return <code key={i} className="bg-zinc-700 px-1 py-0.5 rounded text-amber-300 text-xs">{part.slice(1, -1)}</code>;
      return part;
    });
  };

  return (
    <div className="flex h-screen overflow-hidden bg-zinc-950">

      {/* ── Chat Panel ── */}
      <div className="flex-1 flex flex-col min-w-0">

        {/* Header */}
        <div className="px-6 py-4 border-b border-zinc-800 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center">
              <Bot size={18} className="text-black" />
            </div>
            <div>
              <h1 className="text-sm font-bold text-white">AI Career Copilot</h1>
              <p className="text-xs text-zinc-500">Your personal career agent • Always available</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 text-xs text-emerald-400 bg-emerald-400/10 px-2.5 py-1 rounded-full border border-emerald-400/20">
              <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse" />
              Online
            </div>
            <button onClick={clearChat} className="p-2 text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800 rounded-lg transition-colors" title="New conversation">
              <RotateCcw size={14} />
            </button>
          </div>
        </div>

        {/* Quick actions */}
        <div className="px-4 py-3 border-b border-zinc-800/50 flex gap-2 overflow-x-auto shrink-0 scrollbar-hide">
          {QUICK_ACTIONS.map(({ label, icon: Icon, context, prompt }) => (
            <button
              key={label}
              onClick={() => sendMessage(prompt, context)}
              disabled={loading}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 rounded-full text-xs font-medium text-zinc-300 hover:text-white transition-all whitespace-nowrap disabled:opacity-50"
            >
              <Icon size={11} className="text-amber-400" />
              {label}
            </button>
          ))}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
          {messages.map((msg, i) => (
            <div key={i} className={`flex gap-3 ${msg.role === "user" ? "flex-row-reverse" : "flex-row"}`}>

              {/* Avatar */}
              <div className={`w-7 h-7 rounded-lg shrink-0 flex items-center justify-center mt-0.5 ${
                msg.role === "user"
                  ? "bg-zinc-700 text-zinc-300"
                  : "bg-gradient-to-br from-amber-500 to-orange-600 text-black"
              }`}>
                {msg.role === "user" ? <User size={14} /> : <Bot size={14} />}
              </div>

              {/* Bubble */}
              <div className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                msg.role === "user"
                  ? "bg-amber-500/15 border border-amber-500/20 text-right"
                  : "bg-zinc-800/70 border border-zinc-700/50"
              }`}>
                <div className={`text-sm space-y-0.5 ${msg.role === "user" ? "text-zinc-100" : ""}`}>
                  {msg.role === "user"
                    ? <p className="text-zinc-100">{msg.content}</p>
                    : <div>{renderMessage(msg.content)}</div>
                  }
                </div>
                <p className={`text-[10px] mt-1.5 ${msg.role === "user" ? "text-amber-400/60 text-right" : "text-zinc-600"}`}>
                  {msg.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </p>
              </div>
            </div>
          ))}

          {/* Typing indicator */}
          {loading && (
            <div className="flex gap-3">
              <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center shrink-0">
                <Bot size={14} className="text-black" />
              </div>
              <div className="bg-zinc-800 border border-zinc-700/50 rounded-2xl px-4 py-3">
                <div className="flex gap-1 items-center h-4">
                  {[0, 1, 2].map(i => (
                    <span key={i} className="w-1.5 h-1.5 bg-amber-400 rounded-full animate-bounce" style={{ animationDelay: `${i * 0.15}s` }} />
                  ))}
                </div>
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <form onSubmit={handleSubmit} className="px-4 py-4 border-t border-zinc-800 shrink-0">
          <div className="flex gap-2 items-end bg-zinc-800/60 border border-zinc-700 rounded-2xl px-4 py-2.5 focus-within:border-amber-500/50 transition-colors">
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask anything about your career, resume, interview prep..."
              rows={1}
              className="flex-1 bg-transparent text-sm text-zinc-100 placeholder-zinc-500 resize-none outline-none leading-relaxed max-h-32"
              style={{ scrollbarWidth: "none" }}
            />
            <button
              type="submit"
              disabled={!input.trim() || loading}
              className="w-8 h-8 rounded-xl bg-amber-500 hover:bg-amber-400 disabled:bg-zinc-700 flex items-center justify-center transition-colors shrink-0"
            >
              <Send size={14} className={loading ? "text-zinc-500" : "text-black"} />
            </button>
          </div>
          <p className="text-[10px] text-zinc-600 mt-1.5 text-center">
            Shift+Enter for new line · Enter to send
          </p>
        </form>
      </div>

      {/* ── Right Panel: Career Insights ── */}
      <div className="w-72 border-l border-zinc-800 flex flex-col overflow-y-auto shrink-0">
        <div className="px-4 py-4 border-b border-zinc-800">
          <h2 className="text-sm font-bold text-white">Career Insights</h2>
          <p className="text-xs text-zinc-500 mt-0.5">Based on your application history</p>
        </div>

        {/* Top skill gaps */}
        {suggestions?.top_skill_gaps && suggestions.top_skill_gaps.length > 0 && (
          <div className="px-4 py-4 border-b border-zinc-800">
            <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">Top Skill Gaps</p>
            <div className="space-y-2">
              {suggestions.top_skill_gaps.slice(0, 5).map(([skill, count]: [string, number]) => (
                <div key={skill} className="flex items-center gap-2">
                  <div className="flex-1 text-xs text-zinc-300 truncate">{skill}</div>
                  <div className="text-xs font-mono text-amber-400">{count}x</div>
                  <button
                    onClick={() => sendMessage(`Tell me the fastest way to learn ${skill} and which certifications or projects would make me competitive in job applications.`)}
                    className="text-zinc-600 hover:text-amber-400 transition-colors"
                  >
                    <ChevronRight size={12} />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* AI Suggestions */}
        <div className="px-4 py-4 flex-1">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">AI Suggestions</p>
            <button onClick={loadCareerSuggestions} className="text-zinc-600 hover:text-zinc-400 transition-colors">
              <RotateCcw size={11} />
            </button>
          </div>

          {loadingSuggestions ? (
            <div className="space-y-2">
              {[1,2,3].map(i => <div key={i} className="h-12 bg-zinc-800 rounded-lg animate-pulse" />)}
            </div>
          ) : suggestions?.suggestions ? (
            <div className="text-xs text-zinc-400 leading-relaxed whitespace-pre-wrap">
              {suggestions.suggestions.slice(0, 400)}
              {suggestions.suggestions.length > 400 && (
                <button
                  className="text-amber-400 hover:text-amber-300 ml-1"
                  onClick={() => sendMessage("Show me my full personalized career development plan with detailed course recommendations and a 90-day action plan.")}
                >
                  See full plan →
                </button>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              {["Apply to 5+ jobs to get personalized skill gap analysis", "Ask me to review your resume for ATS optimization", "Try a mock interview to build confidence"].map(tip => (
                <div key={tip} className="text-xs text-zinc-500 bg-zinc-800/50 rounded-lg p-3 leading-relaxed">
                  {tip}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Resume Analysis CTA */}
        <div className="px-4 py-4 border-t border-zinc-800">
          <button
            onClick={async () => {
              setLoading(true);
              try {
                const data = await api.copilot.analyzeResume();
                setMessages(prev => [...prev,
                  { role: "user" as const, content: "Please analyze my resume.", timestamp: new Date() },
                  { role: "assistant" as const, content: data.analysis, timestamp: new Date() },
                ]);
              } catch {
                setMessages(prev => [...prev, {
                  role: "assistant" as const,
                  content: "Couldn't analyze resume. Make sure you have a primary resume uploaded in the Resume section.",
                  timestamp: new Date(),
                }]);
              } finally {
                setLoading(false);
              }
            }}
            disabled={loading}
            className="w-full py-2.5 bg-amber-500/10 border border-amber-500/20 hover:bg-amber-500/20 text-amber-400 text-xs font-semibold rounded-xl transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
          >
            <FileText size={13} />
            Analyze My Resume
          </button>
        </div>
      </div>
    </div>
  );
}
