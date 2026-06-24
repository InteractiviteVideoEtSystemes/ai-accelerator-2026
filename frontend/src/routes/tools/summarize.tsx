/**
 * AI Summarizing Route
 */

import { createFileRoute } from '@tanstack/react-router';
import { UIEngine } from '@/engine';
import aiSummarizePage from '@/pages/ai-summarize.json';
import type { PageDefinition } from '@/engine/types';

export const Route = createFileRoute('/tools/summarize')({
  component: AiSummarizePage,
});

function AiSummarizePage() {
  return <UIEngine page={aiSummarizePage as PageDefinition} />;
}
