import * as React from "react"

import { cn } from "@/lib/utils"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex field-sizing-content min-h-16 w-full rounded-md border border-toss-gray-200 bg-transparent px-3 py-2 text-sm transition-all outline-none placeholder:text-toss-gray-400 focus-visible:border-toss-blue focus-visible:ring-2 focus-visible:ring-toss-blue/20 disabled:cursor-not-allowed disabled:bg-toss-gray-50 disabled:opacity-50 aria-invalid:border-toss-red aria-invalid:ring-2 aria-invalid:ring-toss-red/20 md:text-sm",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
