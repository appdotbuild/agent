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
}

interface SearchResponse {
  query: string;
  result: string;
}

const searchPerplexity = async (
  params: PerplexitySearchParams
): Promise<SearchResponse> => {
  if (!env.PERPLEXITY_API_KEY) {
    throw new Error('PERPLEXITY_API_KEY is not set');
  }

  const options = {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${process.env['PERPLEXITY_API_KEY']}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: 'sonar',
      messages: [{ role: 'user', content: params.query }],
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
    query: params.query,
    result: data.choices[0].message.content,
  };
};

export const webSearchParamsSchema = z.object({
  query: z.string(),
});

// web search
export type WebSearchParams = z.infer<typeof webSearchParamsSchema>;

export const handle_search_web = async (options: WebSearchParams): Promise<string> => {
  return searchPerplexity({
    query: options.query,
  }).then((result) => {
    return result.result;
  });
};

// news search
export const newsSearchParamsSchema = z.object({
  query: z.string(),
  date_range: z.enum(['day', 'week', 'month', 'year']).optional(),
  sort_by: z.enum(['relevance', 'date']).optional(),
  include_images: z.boolean().optional(),
  include_videos: z.boolean().optional(),
  include_sources: z.boolean().optional(),
  region: z.string().optional(),
  language: z.string().optional()
});

export type NewsSearchParams = z.infer<typeof newsSearchParamsSchema>;

export const handle_search_news = async (options: NewsSearchParams): Promise<string> => {
  return searchPerplexity({
    query: `Latest news about ${options.query} ${options.date_range ? `from the last ${options.date_range}` : ''} ${options.sort_by ? `sorted by ${options.sort_by}` : ''} ${options.include_images ? 'with images' : ''} ${options.include_videos ? 'with videos' : ''} ${options.include_sources ? 'with sources' : ''} ${options.region ? `in ${options.region}` : ''} ${options.language ? `in ${options.language}` : ''}`,
  }).then((result) => {
    return result.result;
  });
};

// market search
export const marketSearchParamsSchema = z.object({
  symbol: z.string(),
  currency: z.enum(['USD', 'EUR', 'GBP', 'JPY', 'CHF', 'CAD', 'AUD', 'NZD', 'CNY', 'HKD', 'INR', 'BRL', 'ARS', 'CLP', 'COP', 'MXN', 'PEN', 'PYG', 'UYU', 'VND', 'ZAR']).optional(),
  include_forecast: z.boolean().optional(),
  include_chart: z.boolean().optional(),
  include_news: z.boolean().optional(),
  include_stats: z.boolean().optional(),
  include_events: z.boolean().optional(),
  include_sources: z.boolean().optional(),
  include_related: z.boolean().optional(),
  include_related_news: z.boolean().optional(),
  include_related_events: z.boolean().optional(),
});

export type MarketSearchParams = z.infer<typeof marketSearchParamsSchema>;

export const handle_search_market = async (options: MarketSearchParams): Promise<string> => {
  return searchPerplexity({
    query: `Current market data for ${options.symbol} ${options.currency ? `in ${options.currency}` : ''} ${options.include_forecast ? 'with a forecast' : ''} ${options.include_chart ? 'with a chart' : ''} ${options.include_news ? 'with news' : ''} ${options.include_stats ? 'with stats' : ''} ${options.include_events ? 'with events' : ''} ${options.include_sources ? 'with sources' : ''} ${options.include_related ? 'with related' : ''} ${options.include_related_news ? 'with related news' : ''} ${options.include_related_events ? 'with related events' : ''}`,
  }).then((result) => {
    return result.result;
  });
};

// weather search
export const weatherSearchParamsSchema = z.object({
  location: z.string(),
  unit: z.enum(['celsius', 'fahrenheit']).optional(),
  include_forecast: z.boolean().optional(),
});

export type WeatherSearchParams = z.infer<typeof weatherSearchParamsSchema>;

export const handle_search_weather = async (options: WeatherSearchParams): Promise<string> => {
  return searchPerplexity({
    query: `Current weather in ${options.location} is ${options.unit} and ${options.include_forecast ? 'includes a forecast' : 'does not include a forecast'}`,
  }).then((result) => {
    return result.result;
  });
};

export const can_handle = (): boolean => {
  return env.PERPLEXITY_API_KEY !== undefined;
};
