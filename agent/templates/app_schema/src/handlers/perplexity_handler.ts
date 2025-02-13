import { GenericHandler, type Message } from "../common/handler";
import { Perplexity } from "perplexity-js";

interface DomainFilter {
    include?: string[];
    exclude?: string[];
}

interface SearchConfig {
    domain_filter?: DomainFilter;
    recency_filter?: string;
}

interface PerplexitySearchParams {
    query: string;
    search_type: 'news' | 'market' | 'weather' | 'web';
    model_size?: string;
    max_results?: number;
    recency_filter?: string;
    domain_filter?: DomainFilter;
}

interface SearchResponse {
    query: string;
    type: string;
    result: string;
}

const searchConfigs: Record<string, SearchConfig> = {
    news: {
        domain_filter: { include: ['reuters.com', 'apnews.com', 'bloomberg.com'] },
        recency_filter: 'day'
    },
    market: {
        domain_filter: { include: ['finance.yahoo.com', 'marketwatch.com', 'investing.com'] },
        recency_filter: 'day'
    },
    weather: {
        domain_filter: { include: ['weather.com', 'accuweather.com'] },
        recency_filter: 'day'
    },
    web: {} // No specific filters for general web search
};

const handle = async (params: PerplexitySearchParams): Promise<SearchResponse> => {
    const config = searchConfigs[params.search_type] || {};
    
    const mergedConfig = {
        domain_filter: params.domain_filter || config.domain_filter,
        recency_filter: params.recency_filter || config.recency_filter
    };

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
        default:
            searchQuery = params.query;
    }
    
    const perplexity = new Perplexity({
        apiKey: process.env['PERPLEXITY_API_KEY'] || ''
    });

    const response = await perplexity.search({
        query: searchQuery,
        maxResults: params.max_results || 2000,
        domainFilter: mergedConfig.domain_filter,
        searchRecencyFilter: mergedConfig.recency_filter
    });

    return {
        query: searchQuery,
        type: params.search_type,
        result: response.content[0].text
    };
};

const preProcessor = async (messages: Message[]): Promise<PerplexitySearchParams> => {
    const userMessage = messages.findLast((m: Message) => m.role === 'user');
    if (!userMessage) {
        throw new Error("No user message found");
    }

    const content = userMessage.content.toLowerCase();
    
    let search_type: PerplexitySearchParams['search_type'];
    if (content.match(/news|latest|current events/)) {
        search_type = 'news';
    } else if (content.match(/stock|market|price|trading/)) {
        search_type = 'market';
    } else if (content.match(/weather|temperature|forecast/)) {
        search_type = 'weather';
    } else {
        search_type = 'web';
    }
    
    return {
        query: userMessage.content,
        search_type,
        model_size: 'medium',
        max_results: 2000
    };
};

const postProcessor = async (output: SearchResponse, messages: Message[]): Promise<Message[]> => {
    let response: string;

    switch (output.type) {
        case 'news':
            response = `Here are the latest news updates:\n\n${output.result}`;
            break;
        case 'market':
            response = `Current market information:\n\n${output.result}`;
            break;
        case 'weather':
            response = `Weather information:\n\n${output.result}`;
            break;
        default:
            response = `Search results:\n\n${output.result}`;
    }
    
    return [{ role: 'assistant', content: response }];
};

export const perplexityHandler = new GenericHandler(
    handle,
    preProcessor,
    postProcessor
);
