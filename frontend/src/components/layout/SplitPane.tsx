import { useState, useRef, useEffect, useCallback, ReactNode } from 'react'

interface Props {
  left: ReactNode
  right: ReactNode
  initialRatio?: number
  minLeft?: number
  minRight?: number
  direction?: 'horizontal' | 'vertical'
}

export default function SplitPane({
  left, right, initialRatio = 0.6, minLeft = 200, minRight = 200, direction = 'horizontal'
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [ratio, setRatio] = useState(initialRatio)
  const dragging = useRef(false)

  const isHorizontal = direction === 'horizontal'

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dragging.current = true
    document.body.style.cursor = isHorizontal ? 'col-resize' : 'row-resize'
    document.body.style.userSelect = 'none'
  }, [isHorizontal])

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!dragging.current || !containerRef.current) return
    const rect = containerRef.current.getBoundingClientRect()
    const size = isHorizontal ? rect.width : rect.height
    const pos = isHorizontal ? e.clientX - rect.left : e.clientY - rect.top
    let newRatio = pos / size
    const minRatio = minLeft / size
    const maxRatio = 1 - minRight / size
    newRatio = Math.max(minRatio, Math.min(maxRatio, newRatio))
    setRatio(newRatio)
  }, [isHorizontal, minLeft, minRight])

  const handleMouseUp = useCallback(() => {
    dragging.current = false
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }, [])

  useEffect(() => {
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [handleMouseMove, handleMouseUp])

  const splitStyle = isHorizontal
    ? { width: `${ratio * 100}%`, minWidth: minLeft }
    : { height: `${ratio * 100}%`, minHeight: minLeft }

  return (
    <div
      ref={containerRef}
      className={`flex ${isHorizontal ? 'flex-row' : 'flex-col'} h-full w-full overflow-hidden`}
    >
      <div className="overflow-hidden" style={splitStyle}>
        {left}
      </div>
      <div
        onMouseDown={handleMouseDown}
        className={`shrink-0 bg-gray-200 hover:bg-primary-300 transition-colors z-10
          ${isHorizontal ? 'w-1.5 cursor-col-resize' : 'h-1.5 cursor-row-resize'}`}
      />
      <div className="flex-1 overflow-hidden min-w-0 min-h-0">
        {right}
      </div>
    </div>
  )
}
