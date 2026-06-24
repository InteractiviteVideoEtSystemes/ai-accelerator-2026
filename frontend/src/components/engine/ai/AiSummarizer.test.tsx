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
      // The Storage upload contract: <uuid>/<filename>, correct content type, no
      // overwrite. A regression here would still render the mocked summary.
      const [uploadPath, uploadedFile, uploadOpts] = uploadMock.mock.calls[0];
      expect(uploadPath).toMatch(/\/doc\.txt$/);
      expect(uploadedFile).toBeInstanceOf(File);
      expect(uploadOpts).toMatchObject({ contentType: 'text/plain', upsert: false });

      // The create request must carry the full, correct payload and auth headers.
      const [createUrl, createInit] = fetchMock.mock.calls[0];
      expect(createUrl).toContain('/summaries');
      expect(createInit?.method).toBe('POST');
      expect(JSON.parse(createInit.body as string)).toEqual({
        storage_path: uploadPath,
        original_filename: 'doc.txt',
        mime_type: 'text/plain',
        size_bytes: 1024,
      });
      const headers = createInit.headers as Record<string, string>;
      expect(headers.Authorization).toBe('Bearer dev-anon-key');
      expect(headers.apikey).toBe('dev-anon-key');
      expect(headers['Content-Type']).toBe('application/json');

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

  it(
    'shows the intermediate "Summarizing" status while polling',
    async () => {
      const fetchMock = vi.fn();
      fetchMock
        .mockResolvedValueOnce(fetchResponse({ id: 'sum-3', status: 'uploaded' }, true, 201))
        .mockResolvedValue(fetchResponse({ id: 'sum-3', status: 'summarizing' }));
      vi.stubGlobal('fetch', fetchMock);
      const user = userEvent.setup();

      render(<AiSummarizer />);
      await user.upload(
        screen.getByLabelText(/Document/i),
        makeFile('doc.txt', 'text/plain', 1024),
      );
      await user.click(screen.getByRole('button', { name: /Summarize/i }));

      // The mapped status label is shown and the input is locked during processing.
      await waitFor(
        () => expect(screen.getByText('Summarizing')).toBeInTheDocument(),
        { timeout: 8000 },
      );
      expect(screen.getByLabelText(/Document/i)).toBeDisabled();
    },
    12000,
  );

  it(
    'retries a failed request and renders the new summary',
    async () => {
      let retried = false;
      const fetchMock = vi.fn(async (url: string, opts?: RequestInit) => {
        const method = opts?.method ?? 'GET';
        if (method === 'POST' && url.endsWith('/summaries')) {
          return fetchResponse({ id: 'sum-4', status: 'uploaded' }, true, 201);
        }
        if (method === 'POST' && url.includes('/retry')) {
          retried = true;
          return fetchResponse({ id: 'sum-4', status: 'uploaded' }, true, 200);
        }
        return retried
          ? fetchResponse({ id: 'sum-4', status: 'completed', summary: 'Recovered summary.' })
          : fetchResponse({ id: 'sum-4', status: 'failed', error_message: 'Provider error' });
      });
      vi.stubGlobal('fetch', fetchMock);
      const user = userEvent.setup();

      render(<AiSummarizer />);
      await user.upload(
        screen.getByLabelText(/Document/i),
        makeFile('doc.txt', 'text/plain', 1024),
      );
      await user.click(screen.getByRole('button', { name: /Summarize/i }));

      const retryButton = await screen.findByRole('button', { name: /Retry/i }, { timeout: 8000 });
      await user.click(retryButton);

      // A retry POST is issued to the {id}/retry endpoint...
      await waitFor(() =>
        expect(
          fetchMock.mock.calls.some(
            ([u, o]) => String(u).includes('/retry') && o?.method === 'POST',
          ),
        ).toBe(true),
      );
      // ...and polling resumes until the recovered summary appears.
      await waitFor(
        () => expect(screen.getByText('Recovered summary.')).toBeInTheDocument(),
        { timeout: 8000 },
      );
    },
    15000,
  );

  it(
    'copies the summary to the clipboard',
    async () => {
      const fetchMock = vi.fn();
      fetchMock
        .mockResolvedValueOnce(fetchResponse({ id: 'sum-5', status: 'uploaded' }, true, 201))
        .mockResolvedValue(
          fetchResponse({ id: 'sum-5', status: 'completed', summary: 'Copy me.' }),
        );
      vi.stubGlobal('fetch', fetchMock);
      const writeText = vi.spyOn(navigator.clipboard, 'writeText');
      const user = userEvent.setup();

      render(<AiSummarizer />);
      await user.upload(
        screen.getByLabelText(/Document/i),
        makeFile('doc.txt', 'text/plain', 1024),
      );
      await user.click(screen.getByRole('button', { name: /Summarize/i }));

      await waitFor(
        () => expect(screen.getByText('Copy me.')).toBeInTheDocument(),
        { timeout: 8000 },
      );
      await user.click(screen.getByRole('button', { name: /Copy/i }));

      expect(writeText).toHaveBeenCalledWith('Copy me.');
      expect(await screen.findByText(/Copied/i)).toBeInTheDocument();
    },
    12000,
  );

  it(
    'renders the summary as text, not HTML (XSS-safe)',
    async () => {
      const malicious = '<img src=x onerror="alert(1)">';
      const fetchMock = vi.fn();
      fetchMock
        .mockResolvedValueOnce(fetchResponse({ id: 'sum-6', status: 'uploaded' }, true, 201))
        .mockResolvedValue(
          fetchResponse({ id: 'sum-6', status: 'completed', summary: malicious }),
        );
      vi.stubGlobal('fetch', fetchMock);
      const user = userEvent.setup();

      const { container } = render(<AiSummarizer />);
      await user.upload(
        screen.getByLabelText(/Document/i),
        makeFile('doc.txt', 'text/plain', 1024),
      );
      await user.click(screen.getByRole('button', { name: /Summarize/i }));

      await waitFor(
        () => expect(screen.getByText(malicious)).toBeInTheDocument(),
        { timeout: 8000 },
      );
      // The payload is rendered as inert text; no <img> element is injected.
      expect(container.querySelector('img')).toBeNull();
    },
    12000,
  );
});
