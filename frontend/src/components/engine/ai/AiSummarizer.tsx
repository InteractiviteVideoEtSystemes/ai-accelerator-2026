/**
 * AiSummarizer - interactive component for the AI document summarization feature.
 *
 * Flow: pick a French .pdf/.docx/.txt (<=512 KB) -> upload to the private
 * `documents` Storage bucket -> POST to the `summaries` Edge Function -> poll its
 * status until `completed`/`failed` -> render the English summary.
 *
 * Registered as the `AiSummarizer` engine component and placed by
 * pages/ai-summarize.json.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { supabase } from '@/data/supabase';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { AlertCircle, CheckCircle, Copy, FileText, Loader2 } from 'lucide-react';

const MAX_BYTES = 512 * 1024; // 512 KB
const BUCKET = 'documents';
const POLL_MS = 2500;

const ALLOWED: Record<string, string> = {
  'application/pdf': '.pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
  'text/plain': '.txt',
};

const API_BASE =
  (import.meta.env.VITE_API_URL as string | undefined) ||
  'http://localhost:54321/functions/v1';
const ANON_KEY =
  (import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined) || 'dev-anon-key';

type Status = 'idle' | 'uploaded' | 'extracting' | 'summarizing' | 'completed' | 'failed';

interface SummaryRecord {
  id: string;
  status: Status;
  summary?: string | null;
  error_message?: string | null;
}

const ACTIVE: Status[] = ['uploaded', 'extracting', 'summarizing'];

const STATUS_LABEL: Record<Status, string> = {
  idle: 'Idle',
  uploaded: 'Queued',
  extracting: 'Extracting text',
  summarizing: 'Summarizing',
  completed: 'Completed',
  failed: 'Failed',
};

function apiHeaders(): HeadersInit {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${ANON_KEY}`,
    apikey: ANON_KEY,
  };
}

export function AiSummarizer() {
  const [file, setFile] = useState<File | null>(null);
  const [clientError, setClientError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [record, setRecord] = useState<SummaryRecord | null>(null);
  const [copied, setCopied] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setClientError(null);
    const selected = e.target.files?.[0] ?? null;
    if (selected) {
      if (!ALLOWED[selected.type]) {
        setClientError('Unsupported file type. Use a PDF, DOCX, or TXT document.');
        setFile(null);
        return;
      }
      if (selected.size > MAX_BYTES) {
        setClientError('File is larger than the 512 KB limit.');
        setFile(null);
        return;
      }
    }
    setFile(selected);
  };

  const poll = useCallback(
    (id: string) => {
      stopPolling();
      pollRef.current = setInterval(async () => {
        try {
          const res = await fetch(`${API_BASE}/summaries/${id}`, {
            headers: apiHeaders(),
          });
          if (!res.ok) return;
          const data = (await res.json()) as SummaryRecord;
          setRecord(data);
          if (!ACTIVE.includes(data.status)) stopPolling();
        } catch {
          /* transient: keep polling */
        }
      }, POLL_MS);
    },
    [stopPolling],
  );

  const onSubmit = async () => {
    if (!file) return;
    setBusy(true);
    setClientError(null);
    setRecord(null);
    setCopied(false);
    try {
      const path = `${crypto.randomUUID()}/${file.name}`;
      const { error: uploadError } = await supabase.storage
        .from(BUCKET)
        .upload(path, file, { contentType: file.type, upsert: false });
      if (uploadError) throw new Error(`Upload failed: ${uploadError.message}`);

      const res = await fetch(`${API_BASE}/summaries`, {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify({
          storage_path: path,
          original_filename: file.name,
          mime_type: file.type,
          size_bytes: file.size,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `Request failed (${res.status})`);
      }
      const data = (await res.json()) as SummaryRecord;
      setRecord(data);
      poll(data.id);
    } catch (e) {
      setClientError(e instanceof Error ? e.message : 'Something went wrong.');
    } finally {
      setBusy(false);
    }
  };

  const onRetry = async () => {
    if (!record) return;
    try {
      const res = await fetch(`${API_BASE}/summaries/${record.id}/retry`, {
        method: 'POST',
        headers: apiHeaders(),
      });
      if (!res.ok) return;
      const data = (await res.json()) as SummaryRecord;
      setRecord(data);
      poll(data.id);
    } catch {
      /* ignore */
    }
  };

  const onCopy = async () => {
    if (!record?.summary) return;
    await navigator.clipboard.writeText(record.summary);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const status: Status = record?.status ?? 'idle';
  const isActive = ACTIVE.includes(status);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Summarize a French document</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <label htmlFor="ai-doc" className="text-sm font-medium">
            Document (PDF, DOCX, or TXT &middot; max 512 KB)
          </label>
          <Input
            id="ai-doc"
            type="file"
            accept=".pdf,.docx,.txt"
            onChange={onFileChange}
            disabled={busy || isActive}
          />
          {file && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <FileText className="h-4 w-4" />
              {file.name} ({Math.ceil(file.size / 1024)} KB)
            </p>
          )}
        </div>

        <div className="flex items-center gap-3">
          <Button onClick={onSubmit} disabled={!file || busy || isActive}>
            {busy || isActive ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {busy || isActive ? 'Working…' : 'Summarize'}
          </Button>
          {status !== 'idle' && (
            <Badge variant={status === 'failed' ? 'destructive' : 'secondary'}>
              {STATUS_LABEL[status]}
            </Badge>
          )}
        </div>

        {clientError && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Error</AlertTitle>
            <AlertDescription>{clientError}</AlertDescription>
          </Alert>
        )}

        {status === 'failed' && record?.error_message && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Summarization failed</AlertTitle>
            <AlertDescription className="space-y-3">
              <p>{record.error_message}</p>
              <Button size="sm" variant="outline" onClick={onRetry}>
                Retry
              </Button>
            </AlertDescription>
          </Alert>
        )}

        {status === 'completed' && record?.summary && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-sm font-semibold">
                <CheckCircle className="h-4 w-4 text-green-600" />
                English summary
              </h3>
              <Button size="sm" variant="ghost" onClick={onCopy}>
                <Copy className="h-4 w-4" />
                {copied ? 'Copied' : 'Copy'}
              </Button>
            </div>
            <div className="whitespace-pre-wrap rounded-md border bg-muted/40 p-4 text-sm">
              {record.summary}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
