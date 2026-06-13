"use client";

import Image from "next/image";
import { useCallback, useState, useRef, useEffect } from "react";
import { Upload, File, X, Check } from "lucide-react";

interface FileUploadProps {
  onFileSelect: (file: File) => void;
  selectedFile: File | null;
  onRemove: () => void;
}

export default function FileUpload({
  onFileSelect,
  selectedFile,
  onRemove,
}: FileUploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    (file: File) => {
      onFileSelect(file);
      if (file.type.startsWith("image/")) {
        const url = URL.createObjectURL(file);
        setPreviewUrl((prev) => {
          if (prev) {
            URL.revokeObjectURL(prev);
          }

          return url;
        });
      } else {
        setPreviewUrl((prev) => {
          if (prev) {
            URL.revokeObjectURL(prev);
          }

          return null;
        });
      }
    },
    [onFileSelect]
  );

  useEffect(() => {
    return () => {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
    };
  }, [previewUrl]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const handleRemove = useCallback(() => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    onRemove();
    if (inputRef.current) inputRef.current.value = "";
  }, [previewUrl, onRemove]);

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  // ── Selected state ───────────────────────────
  if (selectedFile) {
    return (
      <div
        className="rounded-xl p-4 animate-fade-in"
        style={{
          background: "var(--bg-surface)",
          border: "1px solid var(--border-default)",
        }}
      >
        <div className="flex items-start gap-4">
          {/* Preview thumbnail or file icon */}
          {previewUrl ? (
            <div
              className="relative w-[72px] h-[72px] rounded-lg overflow-hidden flex-shrink-0"
              style={{
                background: "var(--bg-elevated)",
                border: "1px solid var(--border-subtle)",
              }}
            >
              <Image
                src={previewUrl}
                alt="Preview"
                fill
                unoptimized
                sizes="72px"
                className="object-cover"
              />
            </div>
          ) : (
            <div
              className="w-[72px] h-[72px] rounded-lg flex-shrink-0 flex items-center justify-center"
              style={{
                background: "var(--bg-elevated)",
                border: "1px solid var(--border-subtle)",
              }}
            >
              <File
                className="w-7 h-7"
                style={{ color: "var(--text-muted)" }}
                aria-hidden="true"
              />
            </div>
          )}

          {/* File metadata */}
          <div className="flex-1 min-w-0 pt-0.5">
            <p
              className="type-body-strong truncate"
              style={{ color: "var(--text-primary)" }}
              title={selectedFile.name}
            >
              {selectedFile.name}
            </p>
            <p
              className="type-caption mt-1"
              style={{ color: "var(--text-secondary)" }}
            >
              {formatFileSize(selectedFile.size)}
              {selectedFile.type ? ` · ${selectedFile.type.split("/")[1]?.toUpperCase() ?? selectedFile.type}` : ""}
            </p>
            <div
              className="flex items-center gap-1.5 mt-2.5"
              style={{ color: "var(--risk-low)" }}
            >
              <Check className="w-3.5 h-3.5" aria-hidden="true" />
              <span className="type-caption" style={{ color: "var(--risk-low)" }}>
                Ready to submit
              </span>
            </div>
          </div>

          {/* Remove button */}
          <button
            type="button"
            onClick={handleRemove}
            aria-label="Remove selected file"
            className="flex-shrink-0 rounded-lg flex items-center justify-center transition-colors hover:opacity-70 focus-ring"
            style={{
              color: "var(--text-muted)",
              minWidth: 44,
              minHeight: 44,
            }}
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
      </div>
    );
  }

  // ── Drop zone (no file selected) ─────────────
  return (
    <div
      role="button"
      tabIndex={0}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          inputRef.current?.click();
        }
      }}
      className="relative border-2 border-dashed rounded-xl cursor-pointer transition-all focus-ring"
      style={{
        borderColor: isDragging ? "var(--accent-primary)" : "var(--border-default)",
        background: isDragging ? "var(--accent-primary-bg)" : "var(--bg-surface)",
        boxShadow: isDragging ? "0 0 0 4px var(--accent-primary-border)" : "none",
        padding: "2.5rem 2rem",
      }}
      aria-label="Upload medical bill or supporting document (image or PDF, up to 10 MB)"
    >
      <input
        ref={inputRef}
        type="file"
        onChange={handleInputChange}
        accept="image/*,.pdf"
        aria-label="Upload medical bill or supporting document (image or PDF, up to 10 MB)"
        className="hidden"
        tabIndex={-1}
      />

      <div className="flex flex-col items-center gap-3 text-center">
        {/* Icon */}
        <div
          className="w-12 h-12 rounded-xl flex items-center justify-center transition-colors"
          style={{
            background: isDragging ? "var(--accent-primary-bg)" : "var(--bg-elevated)",
            border: `1px solid ${isDragging ? "var(--accent-primary-border)" : "var(--border-default)"}`,
          }}
          aria-hidden="true"
        >
          <Upload
            className="w-5 h-5 transition-colors"
            style={{ color: isDragging ? "var(--accent-primary)" : "var(--text-secondary)" }}
          />
        </div>

        {/* Primary line */}
        <div>
          <p className="type-body-strong" style={{ color: "var(--text-primary)" }}>
            <span style={{ color: "var(--accent-primary)" }}>Click to upload</span>
            {" "}or drag and drop
          </p>
          <p className="type-caption mt-1" style={{ color: "var(--text-muted)" }}>
            PDF, PNG, JPG, WEBP — up to 10 MB
          </p>
        </div>
      </div>
    </div>
  );
}
