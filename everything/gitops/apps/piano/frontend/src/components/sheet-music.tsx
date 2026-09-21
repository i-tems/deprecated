"use client";

import { useEffect, useRef } from "react";

interface SheetSnippet {
  title: string;
  abc: string;
  description?: string;
}

function SheetSnippetCard({ snippet }: { snippet: SheetSnippet }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let mounted = true;
    import("abcjs").then((abcjs) => {
      if (mounted && ref.current) {
        abcjs.renderAbc(ref.current, snippet.abc, {
          responsive: "resize",
          staffwidth: 500,
          paddingtop: 0,
          paddingbottom: 0,
          paddingleft: 0,
          paddingright: 0,
        });
      }
    });
    return () => {
      mounted = false;
    };
  }, [snippet.abc]);

  return (
    <div className="border border-toss-gray-100 rounded-xl p-4 space-y-2">
      <h3 className="text-sm font-semibold text-toss-gray-800">
        {snippet.title}
      </h3>
      <div
        ref={ref}
        className="overflow-x-auto [&_svg]:max-w-full [&_svg]:h-auto"
      />
      {snippet.description && (
        <p className="text-xs text-toss-gray-500 leading-relaxed">
          {snippet.description}
        </p>
      )}
    </div>
  );
}

export function SheetMusicSection({
  snippets,
}: {
  snippets: SheetSnippet[];
}) {
  return (
    <div className="bg-card rounded-xl p-6 border border-border">
      <h2 className="text-base font-semibold text-toss-gray-900 mb-4">
        주요 악보 구절
      </h2>
      <div className="space-y-4">
        {snippets.map((snippet, i) => (
          <SheetSnippetCard key={i} snippet={snippet} />
        ))}
      </div>
    </div>
  );
}
