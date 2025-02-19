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
  @llm_func(2)
  @handler("perplexityHandler")
  search(params: SearchParams): SearchResponse;

  @llm_func(2)
  @handler("perplexityWebSearchHandler")
  webSearch(query: string): SearchResponse;

  @llm_func(2)
  @handler("perplexityNewsSearchHandler")
  newsSearch(query: string): SearchResponse;

  @llm_func(2)
  @handler("perplexityMarketSearchHandler")
  marketSearch(query: string): SearchResponse;

  @llm_func(2)
  @handler("perplexityWeatherSearchHandler")
  weatherSearch(query: string): SearchResponse;
}