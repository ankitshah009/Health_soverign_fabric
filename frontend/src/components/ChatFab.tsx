"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import { MessageSquare, X, Mic } from "lucide-react";
import ChatPanel from "./ChatPanel";
import VoiceButton from "./VoiceButton";

export const SOVEREIGN_OPEN_VOICE_EVENT = "sovereign:open-voice";

export default function ChatFab() {
  const [isOpen, setIsOpen] = useState(false);
  const [mode, setMode] = useState<"chat" | "voice">("chat");
  const pathname = usePathname();

  // Listen for demo-trigger events so DemoTrigger can open the voice panel
  useEffect(() => {
    const handler = () => {
      setMode("voice");
      setIsOpen(true);
    };
    window.addEventListener(SOVEREIGN_OPEN_VOICE_EVENT, handler);
    return () => window.removeEventListener(SOVEREIGN_OPEN_VOICE_EVENT, handler);
  }, []);

  // Extract claimId from URL if on a claim detail page (exclude /claims/submit)
  const claimIdMatch = pathname.match(/^\/claims\/([^/]+)$/);
  const claimId = claimIdMatch && claimIdMatch[1] !== "submit" ? claimIdMatch[1] : undefined;

  const openWith = (m: "chat" | "voice") => {
    setMode(m);
    setIsOpen(true);
  };

  return (
    <>
      {/* ── Dual FAB buttons: Voice (primary) + Chat ── */}
      {!isOpen && (
        <div className="fixed bottom-6 right-6 z-50 flex flex-col items-end gap-3">
          {/* Voice FAB — big, primary, unmissable */}
          <button
            data-testid="voice-fab"
            onClick={() => openWith("voice")}
            aria-label="Open voice advocate — hands-free bill review"
            className="w-16 h-16 rounded-full flex items-center justify-center btn-press focus-ring"
            style={{
              background: "linear-gradient(135deg, var(--accent-primary), var(--accent-primary-hover))",
              boxShadow: "0 4px 24px rgba(43, 130, 240, 0.32), 0 0 0 4px rgba(43, 130, 240, 0.12)",
            }}
            title="Start voice conversation"
          >
            <Mic size={26} color="var(--bg-base)" strokeWidth={2.5} aria-hidden="true" />
          </button>

          {/* Chat FAB — secondary, smaller */}
          <button
            data-testid="chat-fab"
            onClick={() => openWith("chat")}
            aria-label="Open chat assistant"
            className="w-12 h-12 rounded-full flex items-center justify-center btn-press focus-ring"
            style={{
              background: "var(--bg-surface)",
              border: "1px solid var(--border-default)",
              boxShadow: "var(--shadow-md)",
            }}
            title="Open chat assistant"
          >
            <MessageSquare size={20} style={{ color: "var(--accent-primary)" }} aria-hidden="true" />
          </button>
        </div>
      )}

      {/* ── Expanded panel ── */}
      {isOpen && (
        <div
          className="fixed bottom-6 right-6 z-50 animate-scale-in"
          style={{
            width: "min(420px, calc(100vw - 48px))",
            height: mode === "voice" ? "auto" : "min(600px, calc(100vh - 120px))",
          }}
        >
          <div
            className="relative flex flex-col h-full rounded-2xl overflow-hidden"
            style={{
              background: "var(--bg-base)",
              border: "1px solid var(--border-subtle)",
              boxShadow: "var(--shadow-lg)",
            }}
          >
            {/* Close button */}
            <button
              data-testid="chat-fab-close"
              aria-label="Close patient advocate panel"
              onClick={() => setIsOpen(false)}
              className="absolute top-3 right-3 z-10 w-11 h-11 rounded-lg flex items-center justify-center transition-colors focus-ring"
              style={{
                color: "var(--text-muted)",
                background: "var(--bg-elevated)",
              }}
            >
              <X size={16} aria-hidden="true" />
            </button>

            {/* ── Mode tabs ─────────────────────── */}
            <div
              className="flex px-4 pt-4 pb-0 gap-1"
              style={{ borderBottom: "1px solid var(--border-subtle)" }}
              role="tablist"
              aria-label="Advocate mode"
            >
              <button
                role="tab"
                onClick={() => setMode("voice")}
                aria-label="Switch to voice mode"
                aria-selected={mode === "voice"}
                aria-pressed={mode === "voice"}
                className="flex items-center gap-2 px-4 py-2.5 rounded-t-lg text-sm font-medium transition-colors focus-ring"
                style={{
                  background: mode === "voice" ? "var(--bg-surface)" : "transparent",
                  color: mode === "voice" ? "var(--accent-primary)" : "var(--text-secondary)",
                  borderTop: mode === "voice" ? "1px solid var(--border-subtle)" : "1px solid transparent",
                  borderLeft: mode === "voice" ? "1px solid var(--border-subtle)" : "1px solid transparent",
                  borderRight: mode === "voice" ? "1px solid var(--border-subtle)" : "1px solid transparent",
                  borderBottom: mode === "voice" ? "1px solid var(--bg-surface)" : "1px solid transparent",
                  marginBottom: mode === "voice" ? "-1px" : 0,
                  position: "relative",
                }}
              >
                <Mic size={15} aria-hidden="true" />
                Voice
              </button>
              <button
                role="tab"
                onClick={() => setMode("chat")}
                aria-label="Switch to chat mode"
                aria-selected={mode === "chat"}
                aria-pressed={mode === "chat"}
                className="flex items-center gap-2 px-4 py-2.5 rounded-t-lg text-sm font-medium transition-colors focus-ring"
                style={{
                  background: mode === "chat" ? "var(--bg-surface)" : "transparent",
                  color: mode === "chat" ? "var(--accent-primary)" : "var(--text-secondary)",
                  borderTop: mode === "chat" ? "1px solid var(--border-subtle)" : "1px solid transparent",
                  borderLeft: mode === "chat" ? "1px solid var(--border-subtle)" : "1px solid transparent",
                  borderRight: mode === "chat" ? "1px solid var(--border-subtle)" : "1px solid transparent",
                  borderBottom: mode === "chat" ? "1px solid var(--bg-surface)" : "1px solid transparent",
                  marginBottom: mode === "chat" ? "-1px" : 0,
                  position: "relative",
                }}
              >
                <MessageSquare size={15} aria-hidden="true" />
                Chat
              </button>
            </div>

            {mode === "voice" ? (
              /* ── Voice mode: centered, prominent ── */
              <div
                className="flex-1 flex flex-col items-center justify-center px-8 py-10 gap-6"
                style={{ background: "var(--bg-base)" }}
              >
                {/* Identity */}
                <div className="text-center space-y-1.5">
                  <p
                    className="type-section-title"
                    style={{ color: "var(--text-primary)" }}
                  >
                    Sovereign Voice Advocate
                  </p>
                  <p
                    className="type-body"
                    style={{ color: "var(--text-secondary)", maxWidth: 280 }}
                  >
                    Review a bill, check case status, or ask questions — hands free.
                  </p>
                </div>

                {/* Divider */}
                <div
                  style={{
                    width: 40,
                    height: 1,
                    background: "var(--border-subtle)",
                  }}
                  aria-hidden="true"
                />

                <VoiceButton autoStart />
              </div>
            ) : (
              /* ── Chat mode ── */
              <>
                <div className="flex-1 min-h-0" style={{ background: "var(--bg-base)" }}>
                  <ChatPanel claimId={claimId} />
                </div>
                {/* Voice button at bottom of chat too */}
                <div
                  className="flex-shrink-0 py-3 flex justify-center"
                  style={{ borderTop: "1px solid var(--border-subtle)" }}
                >
                  <VoiceButton />
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
