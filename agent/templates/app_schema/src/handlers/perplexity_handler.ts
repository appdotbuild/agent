import { GenericHandler, type Message } from "../common/handler";
import * as process from 'process';
import fetch from 'node-fetch';

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

const handle = async (params: PerplexitySearchParams): Promise<SearchResponse> => {
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
            'Authorization': `Bearer ${process.env["PERPLEXITY_API_KEY"]}`,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            model: 'sonar',
            messages: [
                { role: 'user', content: searchQuery }
            ],
            temperature: 0.7,
            max_tokens: 250,
            max_results: 10
        })
    };

    const response = await fetch('https://api.perplexity.ai/chat/completions', options);
    
    if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Perplexity API error: ${response.status}\nDetails: ${errorText}\nRequest: ${options.body}`);
    }
    
    const data = await response.json();
    
    if (!data?.choices?.[0]?.message?.content) {
        throw new Error('Invalid response from Perplexity API');
    }

    return {
        query: searchQuery,
        type: params.search_type,
        result: data.choices[0].message.content
    };
};

const preProcessor = async (messages: Message[]): Promise<PerplexitySearchParams> => {
    const userMessage = messages.findLast((m: Message) => m.role === 'user');
    if (!userMessage) {
        throw new Error("No user message found");
    }

    let recency_filter: string;
    let domain_filter: DomainFilter;
    let search_type: PerplexitySearchParams['search_type'];
    const content = userMessage.content.toLowerCase();    
    if (content.match(/news|latest|current events/)) {
        search_type = 'news';
        recency_filter = 'day';
        domain_filter = { include: ['reuters.com', 'apnews.com', 'bloomberg.com'] };
    } else if (content.match(/stock|market|price|trading/)) {
        search_type = 'market';
        recency_filter = 'day';
        domain_filter = { include: ['finance.yahoo.com', 'marketwatch.com', 'investing.com'] };
    } else if (content.match(/weather|temperature|forecast/)) {
        search_type = 'weather';
        recency_filter = 'day';
        domain_filter = { include: ['weather.com', 'accuweather.com'] };
    } else {
        search_type = 'web';
        recency_filter = 'day';
        domain_filter = { include: ['google.com', 'bing.com', 'duckduckgo.com'] };
    }
    
    return {
        query: userMessage.content,
        search_type,
        recency_filter: recency_filter,
        domain_filter: domain_filter
    };
};

const postProcessor = async (output: SearchResponse, messages: Message[]): Promise<Message[]> => {
    let responseText: string;

    switch (output.type) {
        case 'news':
            responseText = `Here are the latest news updates:\n\n${output.result}`;
            break;
        case 'market':
            responseText = `Current market information:\n\n${output.result}`;
            break;
        case 'weather':
            responseText = `Weather information:\n\n${output.result}`;
            break;
        case 'web':
            responseText = `Search results:\n\n${output.result}`;
            break;
        default:
            responseText = `Cannot reply to this query.`;
    }
    
    return [{ role: 'assistant', content: responseText }];
};

export const perplexityHandler = new GenericHandler(
    handle,
    preProcessor,
    postProcessor
);

export const perplexityWebSearchHandler = new GenericHandler(
    (params: PerplexitySearchParams) => handle({ ...params, search_type: 'web' }),
    preProcessor,
    postProcessor
);

export const perplexityNewsSearchHandler = new GenericHandler(
    (params: PerplexitySearchParams) => handle({ ...params, search_type: 'news' }),
    preProcessor,
    postProcessor
);

export const perplexityMarketSearchHandler = new GenericHandler(
    (params: PerplexitySearchParams) => handle({ ...params, search_type: 'market' }),
    preProcessor,
    postProcessor
);

export const perplexityWeatherSearchHandler = new GenericHandler(
    (params: PerplexitySearchParams) => handle({ ...params, search_type: 'weather' }),
    preProcessor,
    postProcessor
);