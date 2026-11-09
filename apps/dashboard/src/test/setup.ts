import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// jsdom lacks these browser APIs that the UI primitives rely on.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.matchMedia ??= ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addEventListener() {},
  removeEventListener() {},
  addListener() {},
  removeListener() {},
  dispatchEvent: () => false,
})) as typeof window.matchMedia
Element.prototype.scrollTo ??= () => {}
Element.prototype.scrollIntoView ??= () => {}

afterEach(() => {
  cleanup()
  sessionStorage.clear()
})

// jsdom has no PointerEvent; Base UI's Switch dispatches one when clicked.
if (typeof window !== 'undefined' && !('PointerEvent' in window)) {
  ;(window as unknown as { PointerEvent: typeof MouseEvent }).PointerEvent = MouseEvent
}
