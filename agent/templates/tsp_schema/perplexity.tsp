import "./helpers.js";

/* we won't be parsing these models for now but will generate ts with emitters */
model DomainFilter {
  include?: string[];
  exclude?: string[];
}

model SearchResponse {
  query: string;
  type: string;
  result: string;
}

model SearchParams {
  query: string;
  search_type: "news" | "market" | "weather" | "web";
  recency_filter?: string;
  domain_filter?: DomainFilter;
}

interface Perplexity {
  @custom_func(1, "perplexityWebSearchHandler")
  webSearch(query: string): SearchResponse;

  @custom_func(1, "perplexityNewsSearchHandler")
  newsSearch(query: string): SearchResponse;

  @custom_func(1, "perplexityMarketSearchHandler")
  marketSearch(query: string): SearchResponse;

  @custom_func(1, "perplexityWeatherSearchHandler")
  weatherSearch(query: string): SearchResponse;
}