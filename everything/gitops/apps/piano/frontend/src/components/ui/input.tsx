import * as React from "react"
import { Input as InputPrimitive } from "@base-ui/react/input"

import { cn } from "@/lib/utils"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <InputPrimitive
      type={type}
      data-slot="input"
      className={cn(
        "h-9 w-full min-w-0 rounded-md border border-toss-gray-200 bg-transparent px-3 py-1.5 text-sm transition-all outline-none file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-toss-gray-400 focus-visible:border-toss-blue focus-visible:ring-2 focus-visible:ring-toss-blue/20 disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-toss-gray-50 disabled:opacity-50 aria-invalid:border-toss-red aria-invalid:ring-2 aria-invalid:ring-toss-red/20 md:text-sm",
        className
      )}
      {...props}
    />
  )
}

export { Input }
