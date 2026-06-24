/**
 * Global test setup: jest-dom matchers plus small browser-API polyfills that
 * jsdom does not implement but the components rely on (crypto.randomUUID for
 * Storage paths and navigator.clipboard for the "Copy" action).
 */
import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

if (!globalThis.crypto?.randomUUID) {
  // @ts-expect-error - minimal polyfill for jsdom
  globalThis.crypto = {
    ...globalThis.crypto,
    randomUUID: () => '00000000-0000-4000-8000-000000000000',
  };
}

if (!navigator.clipboard) {
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    configurable: true,
  });
}
