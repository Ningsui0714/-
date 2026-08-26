import type { KeyboardEvent as ReactKeyboardEvent } from 'react'

/**
 * Return true only when Enter is an intentional send action.
 *
 * Chinese/Japanese/Korean IMEs also emit Enter while confirming a candidate.
 * `isComposing` is the standards-based signal; keyCode 229 keeps the guard
 * reliable in Safari/WebKit where compositionend and keydown can be reordered.
 */
export function shouldSendMessageOnEnter<ElementType extends HTMLElement>(
  event: ReactKeyboardEvent<ElementType>,
) {
  const nativeEvent = event.nativeEvent
  return event.key === 'Enter'
    && !event.shiftKey
    && !nativeEvent.isComposing
    && nativeEvent.keyCode !== 229
}
