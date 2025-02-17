import { GenericHandler, type Message } from "../common/handler";

interface DomainFilter {
    include?: string[];
    exclude?: string[];
}

interface SearchConfig {
    domain_filter?: DomainFilter;
    recency_filter?: string;
}

export interface PerplexitySearchParams {
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
            max_tokens: 1024
        })
    };

    //console.log('Request options:', {
    //    url: 'https://api.perplexity.ai/chat/completions',
    //    headers: options.headers,
    //    body: JSON.parse(options.body)
    //});

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
        default:
            responseText = `Search results:\n\n${output.result}`;
    }
    
    return [{ role: 'assistant', content: responseText }];
};

export const perplexityHandler = new GenericHandler(
    handle,
    preProcessor,
    postProcessor
);
