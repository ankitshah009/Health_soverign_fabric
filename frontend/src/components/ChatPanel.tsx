"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { streamChat } from "@/lib/api";
import { ChatMessage, ToolCall } from "@/lib/types";
import { MessageSquare, Send, Paperclip, ChevronDown, X, Sparkles } from "lucide-react";

interface ChatPanelProps {
  claimId?: string;
}

function ToolCallCard({ toolCall }: { toolCall: ToolCall }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className="glass-panel p-3 my-2 cursor-pointer transition-all"
      onClick={() => setExpanded(!expanded)}
      role="button"
      tabIndex={0}
      aria-expanded={expanded}
      aria-label={`Tool call: ${toolCall.name}. Click to ${expanded ? "collapse" : "expand"} details.`}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setExpanded(!expanded); } }}
    >
      <div className="flex items-center gap-2">
        <div
          className="w-6 h-6 rounded flex items-center justify-center flex-shrink-0"
          style={{ background: "var(--accent-primary-bg)" }}
        >
          <ChevronDown
            className={`w-3.5 h-3.5 transition-transform ${expanded ? "rotate-180" : ""}`}
            style={{ color: "var(--accent-primary)" }}
            aria-hidden="true"
          />
        </div>

        <span
          className="text-xs font-mono font-medium"
          style={{ color: "var(--accent-primary)" }}
        >
          {toolCall.name}
        </span>
        {toolCall.result && (
          <span
            className="ml-auto text-xs"
            style={{ color: "var(--risk-low)" }}
          >
            Done
          </span>
        )}
      </div>
      {expanded && (
        <div className="mt-2 space-y-2">
          {Object.keys(toolCall.arguments).length > 0 && (
            <div
              className="rounded p-2 text-xs font-mono overflow-x-auto"
              style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)" }}
            >
              {Object.entries(toolCall.arguments).map(([key, val]) => (
                <div key={key}>
                  <span style={{ color: "var(--text-muted)" }}>{key}:</span>{" "}
                  <span style={{ color: "var(--text-primary)" }}>
                    {typeof val === "object" ? JSON.stringify(val) : String(val)}
                  </span>
                </div>
              ))}
            </div>
          )}
          {toolCall.result && (
            <div
              className="rounded p-2 text-xs font-mono overflow-x-auto max-h-32 overflow-y-auto"
              style={{
                background: "var(--risk-low-bg)",
                border: "1px solid var(--risk-low-border)",
                color: "var(--text-primary)",
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
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} animate-fade-in`}>
      <div
        className={`max-w-[85%] rounded-xl px-4 py-2.5 text-sm ${isUser ? "rounded-br-sm" : "rounded-bl-sm"}`}
        style={{
          background: isUser ? "var(--accent-primary)" : "var(--bg-surface)",
          color: isUser ? "var(--bg-base)" : "var(--text-primary)",
          border: isUser ? "none" : "1px solid var(--glass-border)",
          backdropFilter: isUser ? "none" : "blur(8px)",
        }}
      >
        <div className="whitespace-pre-wrap break-words">
          {message.content}
          {message.isStreaming && (
            <span
              className="inline-block w-0.5 h-4 ml-0.5 align-text-bottom"
              style={{
                background: isUser ? "var(--bg-base)" : "var(--accent-primary)",
                animation: "blink 1s step-end infinite",
              }}
            />
          )}
        </div>
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="mt-2">
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
        background: "rgba(9, 9, 11, 0.9)",
        border: "2px dashed var(--accent-primary)",
      }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        const file = e.dataTransfer.files[0];
        if (file) onFileDrop(file);
      }}
    >
      <div className="text-center">
        <Paperclip
          className="w-10 h-10 mx-auto mb-2"
          style={{ color: "var(--accent-primary)" }}
        />
        <p className="text-sm font-medium" style={{ color: "var(--accent-primary)" }}>
          Drop medical bill or EOB here
        </p>
      </div>
    </div>
  );
}

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

  const handleSend = useCallback(async () => {
    if (isStreamingRef.current) return;
    const trimmed = input.trim();
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

  return (
    <div
      className="flex flex-col h-full relative"
      style={{
        background: "var(--bg-base)",
      }}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={(e) => e.preventDefault()}
    >
      {/* Blink cursor keyframe */}
      <style>{`
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
      `}</style>

      <FileDropZone onFileDrop={handleDrop} isDragging={isDragging} />

      {/* Header */}
      <div
        className="px-4 py-3 flex items-center gap-2 flex-shrink-0"
        style={{ borderBottom: "1px solid var(--border-subtle)" }}
      >
        <MessageSquare
          className="w-4 h-4"
          style={{ color: "var(--accent-primary)" }}
        />
        <span
          className="text-sm font-semibold"
          style={{ color: "var(--text-primary)" }}
        >
          Sovereign Assistant
        </span>
        {isStreaming && (
          <span
            className="ml-auto flex items-center gap-1.5 text-xs"
            style={{ color: "var(--accent-primary)" }}
          >
            <span
              className="w-1.5 h-1.5 rounded-full animate-pulse"
              style={{ background: "var(--accent-primary)" }}
            />
            Thinking
          </span>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 min-h-0">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <div
                className="w-12 h-12 rounded-full flex items-center justify-center mx-auto mb-3"
                style={{ background: "var(--accent-primary-bg)" }}
              >
                <Sparkles
                  className="w-6 h-6"
                  style={{ color: "var(--accent-primary)" }}
                />
              </div>
              <p
                className="text-sm font-medium mb-1"
                style={{ color: "var(--text-primary)" }}
              >
                Sovereign Patient Advocate
              </p>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                Ask about your bill, request an overcharge analysis, or upload documents.
              </p>
            </div>
          </div>
        )}
        {messages.map((msg, idx) => (
          <MessageBubble key={idx} message={msg} />
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Attached file indicator */}
      {attachedFile && (
        <div
          className="mx-4 mb-1 flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs"
          style={{
            background: "var(--accent-primary-bg)",
            border: "1px solid var(--accent-primary-border)",
            color: "var(--accent-primary)",
          }}
        >
          <Paperclip className="w-3.5 h-3.5 flex-shrink-0" />
          <span className="truncate">{attachedFile.name}</span>
          <button
            onClick={removeFile}
            aria-label="Remove attachment"
            className="ml-auto flex-shrink-0 hover:opacity-75"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
      )}

      {/* Input area */}
      <div
        className="px-3 py-3 flex-shrink-0"
        style={{ borderTop: "1px solid var(--border-subtle)" }}
      >
        <div
          className="flex items-end gap-2 rounded-lg px-3 py-2"
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
            placeholder="Ask about your bill or denial..."
            rows={1}
            className="flex-1 bg-transparent text-sm resize-none focus:outline-none min-h-[24px] max-h-[120px]"
            style={{ color: "var(--text-primary)" }}
            onInput={(e) => {
              const el = e.currentTarget;
              el.style.height = "auto";
              el.style.height = Math.min(el.scrollHeight, 120) + "px";
            }}
          />
          <button
            onClick={handleSend}
            aria-label="Send message"
            disabled={isStreaming || (!input.trim() && !attachedFile)}
            className="flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center transition-colors"
            style={{
              background:
                isStreaming || (!input.trim() && !attachedFile)
                  ? "var(--bg-overlay)"
                  : "var(--accent-primary)",
              color:
                isStreaming || (!input.trim() && !attachedFile)
                  ? "var(--text-muted)"
                  : "var(--bg-base)",
              cursor:
                isStreaming || (!input.trim() && !attachedFile)
                  ? "not-allowed"
                  : "pointer",
            }}
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
