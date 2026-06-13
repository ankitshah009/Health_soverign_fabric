"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  FilePlus,
  FileStack,
  Pin,
  PinOff,
  Menu,
  X,
} from "lucide-react";
import { SovereignMark } from "./Logo";

const navItems = [
  { label: "Dashboard", href: "/", icon: LayoutDashboard },
  { label: "Submit Case", href: "/claims/submit", icon: FilePlus },
  { label: "All Cases", href: "/claims", icon: FileStack },
];

export default function Sidebar() {
  const pathname = usePathname();
  const [isHovered, setIsHovered] = useState(false);
  const [isPinned, setIsPinned] = useState(() => {
    if (typeof window === "undefined") {
      return false;
    }

    try {
      return localStorage.getItem("sidebar-pinned") === "true";
    } catch {
      return false;
    }
  });
  const [isMobileOpen, setIsMobileOpen] = useState(false);

  useEffect(() => {
    document.documentElement.style.setProperty(
      "--sidebar-width",
      isPinned ? "240px" : "64px"
    );

    return () => {
      document.documentElement.style.removeProperty("--sidebar-width");
    };
  }, [isPinned]);

  const togglePin = useCallback(() => {
    setIsPinned((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("sidebar-pinned", String(next));
      } catch {
        // localStorage unavailable
      }
      return next;
    });
  }, []);

  const isExpanded = isHovered || isPinned;

  return (
    <>
      {/* Mobile hamburger */}
      <button
        data-testid="sidebar-mobile-toggle"
        aria-label={isMobileOpen ? "Close navigation menu" : "Open navigation menu"}
        aria-expanded={isMobileOpen}
        aria-controls="sidebar"
        className="fixed top-4 left-4 z-[60] md:hidden w-11 h-11 rounded-lg flex items-center justify-center"
        style={{
          background: "var(--bg-surface)",
          border: "1px solid var(--border-subtle)",
          color: "var(--text-primary)",
        }}
        onClick={() => setIsMobileOpen(!isMobileOpen)}
      >
        {isMobileOpen ? <X size={20} aria-hidden="true" /> : <Menu size={20} aria-hidden="true" />}
      </button>

      {/* Mobile overlay */}
      {isMobileOpen && (
        <div
          className="fixed inset-0 z-40 md:hidden"
          style={{ background: "rgba(20,23,30,0.38)" }}
          onClick={() => setIsMobileOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        id="sidebar"
        data-testid="sidebar"
        aria-label="Main navigation"
        className={`fixed left-0 top-0 h-screen flex flex-col z-50 transition-all duration-300 ease-out
          ${isMobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"}`}
        style={{
          width: isExpanded ? 240 : 64,
          background: "var(--bg-surface)",
          borderRight: "1px solid var(--border-subtle)",
        }}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
      >
        {/* Branding */}
        <div
          className="p-3 flex items-center gap-3 h-16 flex-shrink-0"
          style={{ borderBottom: "1px solid var(--border-subtle)" }}
        >
          <SovereignMark size={40} variant="icon" />
          <div
            className="overflow-hidden transition-all duration-300"
            style={{
              width: isExpanded ? 140 : 0,
              opacity: isExpanded ? 1 : 0,
            }}
          >
            <h1
              className="text-base font-bold tracking-tight whitespace-nowrap"
              style={{ color: "var(--text-primary)" }}
            >
              Sovereign
            </h1>
            <p
              className="text-[10px] font-bold tracking-[0.15em] uppercase whitespace-nowrap"
              style={{ color: "var(--accent-primary)" }}
            >
              Patient Advocate
            </p>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-2 space-y-1">
          {navItems.map((item) => {
            const isActive =
              item.href === "/"
                ? pathname === "/"
                : pathname.startsWith(item.href);
            const Icon = item.icon;

            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setIsMobileOpen(false)}
                aria-label={item.label}
                aria-current={isActive ? "page" : undefined}
                className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 group relative"
                style={{
                  color: isActive ? "var(--accent-primary)" : "var(--text-secondary)",
                  background: isActive ? "var(--accent-primary-bg)" : "transparent",
                }}
              >
                {isActive && (
                  <div
                    className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full"
                    style={{ background: "var(--accent-primary)" }}
                  />
                )}
                <Icon
                  size={20}
                  aria-hidden="true"
                  className="flex-shrink-0 transition-colors"
                  style={{
                    color: isActive ? "var(--accent-primary)" : "var(--text-muted)",
                  }}
                />
                <span
                  className="overflow-hidden transition-all duration-300 whitespace-nowrap"
                  style={{
                    width: isExpanded ? 140 : 0,
                    opacity: isExpanded ? 1 : 0,
                  }}
                >
                  {item.label}
                </span>
              </Link>
            );
          })}
        </nav>

        {/* Footer */}
        <div
          className="p-3 flex-shrink-0"
          style={{ borderTop: "1px solid var(--border-subtle)" }}
        >
          {/* Pin button - only show when expanded */}
          {isExpanded && (
            <button
              data-testid="sidebar-pin"
              onClick={togglePin}
              aria-label={isPinned ? "Unpin sidebar — allow it to collapse" : "Pin sidebar — keep it expanded"}
              aria-pressed={isPinned}
              className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-xs transition-colors mb-2"
              style={{
                color: isPinned ? "var(--accent-primary)" : "var(--text-muted)",
                background: isPinned ? "var(--accent-primary-bg)" : "transparent",
              }}
            >
              {isPinned ? <PinOff size={14} aria-hidden="true" /> : <Pin size={14} aria-hidden="true" />}
              <span>{isPinned ? "Unpin sidebar" : "Pin sidebar"}</span>
            </button>
          )}

          <div className="flex items-center gap-2 px-3">
            <div
              className="w-2 h-2 rounded-full flex-shrink-0 animate-pulse"
              style={{ background: "var(--risk-low)" }}
            />
            {isExpanded && (
              <span
                className="text-xs whitespace-nowrap transition-opacity duration-300"
                style={{ color: "var(--text-muted)" }}
              >
                System Online
              </span>
            )}
          </div>
        </div>
      </aside>
    </>
  );
}
