"use client";

import React from "react";

/**
 * Lightweight Markdown renderer for song analysis/practice content.
 * Supports: ## h2, ### h3, **bold**, - list items, numbered lists, blank lines.
 */

function renderInline(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  const regex = /\*\*(.+?)\*\*/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    parts.push(
      <strong key={match.index} className="font-semibold text-toss-gray-900">
        {match[1]}
      </strong>
    );
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length > 0 ? parts : [text];
}

export function MarkdownRenderer({
  content,
  className = "",
}: {
  content: string;
  className?: string;
}) {
  const lines = content.split("\n");
  const elements: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Blank line
    if (line.trim() === "") {
      i++;
      continue;
    }

    // ## Heading 2
    if (line.startsWith("## ")) {
      elements.push(
        <h2
          key={i}
          className="text-lg font-semibold text-toss-gray-900 mt-6 mb-3 pb-2 border-b border-toss-gray-100 first:mt-0"
        >
          {line.slice(3)}
        </h2>
      );
      i++;
      continue;
    }

    // ### Heading 3
    if (line.startsWith("### ")) {
      elements.push(
        <h3
          key={i}
          className="text-base font-semibold text-toss-gray-800 mt-4 mb-2"
        >
          {renderInline(line.slice(4))}
        </h3>
      );
      i++;
      continue;
    }

    // Unordered list: collect consecutive - items
    if (line.startsWith("- ")) {
      const items: { key: number; text: string }[] = [];
      while (i < lines.length && lines[i].startsWith("- ")) {
        items.push({ key: i, text: lines[i].slice(2) });
        i++;
      }
      elements.push(
        <ul key={`ul-${items[0].key}`} className="space-y-1.5 mb-3">
          {items.map((item) => (
            <li key={item.key} className="flex gap-2 items-start">
              <span className="text-toss-blue mt-1.5 shrink-0">
                <svg width="6" height="6" viewBox="0 0 6 6" fill="currentColor">
                  <circle cx="3" cy="3" r="3" />
                </svg>
              </span>
              <span className="text-sm text-toss-gray-600 leading-relaxed">
                {renderInline(item.text)}
              </span>
            </li>
          ))}
        </ul>
      );
      continue;
    }

    // Numbered list: collect consecutive N. items
    if (/^\d+\.\s/.test(line)) {
      const items: { key: number; num: string; text: string }[] = [];
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
        const m = lines[i].match(/^(\d+)\.\s(.*)/)!;
        items.push({ key: i, num: m[1], text: m[2] });
        i++;
      }
      elements.push(
        <ol key={`ol-${items[0].key}`} className="space-y-2 mb-3">
          {items.map((item) => (
            <li
              key={item.key}
              className="flex gap-3 items-start p-3 rounded-xl bg-toss-gray-50"
            >
              <span className="bg-toss-blue text-white text-xs font-semibold w-5 h-5 rounded-full flex items-center justify-center shrink-0 mt-0.5">
                {item.num}
              </span>
              <span className="text-sm text-toss-gray-700 leading-relaxed">
                {renderInline(item.text)}
              </span>
            </li>
          ))}
        </ol>
      );
      continue;
    }

    // Regular paragraph
    elements.push(
      <p key={i} className="text-sm text-toss-gray-600 leading-relaxed mb-2">
        {renderInline(line)}
      </p>
    );
    i++;
  }

  return <div className={`space-y-0 ${className}`}>{elements}</div>;
}
