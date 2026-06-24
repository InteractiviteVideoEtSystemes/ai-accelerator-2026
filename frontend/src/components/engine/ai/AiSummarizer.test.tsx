/**
 * Unit tests for the AiSummarizer component (Vitest + Testing Library).
 *
 * Storage upload (supabase) and the Edge Function calls (fetch) are mocked so the
 * tests are deterministic and offline: they cover client-side validation, the
 * upload -> create -> poll happy path, the completed-summary rendering, and the
 * failed -> retry path. Real timers are used (the component polls every 2.5s), so
 * the flow tests raise their per-test timeout.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const uploadMock = vi.fn();

vi.mock('@/data/supabase', () => ({
  supabase: {
    storage: {
      from: () => ({ upload: uploadMock }),
    },
  },
}));

import { AiSummarizer } from './AiSummarizer';

function makeFile(name: string, type: string, sizeBytes: number): File {
  const file = new File(['x'], name, { type });
  Object.defineProperty(file, 'size', { value: sizeBytes });
  return file;
}

function fetchResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => body } as Response;
}

beforeEach(() => {
  uploadMock.mockReset();
  uploadMock.mockResolvedValue({ error: null });
});

describe('AiSummarizer validation', () => {
  it('rejects an unsupported file type', async () => {
    render(<AiSummarizer />);
    // fireEvent.change bypasses the input's accept filter so the component's own
    // validation runs (that is what we are testing).
    fireEvent.change(screen.getByLabelText(/Document/i), {
      target: { files: [makeFile('image.png', 'image/png', 1000)] },
    });

    expect(await screen.findByText(/Unsupported file type/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Summarize/i })).toBeDisabled();
  });

  it('rejects a file larger than 512 KB', async () => {
    const user = userEvent.setup();
    render(<AiSummarizer />);
    await user.upload(
      screen.getByLabelText(/Document/i),
      makeFile('big.txt', 'text/plain', 512 * 1024 + 1),
    );

    expect(await screen.findByText(/larger than the 512 KB limit/i)).toBeInTheDocument();
  });

  it('accepts a valid file and enables the Summarize button', async () => {
    const user = userEvent.setup();
    render(<AiSummarizer />);
    await user.upload(
      screen.getByLabelText(/Document/i),
      makeFile('doc.txt', 'text/plain', 1024),
    );

    expect(screen.getByText(/doc\.txt/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Summarize/i })).toBeEnabled();
  });
});

describe('AiSummarizer flow', () => {
  it(
    'uploads, creates a request, polls, and renders the completed summary',
    async () => {
      const fetchMock = vi.fn();
      // 1) POST /summaries -> created (uploaded). 2+) GET poll -> completed.
      fetchMock
        .mockResolvedValueOnce(fetchResponse({ id: 'sum-1', status: 'uploaded' }, true, 201))
        .mockResolvedValue(
          fetchResponse({ id: 'sum-1', status: 'completed', summary: 'An English summary.' }),
        );
      vi.stubGlobal('fetch', fetchMock);
      const user = userEvent.setup();

      render(<AiSummarizer />);
      await user.upload(
        screen.getByLabelText(/Document/i),
        makeFile('doc.txt', 'text/plain', 1024),
      );
      await user.click(screen.getByRole('button', { name: /Summarize/i }));

      expect(uploadMock).toHaveBeenCalledOnce();
      expect(fetchMock.mock.calls[0][0]).toContain('/summaries');
      expect(fetchMock.mock.calls[0][1]?.method).toBe('POST');

      await waitFor(
        () => expect(screen.getByText('An English summary.')).toBeInTheDocument(),
        { timeout: 8000 },
      );
      expect(screen.getByRole('button', { name: /Copy/i })).toBeInTheDocument();
    },
    12000,
  );

  it(
    'shows an error and a Retry button when the request fails',
    async () => {
      const fetchMock = vi.fn();
      fetchMock
        .mockResolvedValueOnce(fetchResponse({ id: 'sum-2', status: 'uploaded' }, true, 201))
        .mockResolvedValue(
          fetchResponse({ id: 'sum-2', status: 'failed', error_message: 'Provider error' }),
        );
      vi.stubGlobal('fetch', fetchMock);
      const user = userEvent.setup();

      render(<AiSummarizer />);
      await user.upload(
        screen.getByLabelText(/Document/i),
        makeFile('doc.txt', 'text/plain', 1024),
      );
      await user.click(screen.getByRole('button', { name: /Summarize/i }));

      await waitFor(
        () => expect(screen.getByText('Provider error')).toBeInTheDocument(),
        { timeout: 8000 },
      );
      expect(screen.getByRole('button', { name: /Retry/i })).toBeInTheDocument();
    },
    12000,
  );
});
