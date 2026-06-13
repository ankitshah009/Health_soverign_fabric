"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { streamChat } from "@/lib/api";
import { ChatMessage, ToolCall } from "@/lib/types";
import { MessageSquare, Send, Paperclip, ChevronDown, X, ArrowRight } from "lucide-react";

interface ChatPanelProps {
  claimId?: string;
}

function ToolCallCard({ toolCall }: { toolCall: ToolCall }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className="rounded-lg my-2 cursor-pointer transition-colors"
      onClick={() => setExpanded(!expanded)}
      role="button"
      tabIndex={0}
      aria-expanded={expanded}
      aria-label={`Tool call: ${toolCall.name}. Click to ${expanded ? "collapse" : "expand"} details.`}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          setExpanded(!expanded);
        }
      }}
      style={{
        background: "var(--bg-elevated)",
        border: "1px solid var(--border-default)",
      }}
    >
      {/* Header row */}
      <div className="flex items-center gap-2.5 px-3 py-2.5">
        <span
          className="inline-flex items-center justify-center w-5 h-5 rounded flex-shrink-0"
          style={{ background: "var(--accent-primary-bg)" }}
          aria-hidden="true"
        >
          <ChevronDown
            className={`w-3 h-3 transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
            style={{ color: "var(--accent-primary)" }}
          />
        </span>

        <span
          className="type-mono flex-1 truncate"
          style={{ color: "var(--accent-primary)" }}
        >
          {toolCall.name}
        </span>

        {toolCall.result ? (
          <span
            className="type-overline flex-shrink-0 px-2 py-0.5 rounded"
            style={{
              color: "var(--risk-low)",
              background: "var(--risk-low-bg)",
            }}
          >
            done
          </span>
        ) : (
          <span
            className="type-overline flex-shrink-0"
            style={{ color: "var(--text-muted)" }}
          >
            running
          </span>
        )}
      </div>

      {/* Expanded body */}
      {expanded && (
        <div
          className="px-3 pb-3 space-y-2 border-t"
          style={{ borderColor: "var(--border-default)" }}
        >
          {Object.keys(toolCall.arguments).length > 0 && (
            <div
              className="mt-2 rounded p-2.5 text-xs font-mono overflow-x-auto"
              style={{
                background: "var(--bg-recessed)",
                color: "var(--text-secondary)",
                lineHeight: 1.6,
              }}
            >
              {Object.entries(toolCall.arguments).map(([key, val]) => (
                <div key={key}>
                  <span style={{ color: "var(--text-muted)" }}>{key}: </span>
                  <span style={{ color: "var(--text-primary)" }}>
                    {typeof val === "object" ? JSON.stringify(val) : String(val)}
                  </span>
                </div>
              ))}
            </div>
          )}
          {toolCall.result && (
            <div
              className="rounded p-2.5 text-xs font-mono overflow-x-auto max-h-32 overflow-y-auto"
              style={{
                background: "var(--risk-low-bg)",
                border: "1px solid var(--risk-low-border)",
                color: "var(--text-primary)",
                lineHeight: 1.6,
              }}
            >
              {toolCall.result}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  return (
    <div className={`flex gap-3 animate-fade-in ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      {/* Avatar dot — Sovereign only */}
      {!isUser && (
        <div
          className="flex-shrink-0 w-6 h-6 rounded-full mt-0.5 flex items-center justify-center"
          style={{
            background: "var(--accent-primary-bg)",
            border: "1px solid var(--accent-primary-border)",
          }}
          aria-hidden="true"
        >
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: "var(--accent-primary)",
              display: "block",
            }}
          />
        </div>
      )}

      <div
        className={`max-w-[82%] rounded-2xl px-4 py-3 text-sm ${
          isUser ? "rounded-tr-sm" : "rounded-tl-sm"
        }`}
        style={{
          background: isUser ? "var(--accent-primary)" : "var(--bg-surface)",
          color: isUser ? "var(--bg-base)" : "var(--text-primary)",
          border: isUser ? "none" : "1px solid var(--border-subtle)",
          lineHeight: 1.55,
        }}
      >
        <div className="whitespace-pre-wrap break-words">
          {message.content}
          {message.isStreaming && (
            <span
              className="inline-block w-px h-4 ml-0.5 align-text-bottom"
              style={{
                background: isUser ? "var(--bg-base)" : "var(--accent-primary)",
                animation: "blink 1s step-end infinite",
              }}
              aria-hidden="true"
            />
          )}
        </div>
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="mt-2.5 space-y-1">
            {message.toolCalls.map((tc) => (
              <ToolCallCard key={tc.id} toolCall={tc} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function FileDropZone({
  onFileDrop,
  isDragging,
}: {
  onFileDrop: (file: File) => void;
  isDragging: boolean;
}) {
  if (!isDragging) return null;

  return (
    <div
      className="absolute inset-0 z-10 flex items-center justify-center rounded-xl"
      style={{
        background: "var(--glass-bg)",
        border: "2px dashed var(--accent-primary)",
        backdropFilter: "blur(var(--glass-blur))",
      }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        const file = e.dataTransfer.files[0];
        if (file) onFileDrop(file);
      }}
    >
      <div className="text-center space-y-2 px-6">
        <Paperclip
          className="w-9 h-9 mx-auto"
          style={{ color: "var(--accent-primary)" }}
          aria-hidden="true"
        />
        <p
          className="type-subtitle"
          style={{ color: "var(--text-primary)" }}
        >
          Drop your medical bill or EOB
        </p>
        <p className="type-caption" style={{ color: "var(--text-secondary)" }}>
          PDF or image accepted
        </p>
      </div>
    </div>
  );
}

// Suggested starter prompts shown in empty state
const STARTERS = [
  "Analyze this bill for overcharges",
  "My claim was denied — what are my options?",
  "Explain this EOB line by line",
];

export default function ChatPanel({ claimId }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [attachedFile, setAttachedFile] = useState<File | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const isStreamingRef = useRef(false);
  const dragCountRef = useRef(0);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const handleSend = useCallback(async (overrideInput?: string) => {
    if (isStreamingRef.current) return;
    const trimmed = (overrideInput ?? input).trim();
    if (!trimmed && !attachedFile) return;
    if (isStreaming) return;

    isStreamingRef.current = true;
    abortRef.current = new AbortController();

    let userContent = trimmed;
    if (attachedFile) {
      userContent = `[Attached: ${attachedFile.name}]\n${trimmed}`;
    }

    const userMessage: ChatMessage = {
      role: "user",
      content: userContent,
    };

    const updatedMessages = [...messages, userMessage];
    setMessages(updatedMessages);
    setInput("");
    setAttachedFile(null);
    setIsStreaming(true);

    // Create assistant message placeholder
    const assistantMessage: ChatMessage = {
      role: "assistant",
      content: "",
      toolCalls: [],
      isStreaming: true,
    };

    setMessages([...updatedMessages, assistantMessage]);

    try {
      const chatHistory = updatedMessages.map((m) => ({
        role: m.role,
        content: m.content,
      }));

      let currentContent = "";
      const currentToolCalls: ToolCall[] = [];

      for await (const event of streamChat(chatHistory, claimId, abortRef.current?.signal)) {
        switch (event.type) {
          case "text_delta": {
            currentContent += event.content || "";
            setMessages((prev) => {
              const newMessages = [...prev];
              const last = newMessages[newMessages.length - 1];
              if (last.role === "assistant") {
                newMessages[newMessages.length - 1] = {
                  ...last,
                  content: currentContent,
                  toolCalls: [...currentToolCalls],
                  isStreaming: true,
                };
              }
              return newMessages;
            });
            break;
          }
          case "tool_call": {
            if (event.tool_call) {
              currentToolCalls.push({
                id: event.tool_call.id,
                name: event.tool_call.name,
                arguments: event.tool_call.arguments,
              });
              setMessages((prev) => {
                const newMessages = [...prev];
                const last = newMessages[newMessages.length - 1];
                if (last.role === "assistant") {
                  newMessages[newMessages.length - 1] = {
                    ...last,
                    content: currentContent,
                    toolCalls: [...currentToolCalls],
                    isStreaming: true,
                  };
                }
                return newMessages;
              });
            }
            break;
          }
          case "tool_result": {
            if (event.tool_result) {
              const idx = currentToolCalls.findIndex(
                (tc) => tc.id === event.tool_result!.id
              );
              if (idx >= 0) {
                currentToolCalls[idx] = {
                  ...currentToolCalls[idx],
                  result: event.tool_result.result,
                };
              }
              setMessages((prev) => {
                const newMessages = [...prev];
                const last = newMessages[newMessages.length - 1];
                if (last.role === "assistant") {
                  newMessages[newMessages.length - 1] = {
                    ...last,
                    content: currentContent,
                    toolCalls: [...currentToolCalls],
                    isStreaming: true,
                  };
                }
                return newMessages;
              });
            }
            break;
          }
          case "done": {
            setMessages((prev) => {
              const newMessages = [...prev];
              const last = newMessages[newMessages.length - 1];
              if (last.role === "assistant") {
                newMessages[newMessages.length - 1] = {
                  ...last,
                  content: currentContent,
                  toolCalls: [...currentToolCalls],
                  isStreaming: false,
                };
              }
              return newMessages;
            });
            break;
          }
          case "error": {
            setMessages((prev) => {
              const newMessages = [...prev];
              const last = newMessages[newMessages.length - 1];
              if (last.role === "assistant") {
                newMessages[newMessages.length - 1] = {
                  ...last,
                  content: event.error || "An error occurred.",
                  isStreaming: false,
                };
              }
              return newMessages;
            });
            break;
          }
        }
      }
    } catch (err) {
      setMessages((prev) => {
        const newMessages = [...prev];
        const last = newMessages[newMessages.length - 1];
        if (last.role === "assistant") {
          newMessages[newMessages.length - 1] = {
            ...last,
            content:
              err instanceof Error
                ? `Error: ${err.message}`
                : "An unexpected error occurred.",
            isStreaming: false,
          };
        }
        return newMessages;
      });
    } finally {
      isStreamingRef.current = false;
      setIsStreaming(false);
      inputRef.current?.focus();
    }
  }, [input, attachedFile, isStreaming, messages, claimId]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    dragCountRef.current++;
    if (dragCountRef.current === 1) {
      setIsDragging(true);
    }
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    dragCountRef.current--;
    if (dragCountRef.current === 0) {
      setIsDragging(false);
    }
  }, []);

  const handleDrop = useCallback((file: File) => {
    setAttachedFile(file);
    setIsDragging(false);
    dragCountRef.current = 0;
  }, []);

  const removeFile = useCallback(() => {
    setAttachedFile(null);
  }, []);

  const canSend = !isStreaming && (!!input.trim() || !!attachedFile);

  return (
    <div
      className="flex flex-col h-full relative"
      style={{ background: "var(--bg-base)" }}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={(e) => e.preventDefault()}
    >
      {/* Cursor blink keyframe */}
      <style>{`
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
      `}</style>

      <FileDropZone onFileDrop={handleDrop} isDragging={isDragging} />

      {/* ── Header ─────────────────────────────── */}
      <div
        className="px-4 py-3 flex items-center gap-2.5 flex-shrink-0"
        style={{ borderBottom: "1px solid var(--border-subtle)" }}
      >
        <MessageSquare
          className="w-4 h-4 flex-shrink-0"
          style={{ color: "var(--accent-primary)" }}
          aria-hidden="true"
        />
        <span className="type-subtitle" style={{ color: "var(--text-primary)" }}>
          Sovereign
        </span>

        {isStreaming && (
          <span
            className="ml-auto flex items-center gap-1.5"
            style={{ color: "var(--accent-primary)" }}
            aria-live="polite"
          >
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{
                background: "var(--accent-primary)",
                animation: "blink 1.2s ease-in-out infinite",
              }}
              aria-hidden="true"
            />
            <span className="type-caption" style={{ color: "var(--accent-primary)" }}>
              Thinking
            </span>
          </span>
        )}
      </div>

      {/* ── Messages ───────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-4 py-4 min-h-0" style={{ scrollbarWidth: "thin" }}>
        {messages.length === 0 ? (
          /* Empty state */
          <div className="h-full flex flex-col items-start justify-center gap-5 pb-2">
            <div>
              <p className="type-section-title mb-1" style={{ color: "var(--text-primary)" }}>
                Your medical billing advocate
              </p>
              <p className="type-body" style={{ color: "var(--text-secondary)" }}>
                Ask about a charge, upload a denial, or describe your situation.
              </p>
            </div>

            {/* Starter prompts */}
            <div className="flex flex-col gap-2 w-full">
              {STARTERS.map((s) => (
                <button
                  key={s}
                  onClick={() => handleSend(s)}
                  className="flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl text-left transition-colors group focus-ring"
                  style={{
                    background: "var(--bg-surface)",
                    border: "1px solid var(--border-subtle)",
                    color: "var(--text-secondary)",
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--border-default)";
                    (e.currentTarget as HTMLButtonElement).style.color = "var(--text-primary)";
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--border-subtle)";
                    (e.currentTarget as HTMLButtonElement).style.color = "var(--text-secondary)";
                  }}
                >
                  <ArrowRight
                    className="w-3.5 h-3.5 flex-shrink-0"
                    style={{ color: "var(--accent-primary)" }}
                    aria-hidden="true"
                  />
                  <span className="type-body-strong">{s}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {messages.map((msg, idx) => (
              <MessageBubble key={idx} message={msg} />
            ))}
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* ── Attached file pill ─────────────────── */}
      {attachedFile && (
        <div
          className="mx-4 mb-2 flex items-center gap-2 px-3 py-2 rounded-lg"
          style={{
            background: "var(--accent-primary-bg)",
            border: "1px solid var(--accent-primary-border)",
          }}
        >
          <Paperclip
            className="w-3.5 h-3.5 flex-shrink-0"
            style={{ color: "var(--accent-primary)" }}
            aria-hidden="true"
          />
          <span
            className="type-caption truncate flex-1"
            style={{ color: "var(--accent-primary)" }}
          >
            {attachedFile.name}
          </span>
          <button
            onClick={removeFile}
            aria-label="Remove attachment"
            className="flex-shrink-0 w-5 h-5 flex items-center justify-center rounded hover:opacity-70 focus-ring"
            style={{ color: "var(--accent-primary)" }}
          >
            <X className="w-3.5 h-3.5" aria-hidden="true" />
          </button>
        </div>
      )}

      {/* ── Input area ─────────────────────────── */}
      <div
        className="px-3 pb-3 pt-2 flex-shrink-0"
        style={{ borderTop: "1px solid var(--border-subtle)" }}
      >
        <div
          className="flex items-end gap-2 rounded-xl px-3 py-2.5 transition-colors"
          style={{
            background: "var(--bg-elevated)",
            border: "1px solid var(--border-default)",
          }}
        >
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your bill or denial…"
            rows={1}
            className="flex-1 bg-transparent text-sm resize-none focus:outline-none min-h-[22px] max-h-[112px]"
            style={{
              color: "var(--text-primary)",
              lineHeight: "1.5",
            }}
            onInput={(e) => {
              const el = e.currentTarget;
              el.style.height = "auto";
              el.style.height = Math.min(el.scrollHeight, 112) + "px";
            }}
            aria-label="Message Sovereign"
          />
          <button
            onClick={() => handleSend()}
            aria-label="Send message"
            disabled={!canSend}
            className="flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center btn-press focus-ring transition-colors"
            style={{
              background: canSend ? "var(--accent-primary)" : "var(--bg-overlay)",
              color: canSend ? "var(--bg-base)" : "var(--text-muted)",
              cursor: canSend ? "pointer" : "not-allowed",
            }}
          >
            <Send className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>
  );
}
