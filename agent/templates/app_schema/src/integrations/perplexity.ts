import { z } from 'zod';
import * as process from 'process';
import fetch from 'node-fetch';
import { env } from '../env';

interface DomainFilter {
  include?: string[];
  exclude?: string[];
}

export interface PerplexitySearchParams {
  query: string;
  search_type: 'news' | 'market' | 'weather' | 'web';
  recency_filter?: string;
  domain_filter?: DomainFilter;
}

interface SearchResponse {
  query: string;
  type: string;
  result: string;
}

const searchPerplexity = async (
  params: PerplexitySearchParams
): Promise<SearchResponse> => {
  if (!env.PERPLEXITY_API_KEY) {
    throw new Error('PERPLEXITY_API_KEY is not set');
  }

  let searchQuery: string;
  switch (params.search_type) {
    case 'news':
      searchQuery = `Latest news about: ${params.query}`;
      break;
    case 'market':
      searchQuery = `Current market data for: ${params.query}`;
      break;
    case 'weather':
      searchQuery = `Current weather conditions in: ${params.query}`;
      break;
    case 'web':
      searchQuery = `Search the web for: ${params.query}`;
      break;
    default:
      searchQuery = params.query;
  }

  const options = {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${process.env['PERPLEXITY_API_KEY']}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: 'sonar',
      messages: [{ role: 'user', content: searchQuery }],
      temperature: 0.7,
      max_tokens: 250,
      max_results: 10,
    }),
  };

  const response = await fetch(
    'https://api.perplexity.ai/chat/completions',
    options
  );

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(
      `Perplexity API error: ${response.status}\nDetails: ${errorText}\nRequest: ${options.body}`
    );
  }

  const data = await response.json();

  if (!data?.choices?.[0]?.message?.content) {
    throw new Error('Invalid response from Perplexity API');
  }

  return {
    query: searchQuery,
    type: params.search_type,
    result: data.choices[0].message.content,
  };
};

export const webSearchParamsSchema = z.object({
  query: z.string(),
});

export type WebSearchParams = z.infer<typeof webSearchParamsSchema>;

export const handle_search_web = async (options: WebSearchParams): Promise<string> => {
  return searchPerplexity({
    query: options.query,
    search_type: 'web',
  }).then((result) => {
    return result.result;
  });
};

export const can_handle_search_web = (): boolean => {
  return env.PERPLEXITY_API_KEY !== undefined && env.PERPLEXITY_API_KEY !== '';
};
