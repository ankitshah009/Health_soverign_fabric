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
            aria-label="Start voice conversation"
            className="w-16 h-16 rounded-full flex items-center justify-center btn-press"
            style={{
              background: "linear-gradient(135deg, var(--accent-primary), var(--accent-primary-hover))",
              boxShadow: "0 4px 24px rgba(245, 166, 35, 0.35), 0 0 0 4px rgba(245, 166, 35, 0.10)",
            }}
            title="Start voice conversation"
          >
            <Mic size={26} color="var(--bg-base)" strokeWidth={2.5} />
          </button>

          {/* Chat FAB — secondary, smaller */}
          <button
            data-testid="chat-fab"
            onClick={() => openWith("chat")}
            aria-label="Open chat assistant"
            className="w-12 h-12 rounded-full flex items-center justify-center btn-press"
            style={{
              background: "var(--bg-surface)",
              border: "1px solid var(--border-default)",
              boxShadow: "0 4px 16px rgba(0, 0, 0, 0.3)",
            }}
            title="Open chat assistant"
          >
            <MessageSquare size={20} style={{ color: "var(--accent-primary)" }} />
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
              boxShadow: "0 8px 40px rgba(0, 0, 0, 0.5)",
            }}
          >
            {/* Close button */}
            <button
              data-testid="chat-fab-close"
              aria-label="Close"
              onClick={() => setIsOpen(false)}
              className="absolute top-3 right-3 z-10 w-8 h-8 rounded-lg flex items-center justify-center transition-colors"
              style={{
                color: "var(--text-muted)",
                background: "var(--bg-elevated)",
              }}
            >
              <X size={16} />
            </button>

            {/* Mode tabs */}
            <div
              className="flex px-4 pt-4 pb-2 gap-1"
              style={{ borderBottom: "1px solid var(--border-subtle)" }}
            >
              <button
                onClick={() => setMode("voice")}
                className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all"
                style={{
                  background: mode === "voice" ? "var(--accent-primary-bg)" : "transparent",
                  color: mode === "voice" ? "var(--accent-primary)" : "var(--text-secondary)",
                  border: mode === "voice" ? "1px solid var(--accent-primary-border)" : "1px solid transparent",
                }}
              >
                <Mic size={16} />
                Voice
              </button>
              <button
                onClick={() => setMode("chat")}
                className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all"
                style={{
                  background: mode === "chat" ? "var(--accent-primary-bg)" : "transparent",
                  color: mode === "chat" ? "var(--accent-primary)" : "var(--text-secondary)",
                  border: mode === "chat" ? "1px solid var(--accent-primary-border)" : "1px solid transparent",
                }}
              >
                <MessageSquare size={16} />
                Chat
              </button>
            </div>

            {mode === "voice" ? (
              /* ── Voice mode: centered, prominent ── */
              <div className="flex-1 flex flex-col items-center justify-center p-8 gap-4">
                <p
                  className="type-section-title text-center mb-2"
                  style={{ color: "var(--text-primary)" }}
                >
                  Sovereign Voice Advocate
                </p>
                <p className="text-sm text-center mb-4" style={{ color: "var(--text-secondary)" }}>
                  Tap the mic to review a bill, check case status, or ask questions — hands free.
                </p>
                <VoiceButton autoStart />
              </div>
            ) : (
              /* ── Chat mode ── */
              <>
                <div className="flex-1 min-h-0">
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
