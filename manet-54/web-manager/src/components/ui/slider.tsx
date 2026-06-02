import * as React from "react"
import { cn } from "@/lib/utils"

export interface SliderProps {
  value?: number[]
  onValueChange?: (value: number[]) => void
  min?: number
  max?: number
  step?: number
  className?: string
  disabled?: boolean
}

const Slider = React.forwardRef<HTMLDivElement, SliderProps>(
  ({ value = [0], onValueChange, min = 0, max = 100, step = 1, className, disabled }, ref) => {
    const [local, setLocal] = React.useState(value)
    const v = value ?? local

    const handleChange = (newVal: number) => {
      setLocal([newVal])
      onValueChange?.([newVal])
    }

    const pct = ((v[0] - min) / (max - min)) * 100

    return (
      <div
        ref={ref}
        className={cn("relative flex w-full touch-none select-none items-center", className)}
      >
        <div className="relative h-2 w-full rounded-full bg-muted">
          <div
            className="absolute h-full rounded-full bg-primary"
            style={{ width: `${pct}%` }}
          />
        </div>
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={v[0]}
          onChange={(e) => handleChange(Number(e.target.value))}
          disabled={disabled}
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer disabled:cursor-not-allowed"
        />
        <div
          className="block h-5 w-5 rounded-full border-2 border-primary bg-background shadow transition-colors"
          style={{ left: `calc(${pct}% - 10px)` }}
        />
      </div>
    )
  }
)
Slider.displayName = "Slider"

export { Slider }